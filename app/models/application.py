from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.enums import ApplicationStatusEnum


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("student_id", name="uq_application_student"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), nullable=False)

    admission_application_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    student_image_path: Mapped[str] = mapped_column(String(255), nullable=False)

    date_of_birth: Mapped[Date] = mapped_column(Date, nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    blood_group: Mapped[str] = mapped_column(String(10), nullable=False)
    aadhar_number: Mapped[str] = mapped_column(String(20), nullable=False)

    category: Mapped[str] = mapped_column(String(20), nullable=False)
    religion: Mapped[str] = mapped_column(String(20), nullable=False)
    nationality: Mapped[str] = mapped_column(String(50), nullable=False)

    father_name: Mapped[str] = mapped_column(String(150), nullable=False)
    mother_name: Mapped[str] = mapped_column(String(150), nullable=False)
    local_guardian_name: Mapped[str] = mapped_column(String(150), nullable=False)
    local_guardian_mobile: Mapped[str] = mapped_column(String(20), nullable=False)

    correspondence_address: Mapped[str] = mapped_column(Text, nullable=False)

    intermediate_college_name: Mapped[str] = mapped_column(String(255), nullable=False)
    intermediate_board_name: Mapped[str] = mapped_column(String(255), nullable=False)
    intermediate_total_marks: Mapped[float] = mapped_column(Float, nullable=False)
    intermediate_marks_obtained: Mapped[float] = mapped_column(Float, nullable=False)
    intermediate_result_type: Mapped[str] = mapped_column(String(50), nullable=False)
    intermediate_percentage: Mapped[float] = mapped_column(Float, nullable=False)

    college_name: Mapped[str] = mapped_column(String(255), nullable=False)
    course_name: Mapped[str] = mapped_column(String(50), nullable=False)
    roll_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    session: Mapped[str] = mapped_column(String(20), nullable=False)
    program: Mapped[str] = mapped_column(String(20), nullable=False)
    pg_course: Mapped[str | None] = mapped_column(String(80), nullable=True)
    honours_subject: Mapped[str] = mapped_column(String(120), nullable=False)

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ApplicationStatusEnum.APP_PAYMENT_PENDING.value,
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    student = relationship("Student", back_populates="application")
    payments = relationship("Payment", back_populates="application")
