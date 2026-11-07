
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Render Persistent Disk path or local project directory
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE)))

class Config:
    # Secret key must be provided through environment variables
    SECRET_KEY = os.getenv("SECRET_KEY")

    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is required."
        )

    # SQLite database location
    DATABASE = os.getenv(
        "DATABASE",
        str(DATA_DIR / "lexibrief.db")
    )

    # Uploaded documents location
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        str(DATA_DIR / "uploads")
    )

    # Maximum upload size: 15 MB
    MAX_CONTENT_LENGTH = 15 * 1024 * 1024
