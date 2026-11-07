import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "dev-only-change-this-secret"
    )

    DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE)))

    DATABASE = str(DATA_DIR / "lexibrief.db")
    UPLOAD_FOLDER = str(DATA_DIR / "uploads")

    MAX_CONTENT_LENGTH = 15 * 1024 * 1024