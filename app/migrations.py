import logging
import re

from passlib.context import CryptContext
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import AdminUser
from .config import settings
from .erp_models import ERPHostelRoom

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _normalize_username(candidate: str | None, fallback: str) -> str:
    raw = (candidate or "").strip().lower()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    raw = re.sub(r"[^a-z0-9._-]+", "_", raw).strip("._-")
    return raw or fallback


def _unique_email_candidate(base_username: str, used_emails: set[str]) -> str:
    candidate = f"{base_username}@admin.local"
    if candidate not in used_emails:
        return candidate

    suffix = 1
    while True:
        candidate = f"{base_username}{suffix}@admin.local"
        if candidate not in used_emails:
            return candidate
        suffix += 1


def migrate_admin_users_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "admin_users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("admin_users")}

    with engine.begin() as connection:
        if "username" not in columns:
            logger.info("Adding missing 'username' column to admin_users table.")
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN username VARCHAR(100)"))
            columns.add("username")

        if "email" not in columns:
            logger.info("Adding missing 'email' column to admin_users table.")
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN email VARCHAR(255)"))
            columns.add("email")

        if "is_active" not in columns:
            logger.info("Adding missing 'is_active' column to admin_users table.")
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            columns.add("is_active")

        if "updated_at" not in columns:
            logger.info("Adding missing 'updated_at' column to admin_users table.")
            connection.execute(text("ALTER TABLE admin_users ADD COLUMN updated_at DATETIME"))
            columns.add("updated_at")

        existing_rows = connection.execute(
            text(
                "SELECT id, email, username, created_at, updated_at, is_active "
                "FROM admin_users ORDER BY id"
            )
        ).mappings().all()

        used_usernames: set[str] = set()
        used_emails: set[str] = set()
        for row in existing_rows:
            current_email = (row.get("email") or "").strip().lower()
            current_username = row.get("username")

            base_username = _normalize_username(current_username or current_email, settings.admin_username)
            username = base_username
            suffix = 1
            while username in used_usernames:
                suffix += 1
                username = f"{base_username}{suffix}"
            used_usernames.add(username)

            email = current_email or _unique_email_candidate(base_username, used_emails)
            while email in used_emails:
                email = _unique_email_candidate(base_username, used_emails)
            used_emails.add(email)

            connection.execute(
                text(
                    "UPDATE admin_users "
                    "SET username = :username, "
                    "email = :email, "
                    "is_active = COALESCE(is_active, 1), "
                    "updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
                    "WHERE id = :id"
                ),
                {
                    "username": username,
                    "email": email,
                    "id": row["id"],
                },
            )

        try:
            # MySQL doesn't support CREATE INDEX IF NOT EXISTS, check manually
            result = connection.execute(
                text("""
                    SELECT 1 FROM information_schema.STATISTICS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'admin_users' 
                    AND INDEX_NAME = 'ix_admin_users_username'
                """)
            ).fetchone()
            if not result:
                connection.execute(
                    text("CREATE UNIQUE INDEX ix_admin_users_username ON admin_users (username)")
                )
        except Exception:
            logger.warning("Unable to create unique index on admin_users.username", exc_info=True)

        try:
            # MySQL doesn't support CREATE INDEX IF NOT EXISTS, check manually
            result = connection.execute(
                text("""
                    SELECT 1 FROM information_schema.STATISTICS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'admin_users' 
                    AND INDEX_NAME = 'ix_admin_users_email'
                """)
            ).fetchone()
            if not result:
                connection.execute(
                    text("CREATE UNIQUE INDEX ix_admin_users_email ON admin_users (email)")
                )
        except Exception:
            logger.warning("Unable to create unique index on admin_users.email", exc_info=True)


def migrate_admin_users_username(engine: Engine) -> None:
    migrate_admin_users_schema(engine)


