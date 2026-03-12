from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from ..config import settings
from ..erp_models import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPStudent

VALID_HOSTELS = {"Vaidehi Hostel", "Mahima Hostel"}

APPLICATION_FIELDS = [
    "name",
    "email",
    "mobile_number",
    "date_of_birth",
    "gender",
    "blood_group",
    "aadhaar_number",
    "category",
    "religion",
    "nationality",
    "father_name",
    "mother_name",
    "local_guardian_name",
    "guardian_mobile_number",
    "correspondence_address",
    "intermediate_college_name",
    "intermediate_board",
    "total_marks",
    "marks_obtained",
    "result_type",
    "aggregate_percentage",
    "admission_application_id",
    "college_name",
    "course_name",
    "honours_subject",
    "session",
    "program",
    "roll_number",
    "preferred_hostel",
]

REQUIRED_SUBMISSION_FIELDS = [
    "name",
    "email",
    "mobile_number",
    "date_of_birth",
    "gender",
    "blood_group",
    "aadhaar_number",
    "category",
    "religion",
    "nationality",
    "father_name",
    "mother_name",
    "local_guardian_name",
    "guardian_mobile_number",
    "correspondence_address",
    "intermediate_college_name",
    "intermediate_board",
    "total_marks",
    "marks_obtained",
    "result_type",
    "aggregate_percentage",
    "admission_application_id",
    "college_name",
    "course_name",
    "honours_subject",
    "session",
    "program",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_optional_date(value: object | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value).strip())


def parse_optional_decimal(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value).strip())


def decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def calculate_percentage(total_marks: Decimal | None, marks_obtained: Decimal | None) -> Decimal | None:
    if total_marks in (None, Decimal("0")) or marks_obtained is None:
        return None
    return (marks_obtained / total_marks * Decimal("100")).quantize(Decimal("0.01"))


def ensure_valid_hostel_name(hostel_name: str) -> str:
    normalized = clean_text(hostel_name)
    if normalized not in VALID_HOSTELS:
        raise ValueError("Invalid hostel name.")
    return normalized


def latest_application_payment(application: ERPApplication | None) -> ERPApplicationPayment | None:
    if not application or not application.application_payments:
        return None
    return application.application_payments[0]


def latest_hostel_payment(application: ERPApplication | None) -> ERPHostelPayment | None:
    if not application or not application.hostel_payments:
        return None
    return application.hostel_payments[0]


def verification_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return "pending"
    return "verified" if application.is_verified else "pending"


def application_payment_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return "pending"
    payment = latest_application_payment(application)
    return "paid" if payment and payment.status == "success" else "pending"


def shortlist_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return "pending"
    return "shortlisted" if application.is_shortlisted else "pending"


def hostel_status(application: ERPApplication | None) -> str:
    if not application or not application.is_shortlisted:
        return "not_available"
    payment = latest_hostel_payment(application)
    if payment and payment.status == "success":
        return "paid"
    if application.allocated_hostel:
        return "payment_pending"
    if application.preferred_hostel:
        return "awaiting_allocation"
    return "preference_pending"


def current_application_status(application: ERPApplication | None) -> str:
    if not application:
        return "Not Started"
    if application.form_status == "draft":
        return "Draft Saved"
    if latest_hostel_payment(application):
        return "Hostel Fee Paid"
    if application.allocated_hostel:
        return "Hostel Allocated"
    if application.is_shortlisted:
        return "Shortlisted"
    if application.is_verified:
        return "Verified"
    return "Submitted"


def can_edit_application(application: ERPApplication | None) -> bool:
    return application is None or not application.is_verified


def can_choose_hostel(application: ERPApplication | None) -> bool:
    return bool(application and application.is_shortlisted and not latest_hostel_payment(application))


def can_pay_hostel_fee(application: ERPApplication | None) -> bool:
    return bool(application and application.allocated_hostel and not latest_hostel_payment(application))


def build_asset_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return f"/{relative_path.lstrip('/')}"


def tracker_steps(student: ERPStudent, application: ERPApplication | None) -> list[dict[str, object | None]]:
    hostel_payment = latest_hostel_payment(application)
    return [
        {
            "key": "registration_completed",
            "label": "Registration Completed",
            "state": "completed",
            "date": student.created_at,
            "description": "Account created and application number issued.",
        },
        {
            "key": "application_submitted",
            "label": "Application Submitted",
            "state": "completed" if application and application.form_status == "submitted" else "pending",
            "date": application.submitted_at if application else None,
            "description": "Application form saved and submitted for review.",
        },
        {
            "key": "application_verified",
            "label": "Application Verified",
            "state": "completed" if application and application.is_verified else "pending",
            "date": application.verified_at if application else None,
            "description": "Admin verification pending until documents are checked.",
        },
        {
            "key": "shortlisted",
            "label": "Shortlisted",
            "state": "completed" if application and application.is_shortlisted else "pending",
            "date": application.shortlisted_at if application else None,
            "description": "Shortlist is uploaded by admin after verification.",
        },
        {
            "key": "hostel_allocated",
            "label": "Hostel Allocated",
            "state": "completed" if application and application.allocated_hostel else "pending",
            "date": application.hostel_allocated_at if application else None,
            "description": "Admin assigns Vaidehi Hostel or Mahima Hostel.",
        },
        {
            "key": "hostel_payment",
            "label": "Hostel Payment",
            "state": "completed" if hostel_payment else "pending",
            "date": hostel_payment.payment_date if hostel_payment else None,
            "description": "Final hostel fee payment and receipt generation.",
        },
    ]


