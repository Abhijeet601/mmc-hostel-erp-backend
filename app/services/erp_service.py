from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..erp_models import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPHostelRoom, ERPStudent

VALID_HOSTELS = {"Vaidehi Hostel", "Mahima Hostel"}
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_SUCCESS = "success"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_MODE_DEMO = "demo"

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
    "room_type",
    "food_preference",
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
    "preferred_hostel",
    "room_type",
    "food_preference",
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


def normalize_bed_number(value: object | None) -> str | None:
    normalized = clean_text(value)
    if not normalized:
        return None
    return normalized.upper().replace("BED ", "B")


def payment_reference(payment_type: str, payment_id: int) -> str:
    return f"{payment_type}-{payment_id}"


def current_cycle_reference(student: ERPStudent, application: ERPApplication | None) -> str:
    if application and application.active_cycle_reference:
        return application.active_cycle_reference
    return f"APP-{student.application_number}-01"


def next_renewal_cycle_reference(student: ERPStudent, application: ERPApplication | None) -> str:
    current = current_cycle_reference(student, application)
    try:
        prefix, raw_counter = current.rsplit("-", 1)
        return f"{prefix}-{int(raw_counter) + 1:02d}"
    except (ValueError, TypeError):
        return f"APP-{student.application_number}-02"


def cycle_label(application: ERPApplication | None) -> str:
    if not application:
        return "new"
    return application.application_type or "new"


def latest_application_payment(application: ERPApplication | None) -> ERPApplicationPayment | None:
    if not application or not application.application_payments:
        return None
    current_cycle = application.active_cycle_reference
    for payment in application.application_payments:
        if not current_cycle or payment.cycle_reference == current_cycle or payment.cycle_reference is None:
            return payment
    return None


def latest_hostel_payment(application: ERPApplication | None) -> ERPHostelPayment | None:
    if not application or not application.hostel_payments:
        return None
    current_cycle = application.active_cycle_reference
    for payment in application.hostel_payments:
        if not current_cycle or payment.cycle_reference == current_cycle or payment.cycle_reference is None:
            return payment
    return None


def latest_successful_application_payment(application: ERPApplication | None) -> ERPApplicationPayment | None:
    if not application or not application.application_payments:
        return None
    current_cycle = application.active_cycle_reference
    return next(
        (
            payment
            for payment in application.application_payments
            if payment.status == PAYMENT_STATUS_SUCCESS
            and (not current_cycle or payment.cycle_reference == current_cycle or payment.cycle_reference is None)
        ),
        None,
    )


def latest_successful_hostel_payment(application: ERPApplication | None) -> ERPHostelPayment | None:
    if not application or not application.hostel_payments:
        return None
    current_cycle = application.active_cycle_reference
    return next(
        (
            payment
            for payment in application.hostel_payments
            if payment.status == PAYMENT_STATUS_SUCCESS
            and (not current_cycle or payment.cycle_reference == current_cycle or payment.cycle_reference is None)
        ),
        None,
    )


def verification_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return "pending"
    return "verified" if application.is_verified else "pending"


def application_payment_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return PAYMENT_STATUS_PENDING
    payment = latest_application_payment(application)
    if not payment:
        return PAYMENT_STATUS_PENDING
    if payment.status == PAYMENT_STATUS_SUCCESS:
        return "paid"
    if payment.status == PAYMENT_STATUS_FAILED:
        return PAYMENT_STATUS_FAILED
    return PAYMENT_STATUS_PENDING


def shortlist_status(application: ERPApplication | None) -> str:
    if not application or application.form_status != "submitted":
        return "pending"
    return "shortlisted" if application.is_shortlisted else "pending"


def hostel_status(application: ERPApplication | None) -> str:
    if not application or not application.is_shortlisted:
        return "not_available"
    payment = latest_hostel_payment(application)
    if payment:
        if payment.status == PAYMENT_STATUS_SUCCESS:
            return "paid"
        if payment.status == PAYMENT_STATUS_FAILED:
            return "payment_failed"
        return "payment_pending"
    if application.allocated_hostel:
        return "payment_pending"
    if application.preferred_hostel:
        return "awaiting_allocation"
    return "preference_pending"


