import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AdminUser

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def is_valid_bcrypt_hash(password_hash: str) -> bool:
    """Check if the password hash is a valid bcrypt hash.
    
    Accepts $2a$, $2b$, and $2y$ prefixes (all valid bcrypt variants).
    Standard bcrypt hash length is 60 characters.
    """
    if not password_hash:
        return False
    # Accept $2a$, $2b$, $2y$ - all valid bcrypt prefixes
    return password_hash.startswith(("$2a$", "$2b$", "$2y$")) and len(password_hash) == 60


def migrate_password_to_bcrypt(db: Session, admin: AdminUser, plain_password: str) -> None:
    """Migrate a plain text password to bcrypt hash and update the database."""
    logger.info(f"Migrating password for user '{admin.username}' from plain text to bcrypt")
    admin.password_hash = get_password_hash(plain_password)
    db.commit()


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify password with try/except to prevent crashes from invalid hashes."""
    if not password_hash:
        logger.warning("Empty password hash encountered during verification")
        return False
    
    # Trim whitespace from stored hash before verification
    password_hash = password_hash.strip()
    
    # Check if it's a valid bcrypt hash
    if not is_valid_bcrypt_hash(password_hash):
        logger.warning("Invalid bcrypt hash format detected - possible plain text password")
        # If it looks like plain text (short and doesn't start with $2), treat as invalid
        if len(password_hash) < 60 and not password_hash.startswith("$"):
            logger.info("Detected potential plain text password - treating as invalid")
            return False
        # For other invalid formats, still try verification (let passlib handle errors gracefully)
    
    try:
        result = pwd_context.verify(plain_password, password_hash)
        return result
    except Exception as e:
        logger.error(f"Error verifying password: {type(e).__name__}: {e}")
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(*, subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def authenticate_admin(db: Session, username: str, password: str) -> AdminUser | None:
    """Authenticate admin user with robust error handling."""
    logger.info(f"Attempting authentication for username: {username}")
    
    admin = db.scalar(select(AdminUser).where(AdminUser.username == username))
    if not admin:
        logger.warning(f"Admin user not found: {username}")
        return None

    if not admin.is_active:
        logger.warning(f"Inactive admin attempted login: {username}")
        return None
    
    if not verify_password(password, admin.password_hash):
        logger.warning(f"Password verification failed for username: {username}")
        return None
    
    logger.info(f"Successfully authenticated username: {username}")
    return admin


def ensure_default_admin(db: Session) -> None:
    existing = db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username))
    if existing:
        changed = False
        if not existing.email:
            existing.email = settings.default_admin_email
            changed = True
        if not existing.is_active:
            existing.is_active = True
            changed = True

        current_password_ok = verify_password(settings.admin_password, existing.password_hash)
        legacy_password_ok = (
            settings.default_admin_password != settings.admin_password
            and verify_password(settings.default_admin_password, existing.password_hash)
        )

        if not current_password_ok and legacy_password_ok:
            logger.info(
                "Migrating legacy default admin password to current ADMIN_PASSWORD for username '%s'.",
                existing.username,
            )
            existing.password_hash = get_password_hash(settings.admin_password)
            changed = True

        if changed:
            db.add(existing)
            db.commit()
        return

    default_admin = AdminUser(
        email=settings.default_admin_email,
        username=settings.admin_username,
        password_hash=get_password_hash(settings.admin_password),
        is_active=True,
    )
    db.add(default_admin)
    db.commit()
