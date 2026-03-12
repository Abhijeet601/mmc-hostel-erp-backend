from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_number: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    date_of_birth: Mapped[Date] = mapped_column(Date, nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    application = relationship("Application", back_populates="student", uselist=False, cascade="all, delete-orphan")
    application_payments = relationship("Payment", back_populates="student", cascade="all, delete-orphan")
    hostel_payments = relationship("HostelPayment", back_populates="student", cascade="all, delete-orphan")
    shortlist_record = relationship(
        "ShortlistedStudent",
        back_populates="student",
        uselist=False,
        cascade="all, delete-orphan",
    )