def application_summary(student: ERPStudent, application: ERPApplication | None) -> dict[str, object | None]:
    app_payment = latest_application_payment(application)
    hostel_payment = latest_hostel_payment(application)
    return {
        "name": application.name if application else None,
        "email": application.email if application and application.email else student.email,
        "mobile_number": application.mobile_number if application and application.mobile_number else student.mobile_number,
        "date_of_birth": application.date_of_birth if application and application.date_of_birth else student.date_of_birth,
        "gender": application.gender if application else None,
        "blood_group": application.blood_group if application else None,
        "aadhaar_number": application.aadhaar_number if application else None,
        "category": application.category if application else None,
        "religion": application.religion if application else None,
        "nationality": application.nationality if application else None,
        "father_name": application.father_name if application else None,
        "mother_name": application.mother_name if application else None,
        "local_guardian_name": application.local_guardian_name if application else None,
        "guardian_mobile_number": application.guardian_mobile_number if application else None,
        "correspondence_address": application.correspondence_address if application else None,
        "intermediate_college_name": application.intermediate_college_name if application else None,
        "intermediate_board": application.intermediate_board if application else None,
        "total_marks": decimal_to_float(application.total_marks) if application else None,
        "marks_obtained": decimal_to_float(application.marks_obtained) if application else None,
        "result_type": application.result_type if application else None,
        "aggregate_percentage": decimal_to_float(application.aggregate_percentage) if application else None,
        "admission_application_id": application.admission_application_id if application else None,
        "college_name": application.college_name if application else "Magadh Mahila College",
        "course_name": application.course_name if application else None,
        "honours_subject": application.honours_subject if application else None,
        "session": application.session if application else None,
        "program": application.program if application else None,
        "roll_number": application.roll_number if application else None,
        "preferred_hostel": application.preferred_hostel if application else None,
        "allocated_hostel": application.allocated_hostel if application else None,
        "student_photo_url": build_asset_url(application.student_photo_path) if application else None,
        "application_payment_transaction_id": app_payment.transaction_id if app_payment else None,
        "hostel_payment_transaction_id": hostel_payment.transaction_id if hostel_payment else None,
    }


def build_receipt_summary(payment_type: str, amount: float, payment) -> dict[str, object | None] | None:
    if not payment:
        return None
    return {
        "payment_type": payment_type,
        "amount": amount,
        "transaction_id": payment.transaction_id,
        "payment_date": payment.payment_date,
        "receipt_url": build_asset_url(payment.receipt_path),
    }


def build_student_dashboard(student: ERPStudent) -> dict[str, object | None]:
    application = student.application
    app_payment = latest_application_payment(application)
    hostel_payment = latest_hostel_payment(application)
    allocated_hostel = application.allocated_hostel if application else None
    hostel_fee_amount = None
    if allocated_hostel:
        hostel_fee_amount = settings.hostel_fee(allocated_hostel)

    return {
        "application_number": student.application_number,
        "student_name": application.name if application else None,
        "email": student.email,
        "mobile_number": student.mobile_number,
        "application_status": current_application_status(application),
        "form_status": application.form_status if application else "not_started",
        "verification_status": verification_status(application),
        "application_payment_status": application_payment_status(application),
        "shortlist_status": shortlist_status(application),
        "hostel_status": hostel_status(application),
        "shortlisted": bool(application and application.is_shortlisted),
        "can_edit_application": can_edit_application(application),
        "can_pay_application_fee": bool(application and application.form_status == "submitted" and not app_payment),
        "can_choose_hostel": can_choose_hostel(application),
        "can_pay_hostel_fee": can_pay_hostel_fee(application),
        "preferred_hostel": application.preferred_hostel if application else None,
        "allocated_hostel": allocated_hostel,
        "application_fee_amount": settings.APP_PAYMENT_AMOUNT,
        "hostel_fee_amount": hostel_fee_amount,
        "photo_url": build_asset_url(application.student_photo_path) if application else None,
        "application_receipt": build_receipt_summary(
            "application_fee",
            float(settings.APP_PAYMENT_AMOUNT),
            app_payment,
        ),
        "hostel_receipt": build_receipt_summary(
            "hostel_fee",
            float(hostel_payment.amount) if hostel_payment else 0.0,
            hostel_payment,
        ),
        "tracker": tracker_steps(student, application),
        "summary": application_summary(student, application),
    }


def build_admin_student_summary(student: ERPStudent) -> dict[str, object | None]:
    application = student.application
    hostel_payment = latest_hostel_payment(application)
    return {
        "id": student.id,
        "application_number": student.application_number,
        "name": application.name if application else None,
        "email": student.email,
        "mobile_number": student.mobile_number,
        "course_name": application.course_name if application else None,
        "category": application.category if application else None,
        "session": application.session if application else None,
        "program": application.program if application else None,
        "form_status": application.form_status if application else "not_started",
        "verification_status": verification_status(application),
        "application_payment_status": application_payment_status(application),
        "shortlist_status": shortlist_status(application),
        "hostel_status": hostel_status(application),
        "preferred_hostel": application.preferred_hostel if application else None,
        "allocated_hostel": application.allocated_hostel if application else None,
        "application_submitted_at": application.submitted_at if application else None,
        "verified_at": application.verified_at if application else None,
        "shortlisted_at": application.shortlisted_at if application else None,
        "hostel_payment_date": hostel_payment.payment_date if hostel_payment else None,
    }


def build_admin_student_detail(student: ERPStudent) -> dict[str, object | None]:
    application = student.application
    dashboard = build_student_dashboard(student)
    dashboard.update(
        {
            "id": student.id,
            "registration_date_of_birth": student.date_of_birth,
            "registered_at": student.created_at,
            "application_submitted_at": application.submitted_at if application else None,
            "verified_at": application.verified_at if application else None,
            "shortlisted_at": application.shortlisted_at if application else None,
            "hostel_allocated_at": application.hostel_allocated_at if application else None,
        }
    )
    return dashboard