def migrate_notices_publish_date(engine: Engine) -> None:
    inspector = inspect(engine)
    if "notices" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notices")}
    if "publish_date" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE notices ADD COLUMN publish_date DATETIME"))
        connection.execute(
            text("UPDATE notices SET publish_date = created_at WHERE publish_date IS NULL")
        )


def migrate_notices_is_active(engine: Engine) -> None:
    inspector = inspect(engine)
    if "notices" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notices")}
    if "is_active" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE notices ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if "published" in columns:
            connection.execute(text("UPDATE notices SET is_active = published"))


def migrate_hostel_application_allocation_fields(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_applications" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("hostel_applications")}

    with engine.begin() as connection:
        if "allocated_room_id" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN allocated_room_id INTEGER"))
            columns.add("allocated_room_id")
        if "bed_number" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN bed_number VARCHAR(20)"))
            columns.add("bed_number")
        if "room_type" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN room_type VARCHAR(50)"))
            columns.add("room_type")
        if "food_preference" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN food_preference VARCHAR(50)"))
            columns.add("food_preference")
        if "aadhaar_card_path" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN aadhaar_card_path VARCHAR(255)"))
            columns.add("aadhaar_card_path")
        if "college_id_path" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN college_id_path VARCHAR(255)"))
            columns.add("college_id_path")
        if "marksheet_path" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN marksheet_path VARCHAR(255)"))
            columns.add("marksheet_path")


def migrate_hostel_application_allotted_category(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_applications" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("hostel_applications")}
    if "allotted_category" in columns:
        return

    with engine.begin() as connection:
        logger.info("Adding missing 'allotted_category' column to hostel_applications table.")
        connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN allotted_category VARCHAR(20)"))


def migrate_hostel_application_cycle_fields(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_applications" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("hostel_applications")}
    with engine.begin() as connection:
        if "application_type" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN application_type VARCHAR(20) DEFAULT 'new'"))
            connection.execute(text("UPDATE hostel_applications SET application_type = 'new' WHERE application_type IS NULL"))
            columns.add("application_type")
        if "active_cycle_reference" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN active_cycle_reference VARCHAR(50)"))
            columns.add("active_cycle_reference")
        if "renewal_reference_number" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN renewal_reference_number VARCHAR(50)"))
            columns.add("renewal_reference_number")
        if "previous_application_number" not in columns:
            connection.execute(text("ALTER TABLE hostel_applications ADD COLUMN previous_application_number VARCHAR(20)"))
            columns.add("previous_application_number")

    for table_name in ("hostel_application_payments", "hostel_hostel_payments"):
        if table_name not in inspector.get_table_names():
            continue
        payment_columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "cycle_reference" in payment_columns:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN cycle_reference VARCHAR(50)"))


def migrate_hostel_complaints_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_complaints" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("hostel_complaints")}
        if "assigned_staff" in columns:
            return
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE hostel_complaints ADD COLUMN assigned_staff VARCHAR(150)"))
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE hostel_complaints (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL,
                    application_id INTEGER NULL,
                    ticket_number VARCHAR(30) NOT NULL UNIQUE,
                    subject VARCHAR(150) NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    description TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'open',
                    assigned_staff VARCHAR(150) NULL,
                    resolution_note TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL,
                    FOREIGN KEY(student_id) REFERENCES hostel_students(id),
                    FOREIGN KEY(application_id) REFERENCES hostel_applications(id)
                )
                """
            )
        )


def migrate_hostel_students_old_fields(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_students" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("hostel_students")}

    with engine.begin() as connection:
        if "hostel_id" not in columns:
            logger.info("Adding missing 'hostel_id' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN hostel_id VARCHAR(20)"))
            columns.add("hostel_id")
        if "is_old_student" not in columns:
            logger.info("Adding missing 'is_old_student' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN is_old_student BOOLEAN NOT NULL DEFAULT 0"))
            columns.add("is_old_student")
        if "old_student_status" not in columns:
            logger.info("Adding missing 'old_student_status' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN old_student_status VARCHAR(20)"))
            columns.add("old_student_status")
        if "hostel_name" not in columns:
            logger.info("Adding missing 'hostel_name' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN hostel_name VARCHAR(50)"))
            columns.add("hostel_name")
        if "block_name" not in columns:
            logger.info("Adding missing 'block_name' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN block_name VARCHAR(20)"))
            columns.add("block_name")
        if "room_number" not in columns:
            logger.info("Adding missing 'room_number' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN room_number VARCHAR(20)"))
            columns.add("room_number")
        if "bed_number" not in columns:
            logger.info("Adding missing 'bed_number' column to hostel_students table.")
            connection.execute(text("ALTER TABLE hostel_students ADD COLUMN bed_number VARCHAR(20)"))
            columns.add("bed_number")

        try:
            connection.execute(text("UPDATE hostel_students SET is_old_student = 0 WHERE is_old_student IS NULL"))
        except Exception:
            logger.warning("Unable to backfill hostel_students.is_old_student", exc_info=True)
        try:
            connection.execute(text("UPDATE hostel_students SET hostel_id = application_number WHERE hostel_id IS NULL"))
        except Exception:
            logger.warning("Unable to backfill hostel_students.hostel_id", exc_info=True)


def migrate_hostel_room_fields(engine: Engine) -> None:
    inspector = inspect(engine)
    if "hostel_rooms" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("hostel_rooms")}

    with engine.begin() as connection:
        if "occupied_beds" not in columns:
            logger.info("Adding missing 'occupied_beds' column to hostel_rooms table.")
            connection.execute(text("ALTER TABLE hostel_rooms ADD COLUMN occupied_beds INTEGER NOT NULL DEFAULT 0"))
            columns.add("occupied_beds")
        if "is_active" not in columns:
            logger.info("Adding missing 'is_active' column to hostel_rooms table.")
            connection.execute(text("ALTER TABLE hostel_rooms ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
            columns.add("is_active")
        if "notes" not in columns:
            logger.info("Adding missing 'notes' column to hostel_rooms table.")
            connection.execute(text("ALTER TABLE hostel_rooms ADD COLUMN notes TEXT"))
            columns.add("notes")


DEFAULT_HOSTEL_ROOMS = [
    ("Vaidehi Hostel", "A", "101", 3),
    ("Vaidehi Hostel", "A", "102", 3),
    ("Vaidehi Hostel", "A", "103", 3),
    ("Vaidehi Hostel", "B", "201", 3),
    ("Vaidehi Hostel", "B", "202", 3),
    ("Vaidehi Hostel", "B", "203", 3),
    ("Mahima Hostel", "A", "101", 2),
    ("Mahima Hostel", "A", "102", 2),
    ("Mahima Hostel", "A", "103", 2),
    ("Mahima Hostel", "B", "201", 2),
    ("Mahima Hostel", "B", "202", 2),
    ("Mahima Hostel", "B", "203", 2),
]


def seed_default_hostel_rooms(session: Session) -> None:
    existing_rooms = session.execute(select(ERPHostelRoom)).scalars().all()
    if existing_rooms:
        return

    for hostel_name, block_name, room_number, bed_capacity in DEFAULT_HOSTEL_ROOMS:
        session.add(
            ERPHostelRoom(
                hostel_name=hostel_name,
                block_name=block_name,
                room_number=room_number,
                bed_capacity=bed_capacity,
                is_active=True,
            )
        )

    session.commit()


def is_valid_bcrypt_hash(password_hash: str) -> bool:
    """Check if the password hash is a valid bcrypt hash."""
    if not password_hash:
        return False
    return password_hash.startswith(("$2a$", "$2b$", "$2y$")) and len(password_hash) == 60


def migrate_plaintext_passwords(engine: Engine, session_factory) -> dict:
    """Migrate any plain text passwords in admin_users table to bcrypt.
    
    This function:
    1. Finds any admin users with non-bcrypt passwords
    2. Automatically migrates the default admin if needed
    
    Returns a dict with migration status info.
    """
    result = {
        "checked": 0,
        "needs_migration": [],
        "migrated": 0,
        "errors": []
    }
    
    inspector = inspect(engine)
    if "admin_users" not in inspector.get_table_names():
        logger.warning("admin_users table not found - skipping password migration")
        return result
    
    session = session_factory()
    try:
        admins = session.execute(select(AdminUser)).scalars().all()
        result["checked"] = len(admins)
        
        for admin in admins:
            password_hash = admin.password_hash
            
            # Skip if already valid bcrypt
            if is_valid_bcrypt_hash(password_hash):
                # Verify it can be used with current bcrypt version
                try:
                    pwd_context.verify("test", password_hash)
                except Exception as e:
                    logger.warning(f"Rehashing admin '{admin.username}' due to bcrypt version mismatch")
                    # Force rehash with current bcrypt
                    new_hash = pwd_context.hash(settings.admin_password)
                    admin.password_hash = new_hash
                    session.commit()
                    result["migrated"] += 1
                    logger.info(f"Successfully rehashed password for admin '{admin.username}'")
                continue
            
            # Check if it's a plain text password (no $ prefix, short length)
            if len(password_hash) < 60 and not password_hash.startswith("$"):
                logger.warning(
                    f"Plain text password detected for admin '{admin.username}'. "
                    f"Auto-migrating to bcrypt..."
                )
                
                # Auto-migrate to bcrypt using the default password from config
                new_hash = pwd_context.hash(settings.admin_password)
                admin.password_hash = new_hash
                session.commit()
                
                result["needs_migration"].append({
                    "username": admin.username,
                    "action": "auto_migrated"
                })
                result["migrated"] += 1
                logger.info(f"Successfully auto-migrated password for admin '{admin.username}'")
            else:
                # Invalid hash format (e.g., malformed bcrypt)
                logger.error(
                    f"Invalid password hash format for admin '{admin.username}'. "
                    f"Hash starts with: '{password_hash[:10] if password_hash else 'empty'}'"
                )
                result["errors"].append({
                    "username": admin.username,
                    "issue": "Invalid hash format - auto-fixing with default password"
                })
                
                # Auto-fix with default password
                new_hash = pwd_context.hash(settings.admin_password)
                admin.password_hash = new_hash
                session.commit()
                result["migrated"] += 1
                logger.info(f"Fixed invalid hash for admin '{admin.username}'")
        
        return result
        
    except Exception as e:
        logger.error(f"Error during password migration check: {type(e).__name__}: {e}")
        result["errors"].append({"issue": str(e)})
        return result
    finally:
        session.close()


def force_migrate_plaintext_password(engine, session_factory, username: str, plain_password: str) -> bool:
    """Force migrate a specific admin user's plain text password to bcrypt.
    
    WARNING: Only use this if you know the plain text password!
    
    Args:
        engine: SQLAlchemy engine
        session_factory: Session factory
        username: Admin username to migrate
        plain_password: The plain text password (will be hashed)
    
    Returns:
        True if migration successful, False otherwise
    """
    session = session_factory()
    try:
        admin = session.execute(
            select(AdminUser).where(AdminUser.username == username)
        ).scalar_one_or_none()
        
        if not admin:
            logger.error(f"Admin user '{username}' not found")
            return False
        
        # Hash the plain password
        new_hash = pwd_context.hash(plain_password)
        admin.password_hash = new_hash
        session.commit()
        
        logger.info(f"Successfully migrated password for admin '{username}'")
        return True
        
    except Exception as e:
        logger.error(f"Error force migrating password for '{username}': {type(e).__name__}: {e}")
        session.rollback()
        return False
    finally:
        session.close()