def current_application_status(application: ERPApplication | None) -> str:
    if not application:
        return "Not Started"
    if application.form_status == "draft":
        return "Renewal Draft Saved" if cycle_label(application) == "renewal" else "Draft Saved"
    hostel_payment = latest_hostel_payment(application)
    if hostel_payment and hostel_payment.status == PAYMENT_STATUS_SUCCESS:
        return "Hostel Fee Paid"
    if hostel_payment and hostel_payment.status == PAYMENT_STATUS_PENDING:
        return "Hostel Fee Pending Approval"
    if hostel_payment and hostel_payment.status == PAYMENT_STATUS_FAILED:
        return "Hostel Fee Failed"
    application_payment = latest_application_payment(application)
    if application_payment and application_payment.status == PAYMENT_STATUS_PENDING:
        return "Application Fee Pending Approval"
    if application_payment and application_payment.status == PAYMENT_STATUS_FAILED:
        return "Application Fee Failed"
    if application.allocated_hostel:
        return "Hostel Allocated"
    if application.is_shortlisted:
        return "Shortlisted"
    if application.is_verified:
        return "Under Review"
    if application.form_status == "submitted":
        return "Renewal Submitted" if cycle_label(application) == "renewal" else "Application Submitted"
    return "Not Started"


def can_edit_application(application: ERPApplication | None) -> bool:
    return application is None or not application.is_verified


def can_choose_hostel(application: ERPApplication | None) -> bool:
    return bool(application and application.is_shortlisted and not latest_hostel_payment(application))


def can_pay_application_fee(application: ERPApplication | None) -> bool:
    if not application or application.form_status != "submitted":
        return False
    payment = latest_application_payment(application)
    return payment is None or payment.status == PAYMENT_STATUS_FAILED


def can_pay_hostel_fee(application: ERPApplication | None) -> bool:
    if not application or not application.is_shortlisted or not application.allocated_hostel:
        return False
    payment = latest_hostel_payment(application)
    return payment is None or payment.status == PAYMENT_STATUS_FAILED


def build_asset_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return f"/{relative_path.lstrip('/')}"


def build_document_summary(application: ERPApplication | None) -> dict[str, str | None]:
    if not application:
        return {
            "student_photo_url": None,
            "aadhaar_card_url": None,
            "college_id_url": None,
            "marksheet_url": None,
        }
    return {
        "student_photo_url": build_asset_url(application.student_photo_path),
        "aadhaar_card_url": build_asset_url(application.aadhaar_card_path),
        "college_id_url": build_asset_url(application.college_id_path),
        "marksheet_url": build_asset_url(application.marksheet_path),
    }


def tracker_steps(student: ERPStudent, application: ERPApplication | None) -> list[dict[str, object | None]]:
    hostel_payment = latest_hostel_payment(application)
    allocation_label = "Hostel, room, and bed assigned."
    if application and application.allocated_room:
        allocation_label = (
            f"{application.allocated_room.hostel_name}, Block {application.allocated_room.block_name}, "
            f"Room {application.allocated_room.room_number}"
            f"{f', Bed {application.bed_number}' if application.bed_number else ''} assigned."
        )
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
            "description": "Renewal form saved and submitted for review." if cycle_label(application) == "renewal" else "Application form saved and submitted for review.",
        },
        {
            "key": "application_verified",
            "label": "Under Review",
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
            "description": allocation_label,
        },
        {
            "key": "hostel_payment",
            "label": "Hostel Fee Paid",
            "state": "completed" if hostel_payment and hostel_payment.status == PAYMENT_STATUS_SUCCESS else "current" if application and application.allocated_hostel else "pending",
            "date": hostel_payment.payment_date if hostel_payment and hostel_payment.status == PAYMENT_STATUS_SUCCESS else None,
            "description": (
                "Final hostel fee payment verified and receipt generated."
                if hostel_payment and hostel_payment.status == PAYMENT_STATUS_SUCCESS
                else "Payment submitted in demo mode and waiting for admin approval."
                if hostel_payment and hostel_payment.status == PAYMENT_STATUS_PENDING
                else "Payment was rejected. Submit it again for admin review."
                if hostel_payment and hostel_payment.status == PAYMENT_STATUS_FAILED
                else "Final hostel fee payment and receipt generation."
            ),
        },
    ]


