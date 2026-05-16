import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings


BASE_DIR = Path(__file__).resolve().parents[2]


def ensure_upload_directories() -> None:
    (BASE_DIR / settings.PHOTO_DIR).mkdir(parents=True, exist_ok=True)
    (BASE_DIR / settings.RECEIPT_DIR).mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "uploads/error_reports").mkdir(parents=True, exist_ok=True)


def save_upload_file(upload_file: UploadFile, destination_dir: str, prefix: str) -> str:
    destination = BASE_DIR / destination_dir
    destination.mkdir(parents=True, exist_ok=True)

    extension = Path(upload_file.filename or "").suffix
    safe_name = f"{prefix}_{uuid4().hex}{extension}"
    file_path = destination / safe_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")


def save_upload_file_bytes(file_buffer, destination_dir: str, filename: str) -> str:
    destination = BASE_DIR / destination_dir
    destination.mkdir(parents=True, exist_ok=True)
    file_path = destination / filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file_buffer, buffer)
    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")

