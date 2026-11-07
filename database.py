import sqlite3
from pathlib import Path
from flask import g, current_app


def get_db():
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)

        g.db = sqlite3.connect(
            str(db_path),
            timeout=30
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")

    return g.db


def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    db_path = Path(current_app.config["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(db_path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT UNIQUE NOT NULL,
            extracted_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            analysis_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            document_id INTEGER,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
        );
        """)

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
            CREATE INDEX IF NOT EXISTS idx_documents_user
            ON documents(user_id, id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_user
            ON activity_log(user_id, id)
        """)

        db.commit()

    finally:
        db.close()