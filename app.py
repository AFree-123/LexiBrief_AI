import os
import sqlite3
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing Config
load_dotenv()

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
)

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from database import init_db, get_db, close_db
from services.document_service import extract_text
from services.ollama_service import ask_ollama


# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)
app.config.from_object(Config)

app.teardown_appcontext(close_db)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


# --------------------------------------------------
# DATABASE INITIALIZATION AND MIGRATION
# --------------------------------------------------

def ensure_database_schema():
    """Create dashboard tables and safely migrate older databases."""

    db = get_db()

    columns = [
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(documents)"
        ).fetchall()
    ]

    if "page_count" not in columns:
        db.execute(
            "ALTER TABLE documents ADD COLUMN page_count INTEGER DEFAULT 0"
        )

    db.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            document_id INTEGER,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
        )
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_user
        ON documents(user_id, id)
    """)

    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_activity_user
        ON activity_log(user_id, id)
    """)

    db.commit()

    # Backfill page counts for existing PDF files.
    existing_docs = db.execute("""
        SELECT id, stored_name
        FROM documents
        WHERE page_count = 0
    """).fetchall()

    for doc in existing_docs:
        file_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            doc["stored_name"]
        )

        if os.path.isfile(file_path) and Path(file_path).suffix.lower() == ".pdf":
            try:
                import fitz

                with fitz.open(file_path) as pdf:
                    db.execute(
                        "UPDATE documents SET page_count=? WHERE id=?",
                        (len(pdf), doc["id"])
                    )

            except Exception:
                pass

    db.commit()


