from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import quote, unquote
from uuid import uuid4

from fastapi import UploadFile

from ..config import settings

NOTICE_UPLOAD_PREFIX = "public"

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:
    boto3 = None
    Config = None

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass


class R2ConfigurationError(RuntimeError):
    pass


class R2StorageError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class UploadedNoticeFile:
    key: str
    public_url: str
    original_name: str
    content_type: str


def _missing_r2_settings() -> list[str]:
    required_settings = {
        "R2_ENDPOINT": settings.r2_endpoint,
        "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
        "R2_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
        "R2_BUCKET": settings.r2_bucket,
        "R2_PUBLIC_URL": settings.r2_public_url,
    }
    return [name for name, value in required_settings.items() if not value]


def _ensure_r2_configured() -> None:
    missing = _missing_r2_settings()
    if missing:
        raise R2ConfigurationError(
            "Missing Cloudflare R2 configuration: "
            + ", ".join(missing)
            + ". Set these environment variables before uploading files."
        )


@lru_cache(maxsize=1)
def get_r2_client():
    _ensure_r2_configured()
    if boto3 is None or Config is None:
        raise R2ConfigurationError(
            "Missing dependency 'boto3'. Install it with: pip install -r requirements.txt"
        )

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _guess_content_type(file: UploadFile) -> str:
    explicit = (file.content_type or "").strip()
    if explicit:
        return explicit

    guessed, _ = guess_type(file.filename or "")
    return guessed or "application/octet-stream"


def _build_notice_key(original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    if len(suffix) > 16:
        suffix = ""

    return f"{NOTICE_UPLOAD_PREFIX}/{uuid4().hex}{suffix}"


def _build_public_url(file_key: str) -> str:
    encoded_key = quote(file_key, safe="/")
    return f"{settings.r2_public_url}/{encoded_key}"


def _extract_key_from_url(file_url: str | None) -> str | None:
    if not file_url:
        return None

    base = settings.r2_public_url
    if not base:
        return None

    normalized = file_url.strip()
    prefix = f"{base}/"
    if not normalized.startswith(prefix):
        return None

    encoded_key = normalized[len(prefix) :]
    key = unquote(encoded_key)
    return key or None


def is_managed_notice_file_url(file_url: str | None) -> bool:
    return _extract_key_from_url(file_url) is not None


async def upload_notice_file(file: UploadFile) -> UploadedNoticeFile:
    try:
        _ensure_r2_configured()

        original_name = (file.filename or "upload").strip() or "upload"
        file_key = _build_notice_key(original_name)
        content_type = _guess_content_type(file)

        payload = await file.read()
        if not payload:
            raise R2StorageError("Uploaded file is empty.")

        client = get_r2_client()

        try:
            await asyncio.to_thread(
                client.put_object,
                Bucket=settings.r2_bucket,
                Key=file_key,
                Body=payload,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError("Failed to upload file to Cloudflare R2.") from exc

        return UploadedNoticeFile(
            key=file_key,
            public_url=_build_public_url(file_key),
            original_name=original_name,
            content_type=content_type,
        )
    finally:
        await file.close()


async def delete_notice_file_by_url(file_url: str | None) -> None:
    file_key = _extract_key_from_url(file_url)
    if not file_key:
        return

    _ensure_r2_configured()
    client = get_r2_client()

    try:
        await asyncio.to_thread(
            client.delete_object,
            Bucket=settings.r2_bucket,
            Key=file_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError("Failed to delete file from Cloudflare R2.") from exc
