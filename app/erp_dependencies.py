from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .erp_models import ERPStudent
from .erp_security import decode_token

student_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


def get_current_student(
    token: str = Depends(student_oauth2_scheme),
    db: Session = Depends(get_db),
) -> ERPStudent:
    payload = decode_token(token)
    if not payload or payload.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired student token.",
        )

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid student token.",
        )

    student = db.get(ERPStudent, int(subject))
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")

    return student