def student_notifications(student: ERPStudent, application: ERPApplication | None) -> list[dict[str, object | None]]:
    notifications: list[dict[str, object | None]] = []
    app_payment = latest_application_payment(application)
    hostel_payment = latest_hostel_payment(application)

    if not application or application.form_status != "submitted":
        notifications.append(
            {
                "title": "Complete the application form",
                "description": "Fill all required fields, upload your photograph, and submit the hostel admission form.",
                "tone": "action",
                "created_at": student.created_at,
            }
        )
        return notifications

    if not app_payment:
        notifications.append(
            {
                "title": "Application fee pending",
                "description": (
                    f"Pay the renewal fee of INR {settings.APP_PAYMENT_AMOUNT} to continue hostel renewal processing."
                    if cycle_label(application) == "renewal"
                    else f"Pay the application fee of INR {settings.APP_PAYMENT_AMOUNT} to continue processing."
                ),
                "tone": "warning",
                "created_at": application.submitted_at,
            }
        )
    elif app_payment.status == PAYMENT_STATUS_PENDING:
        notifications.append(
            {
                "title": "Application fee awaiting approval",
                "description": "Your demo payment has been submitted and is waiting for admin approval.",
                "tone": "info",
                "created_at": app_payment.payment_date,
            }
        )
    elif app_payment.status == PAYMENT_STATUS_FAILED:
        notifications.append(
            {
                "title": "Application fee was rejected",
                "description": "Admin rejected the payment record. Submit the payment again to continue.",
                "tone": "warning",
                "created_at": app_payment.payment_date,
            }
        )

    if not application.is_verified:
        notifications.append(
            {
                "title": "Application under review",
                "description": "Your submitted application is waiting for admin verification.",
                "tone": "info",
                "created_at": application.submitted_at,
            }
        )
    elif not application.is_shortlisted:
        notifications.append(
            {
                "title": "Waiting for shortlist update",
                "description": "Your documents are verified. Shortlist decisions will appear here.",
                "tone": "info",
                "created_at": application.verified_at,
            }
        )

    if application.is_shortlisted and not application.preferred_hostel and not application.allocated_hostel:
        notifications.append(
            {
                "title": "Choose hostel preference",
                "description": "Save your preferred hostel to help the allocation process.",
                "tone": "action",
                "created_at": application.shortlisted_at,
            }
        )

    if application.allocated_hostel and not hostel_payment:
        room_bits = [
            application.allocated_hostel,
            f"Block {application.allocated_room.block_name}" if application.allocated_room else None,
            f"Room {application.allocated_room.room_number}" if application.allocated_room else None,
            f"Bed {application.bed_number}" if application.bed_number else None,
        ]
        notifications.append(
            {
                "title": "Hostel allocated",
                "description": f"Your allocation is {' • '.join([bit for bit in room_bits if bit])}. Hostel fee payment is pending.",
                "tone": "success",
                "created_at": application.hostel_allocated_at,
            }
        )
    elif hostel_payment and hostel_payment.status == PAYMENT_STATUS_PENDING:
        notifications.append(
            {
                "title": "Hostel payment awaiting approval",
                "description": "Your hostel payment record was submitted successfully and is waiting for admin approval.",
                "tone": "info",
                "created_at": hostel_payment.payment_date,
            }
        )
    elif hostel_payment and hostel_payment.status == PAYMENT_STATUS_FAILED:
        notifications.append(
            {
                "title": "Hostel payment was rejected",
                "description": "Admin rejected the hostel payment record. Submit it again to complete the admission cycle.",
                "tone": "warning",
                "created_at": hostel_payment.payment_date,
            }
        )

    if hostel_payment and hostel_payment.status == PAYMENT_STATUS_SUCCESS:
        notifications.append(
            {
                "title": "Admission cycle completed",
                "description": "Hostel fee paid successfully. Download your final receipt from the dashboard.",
                "tone": "success",
                "created_at": hostel_payment.payment_date,
            }
        )

    return notifications


