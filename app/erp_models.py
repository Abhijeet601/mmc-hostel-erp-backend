from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ERPStudent(Base):
    __tablename__ = "hostel_students"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    hostel_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Old student fields
    is_old_student: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    old_student_status: Mapped[str | None] = mapped_column(String(20), index=True)
    hostel_name: Mapped[str | None] = mapped_column(String(50), index=True)
    block_name: Mapped[str | None] = mapped_column(String(20), index=True)
    room_number: Mapped[str | None] = mapped_column(String(20), index=True)
    bed_number: Mapped[str | None] = mapped_column(String(20), index=True)

    application: Mapped["ERPApplication | None"] = relationship(
        "ERPApplication",
        back_populates="student",
        uselist=False,
        cascade="all, delete-orphan",
    )
    application_payments: Mapped[list["ERPApplicationPayment"]] = relationship(
        "ERPApplicationPayment",
        back_populates="student",
        cascade="all, delete-orphan",
        order_by="ERPApplicationPayment.payment_date.desc()",
    )
    hostel_payments: Mapped[list["ERPHostelPayment"]] = relationship(
        "ERPHostelPayment",
        back_populates="student",
        cascade="all, delete-orphan",
        order_by="ERPHostelPayment.payment_date.desc()",
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # student, room
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # create, update, delete, allocate
    old_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ERPHostelRoom(Base):

    __tablename__ = "hostel_rooms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    hostel_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    block_name: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    room_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    bed_capacity: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    occupied_beds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    applications: Mapped[list["ERPApplication"]] = relationship(
        "ERPApplication",
        back_populates="allocated_room",
    )


class ERPApplication(Base):
    __tablename__ = "hostel_applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("hostel_students.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    form_status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    application_type: Mapped[str] = mapped_column(String(20), default="new", nullable=False, index=True)
    active_cycle_reference: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    renewal_reference_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    previous_application_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_shortlisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mobile_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    student_photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    aadhaar_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    allotted_category: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    religion: Mapped[str | None] = mapped_column(String(30), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(50), nullable=True)

    father_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    mother_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    local_guardian_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    guardian_mobile_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    correspondence_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    intermediate_college_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intermediate_board: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_marks: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    marks_obtained: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aggregate_percentage: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    admission_application_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    college_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    course_name: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    honours_subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    program: Mapped[str | None] = mapped_column(String(20), nullable=True)
    roll_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    preferred_hostel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    allocated_hostel: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    allocated_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("hostel_rooms.id"),
        nullable=True,
        index=True,
    )
    bed_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shortlisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hostel_allocated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    student: Mapped[ERPStudent] = relationship("ERPStudent", back_populates="application")
    allocated_room: Mapped["ERPHostelRoom | None"] = relationship("ERPHostelRoom", back_populates="applications")
    application_payments: Mapped[list["ERPApplicationPayment"]] = relationship(
        "ERPApplicationPayment",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ERPApplicationPayment.payment_date.desc()",
    )
    hostel_payments: Mapped[list["ERPHostelPayment"]] = relationship(
        "ERPHostelPayment",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ERPHostelPayment.payment_date.desc()",
    )


class ERPApplicationPayment(Base):
    __tablename__ = "hostel_application_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("hostel_students.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("hostel_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_reference: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    receipt_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    student: Mapped[ERPStudent] = relationship("ERPStudent", back_populates="application_payments")
    application: Mapped[ERPApplication] = relationship("ERPApplication", back_populates="application_payments")


class ERPHostelPayment(Base):
    __tablename__ = "hostel_hostel_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("hostel_students.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("hostel_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_reference: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    hostel_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    transaction_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    receipt_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    student: Mapped[ERPStudent] = relationship("ERPStudent", back_populates="hostel_payments")
    application: Mapped[ERPApplication] = relationship("ERPApplication", back_populates="hostel_payments")


class ERPComplaint(Base):
    __tablename__ = "hostel_complaints"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("hostel_students.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("hostel_applications.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
