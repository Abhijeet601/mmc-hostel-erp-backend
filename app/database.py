import os
import re

from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url

from .config import settings

REFERENCE_PATTERN = re.compile(r"\$\{\{([^}]+)\}\}|\$\{([^}]+)\}|\{\{([^}]+)\}\}")


def _is_unresolved_env_reference(value: str) -> bool:
    return bool(REFERENCE_PATTERN.search(value))


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = _strip_wrapping_quotes(value.strip())
    expanded = _expand_env_references(cleaned)
    return _strip_wrapping_quotes(expanded.strip())


def _lookup_placeholder_value(token: str) -> str:
    normalized = token.strip()
    candidates = [
        normalized,
        normalized.upper(),
        normalized.replace(".", "_"),
        normalized.replace(".", "_").upper(),
    ]

    if "." in normalized:
        tail = normalized.split(".")[-1]
        candidates.extend([tail, tail.upper(), tail.replace(".", "_"), tail.replace(".", "_").upper()])
    else:
        tail = normalized

    if tail.endswith("_URL"):
        candidates.extend(
            [
                tail.replace("_URL", "_PUBLIC_URL"),
                tail.replace("_URL", "_PRIVATE_URL"),
                tail.replace("_URL", "_PUBLIC_URL").upper(),
                tail.replace("_URL", "_PRIVATE_URL").upper(),
            ]
        )

    seen: set[str] = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        env_val = os.getenv(key)
        if env_val is None:
            continue
        cleaned = _strip_wrapping_quotes(env_val.strip())
        if cleaned:
            return cleaned

    return ""


def _expand_env_references(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = next((group for group in match.groups() if group), "")
        replacement = _lookup_placeholder_value(token)
        return replacement if replacement else match.group(0)

    return REFERENCE_PATTERN.sub(replacer, value)


def _first_env_value(*keys: str) -> str:
    for key in keys:
        value = _clean_env_value(os.getenv(key))
        if value:
            return value
    return ""


def _is_usable_env_value(value: str) -> bool:
    return bool(value) and not _is_unresolved_env_reference(value)


def _is_parseable_database_url(url: str) -> bool:
    try:
        make_url(normalize_database_url(url))
        return True
    except ArgumentError:
        return False


def _build_mysql_url_from_parts() -> str | None:
    host = _first_env_value("MYSQLHOST", "MYSQL_HOST")
    port = _first_env_value("MYSQLPORT", "MYSQL_PORT")
    user = _first_env_value("MYSQLUSER", "MYSQL_USER")
    password = _first_env_value("MYSQLPASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD")
    database = _first_env_value("MYSQLDATABASE", "MYSQL_DATABASE")

    required_parts = [host, port, user, password, database]
    if not all(_is_usable_env_value(part) for part in required_parts):
        return None

    try:
        port_number = int(port)
    except ValueError:
        return None

    mysql_url = URL.create(
        drivername="mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=port_number,
        database=database,
    )
    return mysql_url.render_as_string(hide_password=False)


def _is_running_on_railway() -> bool:
    railway_markers = ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
    return any(os.getenv(marker) for marker in railway_markers)


def _present_mysql_env_keys() -> list[str]:
    keys = [
        "DATABASE_URL",
        "MYSQL_URL",
        "MYSQL_PUBLIC_URL",
        "MYSQLHOST",
        "MYSQL_HOST",
        "MYSQLPORT",
        "MYSQL_PORT",
        "MYSQLUSER",
        "MYSQL_USER",
        "MYSQLPASSWORD",
        "MYSQL_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
        "MYSQLDATABASE",
        "MYSQL_DATABASE",
    ]
    return [key for key in keys if _clean_env_value(os.getenv(key))]


def _resolve_raw_database_url() -> str:
    running_on_railway = _is_running_on_railway()

    candidates = [
        _clean_env_value(os.getenv("DATABASE_URL")),
        _clean_env_value(os.getenv("MYSQL_URL")),
        _clean_env_value(os.getenv("MYSQL_PUBLIC_URL")),
    ]

    for candidate in candidates:
        normalized_candidate = normalize_database_url(candidate)
        if running_on_railway and normalized_candidate.startswith("sqlite"):
            continue
        if _is_usable_env_value(candidate) and _is_parseable_database_url(candidate):
            return candidate

    mysql_from_parts = _build_mysql_url_from_parts()
    if mysql_from_parts is not None:
        return mysql_from_parts

    if running_on_railway:
        present_keys = ", ".join(_present_mysql_env_keys()) or "none"
        raise RuntimeError(
            "No valid MySQL connection settings found on Railway. "
            "Set MYSQL_URL or DATABASE_URL (mysql:// or mysql+pymysql://), "
            "or provide MYSQLHOST, MYSQLPORT, MYSQLUSER, MYSQLPASSWORD, MYSQLDATABASE. "
            f"Detected env keys: {present_keys}."
        )

    return _clean_env_value(settings.database_url)


def normalize_database_url(url: str) -> str:
    """Convert Railway-style MySQL URLs into SQLAlchemy PyMySQL URLs."""
    normalized = _strip_wrapping_quotes(url.strip())

    if normalized.startswith("mysql2://"):
        normalized = normalized.replace("mysql2://", "mysql+pymysql://", 1)

    if normalized.startswith("mysql://"):
        normalized = normalized.replace("mysql://", "mysql+pymysql://", 1)

    return normalized


def validate_database_url(url: str) -> str:
    try:
        make_url(url)
    except ArgumentError as exc:
        raise RuntimeError(
            "Invalid database URL. Configure Railway with MYSQL_URL, or set "
            "DATABASE_URL to a valid SQLAlchemy URL (for MySQL use mysql:// or mysql+pymysql://). "
            "Alternatively set MYSQLHOST, MYSQLPORT, MYSQLUSER, MYSQLPASSWORD, MYSQLDATABASE."
        ) from exc

    return url


database_url = validate_database_url(normalize_database_url(_resolve_raw_database_url()))

connect_args: dict[str, bool] = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