def room_occupied_beds(room: ERPHostelRoom) -> int:
    return sum(1 for application in room.applications if application.allocated_hostel and application.allocated_room_id == room.id)


def room_total_occupied_beds(
    db: Session,
    room: ERPHostelRoom,
    *,
    exclude_student_id: int | None = None,
    exclude_old_student_id: int | None = None,
) -> int:
    application_occupancy = sum(
        1
        for application in room.applications
        if application.allocated_hostel
        and application.allocated_room_id == room.id
        and application.student_id != exclude_student_id
    )
    old_student_occupancy = db.scalar(
        select(func.count(ERPStudent.id)).where(
            ERPStudent.is_old_student == True,
            ERPStudent.hostel_name == room.hostel_name,
            ERPStudent.block_name == room.block_name,
            ERPStudent.room_number == room.room_number,
            ERPStudent.id != exclude_old_student_id,
        )
    )
    return application_occupancy + (old_student_occupancy or 0)


def refresh_room_occupancy(db: Session, room: ERPHostelRoom) -> int:
    room.occupied_beds = room_total_occupied_beds(db, room)
    db.add(room)
    return room.occupied_beds


def update_room_occupancy(db: Session, room: ERPHostelRoom):
    refresh_room_occupancy(db, room)
    db.commit()


def build_room_summary(room: ERPHostelRoom) -> dict[str, object]:
    occupied_beds = room.occupied_beds or 0
    available_beds = max(room.bed_capacity - occupied_beds, 0)
    return {
        "id": room.id,
        "hostel_name": room.hostel_name,
        "block_name": room.block_name,
        "room_number": room.room_number,
        "bed_capacity": room.bed_capacity,
        "occupied_beds": occupied_beds,
        "available_beds": available_beds,
        "is_active": room.is_active,
        "notes": room.notes,
    }


def build_admin_recent_activities(students: list[ERPStudent]) -> list[dict[str, object | None]]:
    activities: list[dict[str, object | None]] = []
    for student in students:
        application = student.application
        if not application:
            continue
        if application.submitted_at:
            activities.append(
                {
                    "title": "Application submitted",
                    "description": f"{application.name or student.application_number} submitted the hostel form.",
                    "timestamp": application.submitted_at,
                    "tone": "info",
                }
            )
        if application.verified_at:
            activities.append(
                {
                    "title": "Application verified",
                    "description": f"{application.name or student.application_number} was verified by admin.",
                    "timestamp": application.verified_at,
                    "tone": "success",
                }
            )
        if application.shortlisted_at:
            activities.append(
                {
                    "title": "Student shortlisted",
                    "description": f"{application.name or student.application_number} moved to shortlist.",
                    "timestamp": application.shortlisted_at,
                    "tone": "accent",
                }
            )
        if application.hostel_allocated_at:
            room_text = ""
            if application.allocated_room:
                room_text = f" Block {application.allocated_room.block_name}, Room {application.allocated_room.room_number}"
            activities.append(
                {
                    "title": "Room allocated",
                    "description": f"{application.name or student.application_number} received {application.allocated_hostel or 'hostel'}{room_text}.",
                    "timestamp": application.hostel_allocated_at,
                    "tone": "success",
                }
            )

    activities.sort(key=lambda item: item.get("timestamp") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return activities[:8]


def application_summary(student: ERPStudent, application: ERPApplication | None) -> dict[str, object | None]:
    app_payment = latest_application_payment(application)
    hostel_payment = latest_hostel_payment(application)
    allocated_room = application.allocated_room if application else None
    return {
        "name": application.name if application else None,
        "application_type": cycle_label(application),
        "cycle_reference": application.active_cycle_reference if application else None,
        "renewal_reference_number": application.renewal_reference_number if application else None,
        "previous_application_number": application.previous_application_number if application else None,
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
        "room_type": application.room_type if application else None,
        "food_preference": application.food_preference if application else None,
        "allocated_hostel": application.allocated_hostel if application else None,
        "hostel_block": allocated_room.block_name if allocated_room else None,
        "room_number": allocated_room.room_number if allocated_room else None,
        "bed_number": application.bed_number if application else None,
        **build_document_summary(application),
        "application_payment_transaction_id": app_payment.transaction_id if app_payment else None,
        "hostel_payment_transaction_id": hostel_payment.transaction_id if hostel_payment else None,
    }


def build_receipt_summary(payment_type: str, amount: float, payment) -> dict[str, object | None] | None:
    if not payment or payment.status != PAYMENT_STATUS_SUCCESS:
        return None
    return {
        "payment_type": payment_type,
        "amount": amount,
        "transaction_id": payment.transaction_id,
        "payment_date": payment.payment_date,
        "status": payment.status,
        "payment_mode": payment.payment_mode,
        "receipt_url": build_asset_url(payment.receipt_path),
    }


def build_payment_history(application: ERPApplication | None) -> list[dict[str, object | None]]:
    if not application:
        return []

    items: list[dict[str, object | None]] = []
    for payment in application.application_payments:
        if payment.status == PAYMENT_STATUS_SUCCESS:
            items.append(
                {
                    "payment_type": "application_fee",
                    "amount": float(payment.amount),
                    "transaction_id": payment.transaction_id,
                    "payment_date": payment.payment_date,
                    "status": payment.status,
                    "payment_mode": payment.payment_mode,
                    "receipt_url": build_asset_url(payment.receipt_path),
                }
            )
    for payment in application.hostel_payments:
        if payment.status == PAYMENT_STATUS_SUCCESS:
            items.append(
                {
                    "payment_type": "hostel_fee",
                    "amount": float(payment.amount),
                    "transaction_id": payment.transaction_id,
                    "payment_date": payment.payment_date,
                    "status": payment.status,
                    "payment_mode": payment.payment_mode,
                    "receipt_url": build_asset_url(payment.receipt_path),
                }
            )
    items.sort(key=lambda item: item["payment_date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items


def build_student_dashboard(student: ERPStudent) -> dict[str, object | None]:
    application = student.application
    app_payment = latest_application_payment(application)
    app_success_payment = latest_successful_application_payment(application)
    hostel_payment = latest_hostel_payment(application)
    hostel_success_payment = latest_successful_hostel_payment(application)
    allocated_hostel = application.allocated_hostel if application else None
    allocated_room = application.allocated_room if application else None
    hostel_fee_amount = None
    if allocated_hostel:
        hostel_fee_amount = settings.hostel_fee(allocated_hostel)

    return {
        "application_number": student.application_number,
        "application_type": cycle_label(application),
        "cycle_reference": application.active_cycle_reference if application else current_cycle_reference(student, application),
        "renewal_reference_number": application.renewal_reference_number if application else None,
        "can_start_renewal": bool(application and application.form_status == "submitted"),
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
        "can_pay_application_fee": can_pay_application_fee(application),
        "can_choose_hostel": can_choose_hostel(application),
        "can_pay_hostel_fee": can_pay_hostel_fee(application),
        "preferred_hostel": application.preferred_hostel if application else None,
        "allocated_hostel": allocated_hostel,
        "allotted_category": application.allotted_category if application else None,
        "hostel_block": allocated_room.block_name if allocated_room else None,
        "room_number": allocated_room.room_number if allocated_room else None,
        "bed_number": application.bed_number if application else None,
        "application_fee_amount": settings.APP_PAYMENT_AMOUNT,
        "hostel_fee_amount": hostel_fee_amount,
        "photo_url": build_asset_url(application.student_photo_path) if application else None,
        "application_receipt": build_receipt_summary(
            "application_fee",
            float(settings.APP_PAYMENT_AMOUNT),
            app_success_payment,
        ),
        "hostel_receipt": build_receipt_summary(
            "hostel_fee",
            float(hostel_success_payment.amount) if hostel_success_payment else 0.0,
            hostel_success_payment,
        ),
        "payment_gateway": settings.payment_provider_public_config,
        "payment_history": build_payment_history(application),
        "tracker": tracker_steps(student, application),
        "notifications": student_notifications(student, application),
        "summary": application_summary(student, application),
    }


def build_admin_student_summary(student: ERPStudent) -> dict[str, object | None]:
    application = student.application
    hostel_payment = latest_hostel_payment(application)
    allocated_room = application.allocated_room if application else None
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
        "allotted_category": application.allotted_category if application else None,
        "hostel_block": allocated_room.block_name if allocated_room else None,
        "room_number": allocated_room.room_number if allocated_room else None,
        "bed_number": application.bed_number if application else None,
        "application_submitted_at": application.submitted_at if application else None,
        "verified_at": application.verified_at if application else None,
        "shortlisted_at": application.shortlisted_at if application else None,
        "hostel_payment_date": hostel_payment.payment_date if hostel_payment else None,
    }


def old_students_count(db: Session) -> int:
    from sqlalchemy import func
    from ..erp_models import ERPStudent
    return db.scalar(
        select(func.count(ERPStudent.id)).filter(
            ERPStudent.is_old_student == True,
            ERPStudent.old_student_status == 'ACTIVE'
        )
    )


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
            "is_old_student": student.is_old_student,
            "old_student_status": student.old_student_status,
        }
    )
    return dashboard


def build_old_student_summary(student: ERPStudent) -> dict:
    application = student.application
    student_name = application.name if application and application.name else student.application_number
    return {
        "id": student.id,
        "hostel_id": student.application_number,
        "student_name": student_name,
        "admission_id": application.admission_application_id if application else None,
        "roll_number": application.roll_number if application else None,
        "course_name": application.course_name if application else None,
        "session": application.session if application else None,
        "mobile_number": student.mobile_number,
        "email": student.email,
        "category": application.category if application else None,
        "hostel_name": student.hostel_name,
        "block_name": student.block_name,
        "room_number": student.room_number,
        "bed_number": student.bed_number,
        "old_student_status": student.old_student_status,
        "created_at": student.created_at,
        "updated_at": student.updated_at,
    }


def validate_old_student_allocation(
    db: Session,
    hostel_name: str | None,
    block_name: str | None,
    room_number: str | None,
    bed_number: str | None,
    exclude_student_id: int | None = None
) -> None:
    if not all([hostel_name, block_name, room_number]):
        return
    
    # Find room
    from sqlalchemy import select
    from ..erp_models import ERPHostelRoom
    room = db.scalar(
        select(ERPHostelRoom).where(
            ERPHostelRoom.hostel_name == hostel_name,
            ERPHostelRoom.block_name == block_name,
            ERPHostelRoom.room_number == room_number,
            ERPHostelRoom.is_active == True
        )
    )
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or inactive")
    
    # Check existing allocations in room (new + old students)
    occupied_beds: set[str] = set()
    for app in room.applications:
        if app.student_id != exclude_student_id:
            normalized = normalize_bed_number(app.bed_number)
            occupied_beds.add(normalized or f"APP-{app.student_id}")

    from ..erp_models import ERPStudent
    old_students_in_room = db.execute(
        select(ERPStudent).where(
            ERPStudent.is_old_student == True,
            ERPStudent.hostel_name == hostel_name,
            ERPStudent.block_name == block_name,
            ERPStudent.room_number == room_number,
            ERPStudent.id != exclude_student_id,
        )
    ).scalars().all()
    for old_student in old_students_in_room:
        normalized = normalize_bed_number(old_student.bed_number)
        occupied_beds.add(normalized or f"OLD-{old_student.id}")

    normalized_bed = normalize_bed_number(bed_number)
    if normalized_bed and normalized_bed in occupied_beds:
        raise HTTPException(status_code=409, detail="Bed already allocated to another student.")

    if len(occupied_beds) >= room.bed_capacity:
        raise HTTPException(status_code=409, detail="Room is full")
