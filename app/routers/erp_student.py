from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..erp_dependencies import get_current_student
from ..erp_models import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPStudent
from ..erp_security import create_access_token, generate_random_password, hash_password, verify_password
from ..erp_schemas import (
    ApplicationFormPayload,
    GenericMessageResponse,
    PaymentResponse,
    StudentDashboardResponse,
    StudentLoginRequest,
    StudentLoginResponse,
    StudentRegistrationRequest,
    StudentRegistrationResponse,
)
from ..services.application_number import generate_application_number
from ..services.email_service import send_receipt_email
from ..services.erp_service import (
    APPLICATION_FIELDS,
    REQUIRED_SUBMISSION_FIELDS,
    application_summary,
    build_asset_url,
    build_student_dashboard,
    calculate_percentage,
    can_edit_application,
    clean_text,
    ensure_valid_hostel_name,
    latest_application_payment,
    latest_hostel_payment,
    parse_optional_date,
    parse_optional_decimal,
    utc_now,
)
from ..services.receipt_service import generate_application_fee_receipt, generate_hostel_receipt
from ..utils.file_storage import save_upload_file

router = APIRouter(tags=["erp-student"])


class PaymentRequest(BaseModel):
    transaction_id: str | None = None


class HostelPreferenceRequest(BaseModel):
    hostel_name: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_login_identifier(value: str) -> str:
    return value.strip()


def _normalize_mobile_number(value: str) -> str:
    return "".join(char for char in value if char.isdigit()) or value.strip()


def _existing_student_by_email_or_mobile(db: Session, email: str, mobile_number: str) -> ERPStudent | None:
    return db.scalar(
        select(ERPStudent).where(
            (ERPStudent.email == email) | (ERPStudent.mobile_number == mobile_number)
        )
    )


async def _parse_application_form(request: Request) -> tuple[dict[str, object | None], object | None]:
    form = await request.form()
    photo = form.get("student_photo") or form.get("student_image") or form.get("photo")

    aliases = {
        "aadhaar_number": ["aadhaar_number", "aadhar_number"],
        "guardian_mobile_number": ["guardian_mobile_number", "local_guardian_mobile", "guardian_mobile"],
        "intermediate_board": ["intermediate_board", "intermediate_board_name"],
        "total_marks": ["total_marks", "intermediate_total_marks"],
        "marks_obtained": ["marks_obtained", "intermediate_marks_obtained"],
        "result_type": ["result_type", "intermediate_result_type"],
        "aggregate_percentage": ["aggregate_percentage", "intermediate_percentage"],
        "roll_number": ["roll_number", "roll_no"],
        "preferred_hostel": ["preferred_hostel", "hostel_name", "hostel_type"],
    }

    data: dict[str, object | None] = {}
    for field_name in APPLICATION_FIELDS:
        possible_keys = aliases.get(field_name, [field_name])
        raw_value = None
        for key in possible_keys:
            if key in form:
                raw_value = form.get(key)
                break
        data[field_name] = raw_value

    data["date_of_birth"] = parse_optional_date(data.get("date_of_birth"))
    data["total_marks"] = parse_optional_decimal(data.get("total_marks"))
    data["marks_obtained"] = parse_optional_decimal(data.get("marks_obtained"))
    data["aggregate_percentage"] = parse_optional_decimal(data.get("aggregate_percentage"))
    if data["aggregate_percentage"] is None:
        data["aggregate_percentage"] = calculate_percentage(
            data.get("total_marks"),
            data.get("marks_obtained"),
        )

    for key, value in list(data.items()):
        if key in {"date_of_birth", "total_marks", "marks_obtained", "aggregate_percentage"}:
            continue
        data[key] = clean_text(value)

    if data.get("preferred_hostel"):
        data["preferred_hostel"] = ensure_valid_hostel_name(str(data["preferred_hostel"]))

    return data, photo


def _get_or_create_application(student: ERPStudent, db: Session) -> ERPApplication:
    application = student.application
    if application:
        return application

    application = ERPApplication(
        student_id=student.id,
        email=student.email,
        mobile_number=student.mobile_number,
        date_of_birth=student.date_of_birth,
        college_name="Magadh Mahila College",
    )
    db.add(application)
    db.flush()
    return application


def _apply_application_payload(
    *,
    student: ERPStudent,
    application: ERPApplication,
    payload: dict[str, object | None],
    photo,
) -> None:
    application.email = student.email
    application.mobile_number = student.mobile_number

    for field_name, value in payload.items():
        if field_name in {"email", "mobile_number"}:
            continue
        if field_name == "preferred_hostel" and value is None:
            continue
        setattr(application, field_name, value)

    if application.date_of_birth is None:
        application.date_of_birth = student.date_of_birth

    if photo and getattr(photo, "filename", None):
        application.student_photo_path = save_upload_file(
            photo,
            settings.photo_dir,
            prefix=f"student_{student.id}",
        )


def _validate_submission(application: ERPApplication) -> list[str]:
    missing_fields: list[str] = []
    for field_name in REQUIRED_SUBMISSION_FIELDS:
        value = getattr(application, field_name)
        if value is None or str(value).strip() == "":
            missing_fields.append(field_name)

    if not application.student_photo_path:
        missing_fields.append("student_photo")

    return missing_fields


def _receipt_absolute_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return str((Path(__file__).resolve().parents[2] / relative_path).resolve())


@router.post("/register", response_model=StudentRegistrationResponse, status_code=status.HTTP_201_CREATED)
def register_student(payload: StudentRegistrationRequest, db: Session = Depends(get_db)) -> StudentRegistrationResponse:
    email = _normalize_email(payload.email)
    mobile_number = _normalize_mobile_number(payload.mobile_number)
    if _existing_student_by_email_or_mobile(db, email, mobile_number):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student with this email or mobile number already exists.",
        )

    generated_password = clean_text(payload.password) or generate_random_password()
    student = ERPStudent(
        application_number=f"TEMP-{uuid4().hex[:10]}",
        email=email,
        date_of_birth=payload.date_of_birth,
        mobile_number=mobile_number,
        password_hash=hash_password(generated_password),
    )
    db.add(student)
    db.flush()
    student.application_number = generate_application_number(student.id)
    db.commit()
    db.refresh(student)

    return StudentRegistrationResponse(
        application_number=student.application_number,
        email=student.email,
        mobile_number=student.mobile_number,
        password=generated_password,
        message="Registration completed successfully.",
    )


@router.post("/login", response_model=StudentLoginResponse)
def login_student(payload: StudentLoginRequest, db: Session = Depends(get_db)) -> StudentLoginResponse:
    login_identifier = _normalize_login_identifier(payload.email)
    student = None
    if "@" in login_identifier:
        email = _normalize_email(login_identifier)
        student = db.scalar(select(ERPStudent).where(ERPStudent.email == email))
    else:
        student = db.scalar(
            select(ERPStudent).where(ERPStudent.application_number == login_identifier)
        )

    if not student or not verify_password(payload.password, student.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    verification_dob = payload.date_of_birth or payload.dob
    if verification_dob and verification_dob != student.date_of_birth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Date of birth does not match.")

    token = create_access_token(subject=str(student.id), role="student")
    application_completed = bool(student.application and student.application.form_status == "submitted")

    return StudentLoginResponse(
        access_token=token,
        application_completed=application_completed,
        redirect="/dashboard" if application_completed else "/application-form",
        application_number=student.application_number,
        student_name=student.application.name if student.application else None,
    )


@router.get("/application", response_model=ApplicationFormPayload)
def get_application_form(
    student: ERPStudent = Depends(get_current_student),
) -> ApplicationFormPayload:
    application = student.application
    summary = application_summary(student, application)
    summary["student_photo_url"] = build_asset_url(application.student_photo_path) if application else None

    return ApplicationFormPayload(
        application_number=student.application_number,
        email=student.email,
        mobile_number=student.mobile_number,
        registration_date_of_birth=student.date_of_birth,
        form_status=application.form_status if application else "not_started",
        is_editable=can_edit_application(application),
        data=summary,
    )


@router.post("/application/draft", response_model=GenericMessageResponse)
async def save_application_draft(
    request: Request,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = _get_or_create_application(student, db)
    if application.is_verified:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified applications cannot be edited.")

    payload, photo = await _parse_application_form(request)
    _apply_application_payload(student=student, application=application, payload=payload, photo=photo)
    if application.form_status != "submitted":
        application.form_status = "draft"
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Draft saved successfully.")


@router.post("/application/submit", response_model=GenericMessageResponse)
async def submit_application(
    request: Request,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = _get_or_create_application(student, db)
    if application.is_verified:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified applications cannot be edited.")

    payload, photo = await _parse_application_form(request)
    _apply_application_payload(student=student, application=application, payload=payload, photo=photo)

    missing_fields = _validate_submission(application)
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required fields: {', '.join(missing_fields)}.",
        )

    application.form_status = "submitted"
    application.submitted_at = utc_now()
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Application submitted successfully.")


@router.post("/hostel/preference", response_model=GenericMessageResponse)
def save_hostel_preference(
    payload: HostelPreferenceRequest,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = student.application
    if not application or not application.is_shortlisted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shortlist status is pending.")
    if latest_hostel_payment(application):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel payment is already completed.")
    if application.allocated_hostel:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel has already been allocated.")

    application.preferred_hostel = ensure_valid_hostel_name(payload.hostel_name)
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Hostel preference saved successfully.")


@router.get("/dashboard", response_model=StudentDashboardResponse)
def get_dashboard(student: ERPStudent = Depends(get_current_student)) -> StudentDashboardResponse:
    return StudentDashboardResponse(**build_student_dashboard(student))


@router.post("/payment/application", response_model=PaymentResponse)
def pay_application_fee(
    payload: PaymentRequest,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> PaymentResponse:
    application = student.application
    if not application or application.form_status != "submitted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submit the application first.")
    if latest_application_payment(application):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application fee is already paid.")

    transaction_id = clean_text(payload.transaction_id) or f"APP-DEMO-{uuid4().hex[:12].upper()}"
    existing_payment = db.scalar(
        select(ERPApplicationPayment).where(ERPApplicationPayment.transaction_id == transaction_id)
    )
    if existing_payment:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction ID already exists.")

    payment_date = utc_now()
    receipt_path = generate_application_fee_receipt(
        payload={
            "application_number": student.application_number,
            "student_name": application.name,
            "course_name": application.course_name,
            "session": application.session,
            "transaction_id": transaction_id,
            "payment_date": payment_date.strftime("%d %b %Y %I:%M %p"),
            "amount": f"INR {settings.APP_PAYMENT_AMOUNT}",
        }
    )

    payment = ERPApplicationPayment(
        student_id=student.id,
        application_id=application.id,
        transaction_id=transaction_id,
        amount=settings.APP_PAYMENT_AMOUNT,
        receipt_path=receipt_path,
        payment_date=payment_date,
    )
    email_status = send_receipt_email(
        recipient=student.email,
        student_name=application.name or "Student",
        subject="MMC Hostel ERP Application Fee Receipt",
        body=(
            f"Your application fee payment of INR {settings.APP_PAYMENT_AMOUNT} has been recorded. "
            f"Transaction ID: {transaction_id}."
        ),
        receipt_path=_receipt_absolute_path(receipt_path),
    )
    payment.email_sent = email_status == "sent"

    db.add(payment)
    db.commit()

    return PaymentResponse(
        message="Application fee recorded successfully.",
        transaction_id=transaction_id,
        receipt_url=build_asset_url(receipt_path),
        email_status=email_status,
        amount=float(settings.APP_PAYMENT_AMOUNT),
    )


@router.post("/payment/hostel", response_model=PaymentResponse)
def pay_hostel_fee(
    payload: PaymentRequest,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> PaymentResponse:
    application = student.application
    if not application or not application.is_shortlisted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student is not shortlisted yet.")
    if not application.allocated_hostel:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel allocation is pending.")
    if latest_hostel_payment(application):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel fee is already paid.")

    transaction_id = clean_text(payload.transaction_id) or f"HOSTEL-DEMO-{uuid4().hex[:12].upper()}"
    existing_payment = db.scalar(
        select(ERPHostelPayment).where(ERPHostelPayment.transaction_id == transaction_id)
    )
    if existing_payment:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction ID already exists.")

    amount = settings.hostel_fee(application.allocated_hostel)
    payment_date = utc_now()
    receipt_path = generate_hostel_receipt(
        payload={
            "application_number": student.application_number,
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
            "amount": f"INR {amount}",
            "transaction_id": transaction_id,
            "payment_date": payment_date.strftime("%d %b %Y %I:%M %p"),
        }
    )

    payment = ERPHostelPayment(
        student_id=student.id,
        application_id=application.id,
        hostel_name=application.allocated_hostel,
        transaction_id=transaction_id,
        amount=amount,
        receipt_path=receipt_path,
        payment_date=payment_date,
    )
    email_status = send_receipt_email(
        recipient=student.email,
        student_name=application.name or "Student",
        subject="MMC Hostel ERP Final Hostel Receipt",
        body=(
            f"Your hostel payment of INR {amount} for {application.allocated_hostel} has been recorded. "
            f"Transaction ID: {transaction_id}."
        ),
        receipt_path=_receipt_absolute_path(receipt_path),
    )
    payment.email_sent = email_status == "sent"

    db.add(payment)
    db.commit()

    return PaymentResponse(
        message="Hostel fee recorded successfully.",
        transaction_id=transaction_id,
        receipt_url=build_asset_url(receipt_path),
        email_status=email_status,
        amount=float(amount),
    )
