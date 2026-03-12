from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import settings
from app.database.base import Base
from app.database.session import engine
from app.models.admin_user import AdminUser


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def seed_default_admin(db: Session) -> None:
    admin = db.query(AdminUser).filter(AdminUser.email == settings.DEFAULT_ADMIN_EMAIL).first()
    if admin:
        return

    default_admin = AdminUser(
        email=settings.DEFAULT_ADMIN_EMAIL,
        password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
        is_active=True,
    )
    db.add(default_admin)
    db.commit()
