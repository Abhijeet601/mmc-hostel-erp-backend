import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import erp_models  # noqa: F401
import app.erp_models  # Ensure all models loaded for create_all
from .auth import ensure_default_admin
from .config import settings
from .database import Base, SessionLocal, engine
from .migrations import (
    migrate_admin_users_username,
    migrate_hostel_application_allocation_fields,
    migrate_hostel_application_cycle_fields,
    migrate_hostel_application_allotted_category,
    migrate_hostel_complaints_table,
    migrate_hostel_room_fields,
    migrate_hostel_students_old_fields,
    migrate_notices_is_active,
    migrate_notices_publish_date,
    migrate_plaintext_passwords,
    seed_default_hostel_rooms,
)
from .routers.auth import router as auth_router
from .routers.erp_admin import router as erp_admin_router
from .routers.erp_student import router as erp_student_router
from .routers.notices import router as notices_router
from .routers.old_students import router as old_students_router
from .seed_notices import sync_notice_folder_to_db

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    @app.on_event("startup")
    def startup_event() -> None:
        Base.metadata.create_all(bind=engine)
        migrate_admin_users_username(engine)
        migrate_notices_publish_date(engine)
        migrate_notices_is_active(engine)
        migrate_hostel_application_allocation_fields(engine)
        migrate_hostel_application_cycle_fields(engine)
        migrate_hostel_application_allotted_category(engine)
        migrate_hostel_complaints_table(engine)
        migrate_hostel_room_fields(engine)
        migrate_hostel_students_old_fields(engine)
        
        # Check for plain text passwords on startup
        logger.info("Running password migration check on startup...")
        migration_result = migrate_plaintext_passwords(engine, SessionLocal)
        
        if migration_result["needs_migration"]:
            for item in migration_result["needs_migration"]:
                logger.warning(
                    f"SECURITY: Plain text password detected for admin '{item['username']}'. "
                    f"Please run password migration manually. "
                    f"To migrate, use: force_migrate_plaintext_password(engine, SessionLocal, '{item['username']}', '<plain_password>')"
                )
        
        if migration_result["errors"]:
            for item in migration_result["errors"]:
                logger.error(f"Password hash error for admin '{item.get('username', 'unknown')}': {item.get('issue', 'Unknown error')}")
        
        logger.info(f"Password check complete. Checked: {migration_result['checked']}, Needs migration: {len(migration_result['needs_migration'])}")
        
        with SessionLocal() as db:
            ensure_default_admin(db)
            seed_default_hostel_rooms(db)
            sync_notice_folder_to_db(
                db,
                source_dir=Path(settings.notice_source_dir),
                upload_root=Path(settings.upload_dir),
            )

    @app.get(f"{settings.api_prefix}/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(erp_student_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(erp_admin_router, prefix=settings.api_prefix)
    app.include_router(old_students_router, prefix=settings.api_prefix)
    app.include_router(notices_router, prefix=settings.api_prefix)
    from .routers import activity_logs
    app.include_router(activity_logs.router, prefix=settings.api_prefix)


    return app


app = create_app()
