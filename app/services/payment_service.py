from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..erp_models import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPStudent
from .email_service import send_receipt_email
from .erp_service import PAYMENT_STATUS_FAILED, PAYMENT_STATUS_SUCCESS
from .receipt_service import generate_application_fee_receipt, generate_hostel_receipt


def transaction_exists(db: Session, transaction_id: str) -> bool:
    return bool(
        db.scalar(select(ERPApplicationPayment.id).where(ERPApplicationPayment.transaction_id == transaction_id))
        or db.scalar(select(ERPHostelPayment.id).where(ERPHostelPayment.transaction_id == transaction_id))
    )


def approve_application_payment(
    *,
    student: ERPStudent,
    application: ERPApplication,
    payment: ERPApplicationPayment,
) -> str:
    receipt_path = generate_application_fee_receipt(
        payload={
            "application_number": student.application_number,
            "application_type": application.application_type,
            "cycle_reference": application.active_cycle_reference,
            "renewal_reference_number": application.renewal_reference_number,
            "student_name": application.name,
            "course_name": application.course_name,
            "session": application.session,
            "transaction_id": payment.transaction_id,
            "payment_date": payment.payment_date.strftime("%d %b %Y %I:%M %p"),
            "amount": f"INR {settings.APP_PAYMENT_AMOUNT}",
        }
    )
    email_status = send_receipt_email(
        recipient=student.email,
        student_name=application.name or "Student",
        subject="MMC Hostel ERP Application Fee Receipt",
        body=(
            f"Your {'renewal' if application.application_type == 'renewal' else 'application'} fee payment of INR {settings.APP_PAYMENT_AMOUNT} has been approved. "
            f"Transaction ID: {payment.transaction_id}."
        ),
        receipt_path=_receipt_absolute_path(receipt_path),
    )
    payment.status = PAYMENT_STATUS_SUCCESS
    payment.receipt_path = receipt_path
    payment.email_sent = email_status == "sent"
    return email_status


def approve_hostel_payment(
    *,
    student: ERPStudent,
    application: ERPApplication,
    payment: ERPHostelPayment,
) -> str:
    receipt_path = generate_hostel_receipt(
        payload={
            "application_number": student.application_number,
            "application_type": application.application_type,
            "cycle_reference": application.active_cycle_reference,
            "renewal_reference_number": application.renewal_reference_number,
            "student_name": application.name,
            "gender": application.gender,
            "date_of_birth": application.date_of_birth,
            "mobile_number": student.mobile_number,
            "email": student.email,
            "blood_group": application.blood_group,
            "aadhaar_number": application.aadhaar_number,
            "category": application.category,
            "religion": application.religion,
            "nationality": application.nationality,
            "father_name": application.father_name,
            "mother_name": application.mother_name,
            "local_guardian_name": application.local_guardian_name,
            "guardian_mobile_number": application.guardian_mobile_number,
            "correspondence_address": application.correspondence_address,
            "admission_application_id": application.admission_application_id,
            "college_name": application.college_name,
            "course_name": application.course_name,
            "honours_subject": application.honours_subject,
            "session": application.session,
            "program": application.program,
            "roll_number": application.roll_number,
            "hostel_name": application.allocated_hostel,
            "amount": f"INR {payment.amount}",
            "transaction_id": payment.transaction_id,
            "payment_date": payment.payment_date.strftime("%d %b %Y %I:%M %p"),
        }
    )
    email_status = send_receipt_email(
        recipient=student.email,
        student_name=application.name or "Student",
        subject="MMC Hostel ERP Final Hostel Receipt",
        body=(
            f"Your hostel {'renewal ' if application.application_type == 'renewal' else ''}payment of INR {payment.amount} for {application.allocated_hostel} has been approved. "
            f"Transaction ID: {payment.transaction_id}."
        ),
        receipt_path=_receipt_absolute_path(receipt_path),
    )
    payment.status = PAYMENT_STATUS_SUCCESS
    payment.receipt_path = receipt_path
    payment.email_sent = email_status == "sent"
    return email_status


def reject_payment(payment: ERPApplicationPayment | ERPHostelPayment) -> None:
    payment.status = PAYMENT_STATUS_FAILED
    payment.receipt_path = None
    payment.email_sent = False


def _receipt_absolute_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    from pathlib import Path

    return str((Path(__file__).resolve().parents[2] / relative_path).resolve())
