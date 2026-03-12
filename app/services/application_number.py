from datetime import datetime


def generate_application_number(student_id: int, current_time: datetime | None = None) -> str:
    now = current_time or datetime.utcnow()
    year = now.year
    return f"{year}{student_id:06d}"