with app.app_context():
    init_db()
    ensure_database_schema()


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def protected(fn):
    @wraps(fn)
    def inner(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return fn(*args, **kwargs)

    return inner


# --------------------------------------------------
# ACTIVITY LOGGER
# --------------------------------------------------

def log_activity(action, details, document_id=None):
    """Save actual user activity to SQLite."""

    if "user_id" not in session:
        return

    db = get_db()

    db.execute("""
        INSERT INTO activity_log
        (user_id, document_id, action, details)
        VALUES (?, ?, ?, ?)
    """, (
        session["user_id"],
        document_id,
        action,
        details
    ))

    db.commit()


# --------------------------------------------------
# PDF PAGE COUNT
# --------------------------------------------------

def get_page_count(file_path):
    """Return PDF page count. Other formats return zero."""

    if Path(file_path).suffix.lower() != ".pdf":
        return 0

    try:
        import fitz

        with fitz.open(file_path) as pdf:
            return len(pdf)

    except Exception:
        return 0


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def index():

    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 8:

            flash(
                "Enter all details. Password must be at least 8 characters.",
                "error"
            )

        else:

            db = get_db()

            try:

                db.execute("""
                    INSERT INTO users(name, email, password_hash)
                    VALUES (?, ?, ?)
                """, (
                    name,
                    email,
                    generate_password_hash(password)
                ))

                db.commit()

                flash("Account created. Please sign in.", "success")

                return redirect(url_for("login"))

            except sqlite3.IntegrityError:

                db.rollback()
                flash("Email already registered.", "error")

    return render_template("register.html")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session.clear()

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.", "error")

    return render_template("login.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@protected
def dashboard():

    db = get_db()
    uid = session["user_id"]

    total_documents = db.execute("""
        SELECT COUNT(*)
        FROM documents
        WHERE user_id=?
    """, (uid,)).fetchone()[0]

    pages_processed = db.execute("""
        SELECT COALESCE(SUM(page_count), 0)
        FROM documents
        WHERE user_id=?
    """, (uid,)).fetchone()[0]

    drafts_created = db.execute("""
        SELECT COUNT(*)
        FROM drafts
        WHERE user_id=?
    """, (uid,)).fetchone()[0]

    documents = db.execute("""
        SELECT id, original_name, created_at
        FROM documents
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 5
    """, (uid,)).fetchall()

    activities = db.execute("""
        SELECT details, action, created_at
        FROM activity_log
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 6
    """, (uid,)).fetchall()

    return render_template(
        "dashboard.html",
        total_documents=total_documents,
        pages_processed=pages_processed,
        drafts_created=drafts_created,
        documents=documents,
        activities=activities
    )


# --------------------------------------------------
# DOCUMENTS / UPLOAD
# --------------------------------------------------

@app.route("/documents", methods=["GET", "POST"])
@protected
def documents():

    if request.method == "POST":

        file = request.files.get("document")

        if not file or not file.filename:

            flash("Choose a file.", "error")

        elif "." not in file.filename or file.filename.rsplit(".", 1)[-1].lower() not in {
            "pdf", "docx", "txt"
        }:

            flash("Only PDF, DOCX and TXT are supported.", "error")

        else:

            name = secure_filename(file.filename)

            if not name:
                flash("Invalid filename.", "error")
                return redirect(url_for("documents"))

            stored = (
                f"{session['user_id']}_"
                f"{os.urandom(6).hex()}_{name}"
            )

            path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                stored
            )

            try:

                file.save(path)

                content = extract_text(path)

                if not content.strip():
                    raise ValueError(
                        "No embedded text found. Scanned PDFs need OCR."
                    )

                page_count = get_page_count(path)

                db = get_db()

                cursor = db.execute("""
                    INSERT INTO documents(
                        user_id,
                        original_name,
                        stored_name,
                        extracted_text,
                        page_count
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    session["user_id"],
                    name,
                    stored,
                    content[:500000],
                    page_count
                ))

                document_id = cursor.lastrowid

                db.commit()

                log_activity(
                    "upload",
                    f"Uploaded document: {name}",
                    document_id
                )

                flash(
                    "Document uploaded and text extracted.",
                    "success"
                )

            except Exception as error:

                db = get_db()
                db.rollback()

                if os.path.exists(path):
                    os.remove(path)

                app.logger.exception("Document upload or extraction failed")

                flash(
                    f"Processing failed: {error}",
                    "error"
                )

        return redirect(url_for("documents"))

    docs = get_db().execute("""
        SELECT *
        FROM documents
        WHERE user_id=?
        ORDER BY id DESC
    """, (
        session["user_id"],
    )).fetchall()

    return render_template(
        "documents.html",
        documents=docs
    )


# --------------------------------------------------
# GET DOCUMENT SAFELY
# --------------------------------------------------

def get_doc(doc_id):

    return get_db().execute("""
        SELECT *
        FROM documents
        WHERE id=? AND user_id=?
    """, (
        doc_id,
        session["user_id"]
    )).fetchone()


# --------------------------------------------------
# DOCUMENT ANALYSIS
# --------------------------------------------------

@app.route("/analyze/<int:doc_id>", methods=["GET", "POST"])
@protected
def analyze(doc_id):

    doc = get_doc(doc_id)

    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for("documents"))

    result = None

    if request.method == "POST":

        prompt = (
            "Review this legal document. Provide: summary, "
            "parties and obligations, dates/deadlines, "
            "potentially risky or unclear clauses, and "
            "questions to clarify. Do not invent facts, "
            "laws or citations. Say when information is absent. "
            "This is not legal advice.\n\n"
            + doc["extracted_text"][:16000]
        )

        result = ask_ollama(prompt)

        if result.get("ok"):

            db = get_db()

            db.execute("""
                INSERT INTO analyses(
                    document_id,
                    user_id,
                    analysis_text
                )
                VALUES (?, ?, ?)
            """, (
                doc_id,
                session["user_id"],
                result["text"]
            ))

            db.commit()

            log_activity(
                "analysis",
                f"Analyzed document: {doc['original_name']}",
                doc_id
            )

        else:
            flash(
                result.get("error", "AI analysis failed."),
                "error"
            )

    return render_template(
        "analyze.html",
        doc=doc,
        result=result.get("text") if result and result.get("ok") else None
    )


# --------------------------------------------------
# ASK DOCUMENTS
# --------------------------------------------------

@app.route("/ask/<int:doc_id>", methods=["GET", "POST"])
@protected
def ask(doc_id):

    doc = get_doc(doc_id)

    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for("documents"))

    answer = None
    question = ""

    if request.method == "POST":

        question = request.form.get("question", "").strip()

        if question:

            prompt = (
                "Answer only from this document. "
                "If the answer is not present, say so. "
                "Do not invent clause/page references. "
                "Not legal advice.\n"
                "QUESTION: " + question +
                "\nDOCUMENT:\n" +
                doc["extracted_text"][:16000]
            )

            response = ask_ollama(prompt)

            if response.get("ok"):

                answer = response["text"]

                log_activity(
                    "question",
                    f"Asked a question about: {doc['original_name']}",
                    doc_id
                )

            else:
                flash(
                    response.get("error", "AI request failed."),
                    "error"
                )

        else:
            flash("Enter a question about the document.", "error")

    return render_template(
        "ask.html",
        doc=doc,
        answer=answer,
        question=question
    )


# --------------------------------------------------
# COMPARE DOCUMENTS
# --------------------------------------------------

@app.route("/compare", methods=["GET", "POST"])
@protected
def compare():

    db = get_db()

    docs = db.execute("""
        SELECT *
        FROM documents
        WHERE user_id=?
        ORDER BY id DESC
    """, (
        session["user_id"],
    )).fetchall()

    result = None

    if request.method == "POST":

        try:

            a = int(request.form["a"])
            b = int(request.form["b"])

            doc1 = get_doc(a)
            doc2 = get_doc(b)

            if not doc1 or not doc2 or a == b:
                raise ValueError()

            prompt = (
                "Compare the two legal documents. "
                "List material differences in parties, dates, "
                "payment, obligations, termination and liability. "
                "Ground claims in supplied text; do not invent. "
                "Not legal advice.\n"
                "DOCUMENT A:\n"
                + doc1["extracted_text"][:8000]
                + "\nDOCUMENT B:\n"
                + doc2["extracted_text"][:8000]
            )

            response = ask_ollama(prompt)

            if response.get("ok"):

                result = response["text"]

                log_activity(
                    "compare",
                    (
                        "Compared documents: "
                        f"{doc1['original_name']} and "
                        f"{doc2['original_name']}"
                    )
                )

            else:
                flash(
                    response.get("error", "Document comparison failed."),
                    "error"
                )

        except (ValueError, KeyError, TypeError):

            flash(
                "Select two different uploaded documents.",
                "error"
            )

    return render_template(
        "compare.html",
        documents=docs,
        result=result
    )


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@protected
def settings():

    db = get_db()
    uid = session["user_id"]

    user = db.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":

        action = request.form.get("action")

        if action == "update_profile":

            name = request.form.get("name", "").strip()

            if not name:
                flash("Name cannot be empty.", "error")

            else:

                db.execute(
                    "UPDATE users SET name=? WHERE id=?",
                    (name, uid)
                )

                db.commit()

                session["user_name"] = name

                flash("Profile updated successfully.", "success")

        elif action == "change_password":

            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not check_password_hash(
                user["password_hash"], current_password
            ):

                flash("Current password is incorrect.", "error")

            elif len(new_password) < 8:

                flash("New password must contain at least 8 characters.", "error")

            elif new_password != confirm_password:

                flash("New passwords do not match.", "error")

            elif check_password_hash(
                user["password_hash"], new_password
            ):

                flash(
                    "Choose a password different from your current password.",
                    "error"
                )

            else:

                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new_password), uid)
                )

                db.commit()

                flash("Password changed successfully.", "success")

        else:
            flash("Invalid settings action.", "error")

        return redirect(url_for("settings"))

    user = db.execute(
        "SELECT * FROM users WHERE id=?",
        (uid,)
    ).fetchone()

    return render_template("settings.html", user=user)


# --------------------------------------------------
# DOCUMENT DOWNLOAD
# --------------------------------------------------

@app.route("/download/<int:doc_id>")
@protected
def download(doc_id):

    doc = get_doc(doc_id)

    if not doc:
        return "Not found", 404

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        doc["stored_name"],
        as_attachment=True
    )


# --------------------------------------------------
# APPLICATION ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )