from datetime import datetime, timezone
import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_admin
from ..models import AdminUser, Notice, NoticeCategory
from ..schemas import CategoryItem, NoticeResponse
from ..storage import (
    R2ConfigurationError,
    R2StorageError,
    delete_notice_file_by_url,
    is_managed_notice_file_url,
    upload_notice_file,
)

router = APIRouter(prefix="/notices", tags=["notices"])
logger = logging.getLogger(__name__)

CATEGORY_LABELS: dict[NoticeCategory, str] = {
    NoticeCategory.TENDERS: "Tenders",
    NoticeCategory.UPCOMING_EVENTS: "Upcoming Events",
    NoticeCategory.NOTIFICATIONS: "Notifications",
    NoticeCategory.NOTICES: "Notices",
}


def parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field_name}. Use ISO-8601 date-time format.",
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def file_name_from_url(file_url: str | None) -> str | None:
    if not file_url:
        return None
    parsed = urlparse(file_url)
    path = parsed.path or file_url
    name = Path(path).name
    return name or None


async def upload_notice_attachment(file: UploadFile) -> tuple[str, str]:
    try:
        uploaded = await upload_notice_file(file)
    except R2ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except R2StorageError as exc:
        message = str(exc)
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY if "empty" in message.lower() else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=http_status, detail=message) from exc

    return uploaded.public_url, uploaded.original_name


async def safe_delete_notice_file(file_url: str | None) -> None:
    if not is_managed_notice_file_url(file_url):
        return

    try:
        await delete_notice_file_by_url(file_url)
    except (R2ConfigurationError, R2StorageError):
        logger.warning("Failed to delete R2 object for notice file URL: %s", file_url, exc_info=True)


def get_notice_or_404(db: Session, notice_id: int) -> Notice:
    notice = db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found.")
    return notice


@router.get("/categories", response_model=list[CategoryItem])
def list_categories() -> list[CategoryItem]:
    return [CategoryItem(value=key, label=value) for key, value in CATEGORY_LABELS.items()]


@router.get("", response_model=list[NoticeResponse])
def list_public_notices(
    publish_to: NoticeCategory | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Notice]:
    now = datetime.now(timezone.utc)
    stmt = select(Notice).where(Notice.is_active.is_(True)).where(
        or_(Notice.publish_date.is_(None), Notice.publish_date <= now)
    )

    if publish_to:
        stmt = stmt.where(Notice.publish_to == publish_to)

    stmt = stmt.order_by(desc(Notice.pinned), desc(Notice.publish_date), desc(Notice.created_at)).limit(limit)
    return list(db.scalars(stmt))


@router.get("/admin", response_model=list[NoticeResponse])
def list_admin_notices(
    publish_to: NoticeCategory | None = Query(default=None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> list[Notice]:
    stmt = select(Notice)
    if publish_to:
        stmt = stmt.where(Notice.publish_to == publish_to)

    stmt = stmt.order_by(desc(Notice.pinned), desc(Notice.publish_date), desc(Notice.created_at))
    return list(db.scalars(stmt))


@router.get("/admin/{notice_id}", response_model=NoticeResponse)
def get_admin_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> Notice:
    return get_notice_or_404(db, notice_id)


@router.post("/admin", response_model=list[NoticeResponse], status_code=status.HTTP_201_CREATED)
async def create_notice(
    title: str = Form(...),
    description: str = Form(default=""),
    publish_to: list[NoticeCategory] = Form(...),
    link: str | None = Form(default=None),
    file_url: str | None = Form(default=None),
    pinned: bool = Form(default=False),
    published: bool = Form(default=True),
    publish_date: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
) -> list[Notice]:
    cleaned_title = title.strip()
    if not cleaned_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Title is required.",
        )

    publish_targets = list(dict.fromkeys(publish_to))
    if not publish_targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one publish_to category is required.",
        )

    stored_file_url = normalize_optional_text(file_url)
    stored_file_name = file_name_from_url(stored_file_url)
    uploaded_file_url_for_cleanup: str | None = None

    if file is not None:
        stored_file_url, stored_file_name = await upload_notice_attachment(file)
        uploaded_file_url_for_cleanup = stored_file_url

    notice_publish_date = parse_optional_datetime(publish_date, "publish_date") or datetime.now(timezone.utc)
    notices: list[Notice] = []

    for target in publish_targets:
        notice = Notice(
            title=cleaned_title,
            description=description.strip(),
            publish_to=target,
            link=normalize_optional_text(link),
            file_url=stored_file_url,
            file_name=stored_file_name,
            pinned=pinned,
            is_active=published,
            publish_date=notice_publish_date,
            created_by_id=current_admin.id,
        )
        db.add(notice)
        notices.append(notice)

    try:
        db.commit()
        for notice in notices:
            db.refresh(notice)
    except SQLAlchemyError as exc:
        db.rollback()
        await safe_delete_notice_file(uploaded_file_url_for_cleanup)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save notice in database.",
        ) from exc

    return notices


@router.patch("/admin/{notice_id}", response_model=NoticeResponse)
async def update_notice(
    notice_id: int,
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    publish_to: NoticeCategory | None = Form(default=None),
    link: str | None = Form(default=None),
    file_url: str | None = Form(default=None),
    pinned: bool | None = Form(default=None),
    published: bool | None = Form(default=None),
    publish_date: str | None = Form(default=None),
    remove_file: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> Notice:
    notice = get_notice_or_404(db, notice_id)
    previous_file_url = notice.file_url
    uploaded_file_url_for_cleanup: str | None = None

    if title is not None:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Title is required.",
            )
        notice.title = cleaned_title

    if description is not None:
        notice.description = description.strip()
    if publish_to is not None:
        notice.publish_to = publish_to
    if link is not None:
        notice.link = normalize_optional_text(link)
    if pinned is not None:
        notice.pinned = pinned
    if published is not None:
        notice.is_active = published
    if publish_date is not None:
        parsed_publish_date = parse_optional_datetime(publish_date, "publish_date")
        notice.publish_date = parsed_publish_date or datetime.now(timezone.utc)

    if file is not None:
        notice.file_url, notice.file_name = await upload_notice_attachment(file)
        uploaded_file_url_for_cleanup = notice.file_url
    elif remove_file:
        notice.file_url = None
        notice.file_name = None
    elif file_url is not None:
        normalized_url = normalize_optional_text(file_url)
        notice.file_url = normalized_url
        notice.file_name = file_name_from_url(normalized_url)

    try:
        db.add(notice)
        db.commit()
        db.refresh(notice)
    except SQLAlchemyError as exc:
        db.rollback()
        if uploaded_file_url_for_cleanup and uploaded_file_url_for_cleanup != previous_file_url:
            await safe_delete_notice_file(uploaded_file_url_for_cleanup)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notice in database.",
        ) from exc

    if previous_file_url != notice.file_url:
        await safe_delete_notice_file(previous_file_url)

    return notice


@router.delete("/admin/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
) -> None:
    notice = get_notice_or_404(db, notice_id)
    file_url = notice.file_url

    try:
        db.delete(notice)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notice from database.",
        ) from exc

    await safe_delete_notice_file(file_url)
    return None
