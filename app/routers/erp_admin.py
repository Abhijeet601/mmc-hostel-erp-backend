from __future__ import annotations

from collections import Counter
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_admin
from ..erp_models import ActivityLog, ERPApplication, ERPApplicationPayment, ERPComplaint, ERPHostelPayment, ERPHostelRoom, ERPStudent
from ..erp_schemas import (
    AdminAllocationRequest,
    AdminDashboardResponse,
    AdminHostelRoomPayload,
    AdminPaymentListResponse,
    AdminStudentDetailResponse,
    AdminShortlistRequest,
    AdminStudentListResponse,
    AdminPaymentSummary,
    AdminVerifyRequest,
    BulkCombinedUploadResponse,
    ChartDatum,
    ComplaintListResponse,
    ComplaintResponse,
    ComplaintUpdateRequest,
    GenericMessageResponse,
    HostelRoomListResponse,
    HostelRoomSummary,
)
from ..services.erp_service import (
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_SUCCESS,
    application_payment_status,
    build_admin_recent_activities,
    build_admin_student_detail,
    build_admin_student_summary,
    build_asset_url,
    build_room_summary,
    clean_text,
    current_application_status,
    ensure_valid_hostel_name,
    hostel_status,
    normalize_bed_number,
    refresh_room_occupancy,
    room_total_occupied_beds,
    payment_reference,
    update_room_occupancy,
    shortlist_status,
    utc_now,
    verification_status,
)
from ..services.payment_service import approve_application_payment, approve_hostel_payment, reject_payment

router = APIRouter(prefix="/admin", tags=["erp-admin"])


def _students_base_query():
    return select(ERPStudent).options(
        selectinload(ERPStudent.application).selectinload(ERPApplication.application_payments),
        selectinload(ERPStudent.application).selectinload(ERPApplication.hostel_payments),
        selectinload(ERPStudent.application).selectinload(ERPApplication.allocated_room),
    )


def _get_student_with_application(student_id: int, db: Session) -> ERPStudent:
    student = db.scalar(_students_base_query().where(ERPStudent.id == student_id))
    if not student or not student.application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student application not found.")
    return student


def _payments_base_query():
    return {
        "application": select(ERPApplicationPayment).options(
            selectinload(ERPApplicationPayment.student),
            selectinload(ERPApplicationPayment.application),
        ),
        "hostel": select(ERPHostelPayment).options(
            selectinload(ERPHostelPayment.student),
            selectinload(ERPHostelPayment.application),
        ),
    }


def _build_payment_summary(payment_type: str, payment: ERPApplicationPayment | ERPHostelPayment) -> AdminPaymentSummary:
    application = payment.application
    student = payment.student
    return AdminPaymentSummary(
        id=payment_reference(payment_type, payment.id),
        payment_id=payment.id,
        payment_type=payment_type,
        status=payment.status,
        payment_mode=payment.payment_mode,
        transaction_id=payment.transaction_id,
        amount=float(payment.amount),
        payment_date=payment.payment_date,
        receipt_url=build_asset_url(payment.receipt_path),
        application_number=student.application_number,
        student_id=student.id,
        student_name=application.name if application else None,
        course_name=application.course_name if application else None,
        hostel_name=payment.hostel_name if payment_type == "hostel" else application.allocated_hostel if application else None,
    )


def _get_payment_or_404(payment_id: str, db: Session) -> tuple[str, ERPApplicationPayment | ERPHostelPayment]:
    try:
        payment_type, raw_id = payment_id.rsplit("-", 1)
        payment_pk = int(raw_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment record not found.")

    if payment_type == "application":
        payment = db.scalar(_payments_base_query()["application"].where(ERPApplicationPayment.id == payment_pk))
    elif payment_type == "hostel":
        payment = db.scalar(_payments_base_query()["hostel"].where(ERPHostelPayment.id == payment_pk))
    else:
        payment = None

    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment record not found.")
    return payment_type, payment


def _chart_data(counter: Counter[str]) -> list[ChartDatum]:
    return [ChartDatum(label=label, value=value) for label, value in counter.items() if label]


def _rooms_base_query():
    return select(ERPHostelRoom).options(selectinload(ERPHostelRoom.applications))


def _get_room_or_404(room_id: int, db: Session) -> ERPHostelRoom:
    room = db.scalar(_rooms_base_query().where(ERPHostelRoom.id == room_id))
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hostel room not found.")
    return room


def _occupied_room_beds(db: Session, room: ERPHostelRoom, *, ignore_student_id: int | None = None) -> set[str]:
    used_beds = {
        normalize_bed_number(application.bed_number) or f"APP-{application.student_id}"
        for application in room.applications
        if application.allocated_room_id == room.id and application.student_id != ignore_student_id
    }
    old_students = db.execute(
        select(ERPStudent).where(
            ERPStudent.is_old_student == True,
            ERPStudent.hostel_name == room.hostel_name,
            ERPStudent.block_name == room.block_name,
            ERPStudent.room_number == room.room_number,
        )
    ).scalars().all()
    for student in old_students:
        used_beds.add(normalize_bed_number(student.bed_number) or f"OLD-{student.id}")
    return used_beds


def _next_available_bed(db: Session, room: ERPHostelRoom, *, ignore_student_id: int | None = None) -> str | None:
    used_beds = _occupied_room_beds(db, room, ignore_student_id=ignore_student_id)
    for index in range(1, room.bed_capacity + 1):
        candidate = f"B{index}"
        if candidate not in used_beds:
            return candidate
    return None


def _validate_bed_number(room: ERPHostelRoom, bed_number: str) -> str:
    normalized = normalize_bed_number(bed_number)
    if not normalized or not normalized.startswith("B") or not normalized[1:].isdigit():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bed number must be in B1/B2 format.")
    if int(normalized[1:]) > room.bed_capacity:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bed number exceeds room capacity.")
    return normalized


def _ensure_room_identity_available(
    *,
    db: Session,
    hostel_name: str,
    block_name: str,
    room_number: str,
    exclude_room_id: int | None = None,
) -> None:
    rooms = list(db.scalars(select(ERPHostelRoom)))
    for room in rooms:
        if exclude_room_id and room.id == exclude_room_id:
            continue
        if (
            room.hostel_name == hostel_name
            and room.block_name == block_name
            and room.room_number == room_number
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A room with the same hostel, block, and room number already exists.",
            )


YES_VALUES = {"yes", "y", "true", "1", "shortlisted"}
NO_VALUES = {"no", "n", "false", "0", "not shortlisted"}


def _parse_yes_no(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    if text in YES_VALUES:
        return True
    if text in NO_VALUES:
        return False
    return None


def _filter_students_by_query(
    students: list[ERPStudent],
    *,
    search: str = "",
    course: str | None = None,
    category: str | None = None,
    session: str | None = None,
    program: str | None = None,
    shortlist: str | None = None,
    verified: str | None = None,
    hostel_state: str | None = None,
) -> list[ERPStudent]:
    search_term = clean_text(search)
    filtered: list[ERPStudent] = []

    for student in students:
        app = student.application
        if not app:
            continue

        if search_term:
            haystack = " ".join(
                filter(
                    None,
                    [
                        student.application_number,
                        student.email,
                        student.mobile_number,
                        app.name,
                        app.course_name,
                    ],
                )
            ).lower()
            if search_term.lower() not in haystack:
                continue
        if course and app.course_name != course:
            continue
        if category and app.category != category:
            continue
        if session and app.session != session:
            continue
        if program and app.program != program:
            continue
        if shortlist and shortlist_status(app) != shortlist:
            continue
        if verified and verification_status(app) != verified:
            continue
        if hostel_state and hostel_status(app) != hostel_state:
            continue
        filtered.append(student)

    return filtered


async def _load_dataframe(upload: UploadFile, *, empty_message: str = "Upload file is empty.") -> pd.DataFrame:
    filename = (upload.filename or "").lower()
    try:
        raw_bytes = await upload.read()
        buffer = BytesIO(raw_bytes)
        if filename.endswith(".csv"):
            dataframe = pd.read_csv(buffer)
        else:
            dataframe = pd.read_excel(buffer)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unable to parse upload file.") from exc
    finally:
        await upload.close()

    if dataframe.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=empty_message)
    return dataframe


def _pick_column(normalized_columns: dict[str, str], candidates: list[str], *, required: bool = False) -> str | None:
    for candidate in candidates:
        if candidate in normalized_columns:
            return normalized_columns[candidate]
    if required:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Missing required column: {candidates[0]}")
    return None


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> AdminDashboardResponse:
    students = list(db.scalars(_students_base_query()))
    applications = [student.application for student in students if student.application]
    application_payments = [payment for payment in db.scalars(select(ERPApplicationPayment)) if payment.status == PAYMENT_STATUS_SUCCESS]
    hostel_payments = [payment for payment in db.scalars(select(ERPHostelPayment)) if payment.status == PAYMENT_STATUS_SUCCESS]
    rooms = list(db.scalars(_rooms_base_query()))
    for room in rooms:
        refresh_room_occupancy(db, room)

    by_course = Counter(app.course_name or "Unassigned" for app in applications)
    by_category = Counter(app.category or "Unassigned" for app in applications)
    by_status = Counter(current_application_status(app) for app in applications)
    by_hostel = Counter(app.allocated_hostel or "Pending" for app in applications if app.is_shortlisted)
    occupied_beds = sum((room.occupied_beds or 0) for room in rooms if room.is_active)
    available_beds = sum(max(room.bed_capacity - (room.occupied_beds or 0), 0) for room in rooms if room.is_active)

    old_students_count = db.execute(select(func.count(ERPStudent.id)).where(ERPStudent.is_old_student == True, ERPStudent.old_student_status == 'ACTIVE')).scalar() or 0
    return AdminDashboardResponse(
        total_applications=sum(1 for app in applications if app.form_status == "submitted"),
        total_paid=sum(1 for app in applications if application_payment_status(app) == "paid"),
        pending_applications=sum(1 for app in applications if app.form_status == "submitted" and not app.is_verified),
        shortlisted_students=sum(1 for app in applications if app.is_shortlisted),
        verified_students=sum(1 for app in applications if app.is_verified),
        hostel_allocated_students=sum(1 for app in applications if app.allocated_hostel),
        hostel_paid_students=len(hostel_payments),
        old_students=old_students_count,
        total_rooms=sum(1 for room in rooms if room.is_active),
        occupied_beds=occupied_beds,
        available_beds=available_beds,
        application_revenue=float(sum(float(payment.amount) for payment in application_payments)),
        hostel_revenue=float(sum(float(payment.amount) for payment in hostel_payments)),
        by_course=_chart_data(by_course),
        by_category=_chart_data(by_category),
        by_status=_chart_data(by_status),
        by_hostel=_chart_data(by_hostel),
        recent_activities=build_admin_recent_activities(students),
    )


@router.get("/students", response_model=AdminStudentListResponse)
def list_students(
    search: str = Query(default=""),
    course: str | None = Query(default=None),
    category: str | None = Query(default=None),
    session: str | None = Query(default=None),
    program: str | None = Query(default=None),
    shortlist: str | None = Query(default=None),
    verified: str | None = Query(default=None),
    hostel_state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> AdminStudentListResponse:
    students = list(db.scalars(_students_base_query()))
    filtered = _filter_students_by_query(
        students,
        search=search,
        course=course,
        category=category,
        session=session,
        program=program,
        shortlist=shortlist,
        verified=verified,
        hostel_state=hostel_state,
    )
    total = len(filtered)
    page = filtered[offset : offset + limit]
    items = [build_admin_student_summary(student) for student in page]
    return AdminStudentListResponse(total=total, items=items)


@router.get("/students/{student_id}", response_model=AdminStudentDetailResponse)
def get_student_detail(
    student_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> AdminStudentDetailResponse:
    student = _get_student_with_application(student_id, db)
    return AdminStudentDetailResponse(**build_admin_student_detail(student))


@router.get("/payments", response_model=AdminPaymentListResponse)
def list_payments(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> AdminPaymentListResponse:
    application_payments = list(db.scalars(_payments_base_query()["application"]))
    hostel_payments = list(db.scalars(_payments_base_query()["hostel"]))
    items = [
        *(_build_payment_summary("application", payment) for payment in application_payments),
        *(_build_payment_summary("hostel", payment) for payment in hostel_payments),
    ]
    items.sort(key=lambda item: item.payment_date, reverse=True)
    return AdminPaymentListResponse(total=len(items), items=items)


@router.get("/complaints", response_model=ComplaintListResponse)
def list_complaints(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> ComplaintListResponse:
    items = list(db.scalars(select(ERPComplaint).order_by(ERPComplaint.created_at.desc())))
    return ComplaintListResponse(total=len(items), items=[ComplaintResponse.model_validate(item) for item in items])


@router.patch("/complaints/{complaint_id}", response_model=ComplaintResponse)
def update_complaint(
    complaint_id: int,
    payload: ComplaintUpdateRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> ComplaintResponse:
    complaint = db.get(ERPComplaint, complaint_id)
    if not complaint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")
    complaint.status = clean_text(payload.status) or complaint.status
    complaint.assigned_staff = clean_text(payload.assigned_staff)
    complaint.resolution_note = clean_text(payload.resolution_note)
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return ComplaintResponse.model_validate(complaint)


@router.post("/approve-payment/{payment_id}", response_model=GenericMessageResponse)
def approve_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
) -> GenericMessageResponse:
    payment_type, payment = _get_payment_or_404(payment_id, db)
    if payment.status == PAYMENT_STATUS_SUCCESS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment is already approved.")
    if payment.status == PAYMENT_STATUS_FAILED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rejected payments must be resubmitted by the student.")
    if payment.status != PAYMENT_STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending payments can be approved.")

    if payment_type == "application":
        email_status = approve_application_payment(student=payment.student, application=payment.application, payment=payment)
        action = "approve_application_payment"
    else:
        email_status = approve_hostel_payment(student=payment.student, application=payment.application, payment=payment)
        action = "approve_hostel_payment"

    db.add(payment)
    db.add(
        ActivityLog(
            entity_type="payment",
            entity_id=payment_reference(payment_type, payment.id),
            action=action,
            new_values=f"{payment.transaction_id} / {payment.status} / email={email_status}",
            admin_id=current_admin.id,
        )
    )
    db.commit()
    return GenericMessageResponse(message="Payment approved successfully.")


@router.post("/reject-payment/{payment_id}", response_model=GenericMessageResponse)
def reject_pending_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
) -> GenericMessageResponse:
    payment_type, payment = _get_payment_or_404(payment_id, db)
    if payment.status == PAYMENT_STATUS_SUCCESS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved payments cannot be rejected.")
    if payment.status == PAYMENT_STATUS_FAILED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment is already rejected.")
    if payment.status != PAYMENT_STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending payments can be rejected.")

    reject_payment(payment)
    db.add(payment)
    db.add(
        ActivityLog(
            entity_type="payment",
            entity_id=payment_reference(payment_type, payment.id),
            action="reject_payment",
            new_values=f"{payment.transaction_id} / {payment.status}",
            admin_id=current_admin.id,
        )
    )
    db.commit()
    return GenericMessageResponse(message="Payment rejected successfully.")


@router.patch("/students/{student_id}/verify", response_model=GenericMessageResponse)
def verify_student_application(
    student_id: int,
    payload: AdminVerifyRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = _get_student_with_application(student_id, db)
    student.application.is_verified = payload.verified
    student.application.verified_at = utc_now() if payload.verified else None
    db.add(student.application)
    db.commit()
    return GenericMessageResponse(
        message="Application verified successfully." if payload.verified else "Application moved back to pending verification."
    )


@router.patch("/students/{student_id}/shortlist", response_model=GenericMessageResponse)
def shortlist_student(
    student_id: int,
    payload: AdminShortlistRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = _get_student_with_application(student_id, db)
    student.application.is_shortlisted = payload.shortlisted
    student.application.shortlisted_at = utc_now() if payload.shortlisted else None
    if not payload.shortlisted:
        student.application.allocated_hostel = None
        student.application.hostel_allocated_at = None
    db.add(student.application)
    db.commit()
    return GenericMessageResponse(
        message="Student shortlisted successfully." if payload.shortlisted else "Student removed from shortlist."
    )


@router.patch("/students/{student_id}/allocate-hostel", response_model=GenericMessageResponse)
def allocate_hostel(
    student_id: int,
    payload: AdminAllocationRequest,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = _get_student_with_application(student_id, db)
    if not student.application.is_shortlisted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student is not shortlisted yet.")

    previous_room = student.application.allocated_room
    if payload.room_id is not None:
        room = _get_room_or_404(payload.room_id, db)
        if not room.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected room is inactive.")

        refresh_room_occupancy(db, room)
        occupied_beds = room_total_occupied_beds(db, room, exclude_student_id=student.id)
        currently_assigned_here = student.application.allocated_room_id == room.id
        if occupied_beds >= room.bed_capacity and not currently_assigned_here:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected room is already full.")

        bed_number = (
            _validate_bed_number(room, payload.bed_number)
            if payload.bed_number
            else _next_available_bed(db, room, ignore_student_id=student.id)
        )
        if not bed_number:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No bed is available in the selected room.")

        if bed_number in _occupied_room_beds(db, room, ignore_student_id=student.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Selected bed is already occupied.")

        student.application.allocated_hostel = room.hostel_name
        student.application.allocated_room_id = room.id
        student.application.bed_number = bed_number
    else:
        if not payload.hostel_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide either a room selection or a hostel name.",
            )
        student.application.allocated_hostel = ensure_valid_hostel_name(payload.hostel_name)
        student.application.allocated_room_id = None
        student.application.bed_number = normalize_bed_number(payload.bed_number)

    student.application.hostel_allocated_at = utc_now()
    db.add(student.application)
    db.commit()
    if payload.room_id:
        room = _get_room_or_404(payload.room_id, db)
        update_room_occupancy(db, room)
        if previous_room and previous_room.id != room.id:
            update_room_occupancy(db, previous_room)
        # Log activity
        log = ActivityLog(
            entity_type="student",
            entity_id=str(student.id),
            action="allocate_room",
            new_values=f"Room {room.id}, Bed {bed_number or 'auto'}",
            admin_id=current_admin.id
        )
        db.add(log)
        db.commit()
    return GenericMessageResponse(message="Hostel allocated successfully.")


@router.delete("/students/{student_id}", response_model=GenericMessageResponse)
def delete_student_application(
    student_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = db.get(ERPStudent, student_id)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student record not found.")

    db.delete(student)
    db.commit()
    return GenericMessageResponse(message="Student record deleted successfully.")


@router.get("/hostel/rooms", response_model=HostelRoomListResponse)
def list_hostel_rooms(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> HostelRoomListResponse:
    rooms = list(db.scalars(_rooms_base_query()))
    for room in rooms:
        refresh_room_occupancy(db, room)
    items = [
        HostelRoomSummary(**build_room_summary(room))
        for room in sorted(rooms, key=lambda item: (item.hostel_name, item.block_name, item.room_number))
    ]
    return HostelRoomListResponse(total=len(items), items=items)


@router.post("/hostel/rooms", response_model=HostelRoomSummary, status_code=status.HTTP_201_CREATED)
def create_hostel_room(
    payload: AdminHostelRoomPayload,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> HostelRoomSummary:
    hostel_name = ensure_valid_hostel_name(payload.hostel_name)
    block_name = clean_text(payload.block_name)
    room_number = clean_text(payload.room_number)
    if not block_name or not room_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Block and room number are required.")
    if payload.bed_capacity < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bed capacity must be at least 1.")

    _ensure_room_identity_available(
        db=db,
        hostel_name=hostel_name,
        block_name=block_name,
        room_number=room_number,
    )

    room = ERPHostelRoom(
        hostel_name=hostel_name,
        block_name=block_name,
        room_number=room_number,
        bed_capacity=payload.bed_capacity,
        is_active=payload.is_active,
        notes=clean_text(payload.notes),
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    room = _get_room_or_404(room.id, db)
    refresh_room_occupancy(db, room)
    return HostelRoomSummary(**build_room_summary(room))


@router.patch("/hostel/rooms/{room_id}", response_model=HostelRoomSummary)
def update_hostel_room(
    room_id: int,
    payload: AdminHostelRoomPayload,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> HostelRoomSummary:
    room = _get_room_or_404(room_id, db)
    refresh_room_occupancy(db, room)
    hostel_name = ensure_valid_hostel_name(payload.hostel_name)
    block_name = clean_text(payload.block_name)
    room_number = clean_text(payload.room_number)
    if not block_name or not room_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Block and room number are required.")
    if payload.bed_capacity < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bed capacity must be at least 1.")

    occupied_beds = room.occupied_beds or 0
    if payload.bed_capacity < occupied_beds:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bed capacity cannot be less than the current occupancy.",
        )

    _ensure_room_identity_available(
        db=db,
        hostel_name=hostel_name,
        block_name=block_name,
        room_number=room_number,
        exclude_room_id=room.id,
    )

    room.hostel_name = hostel_name
    room.block_name = block_name
    room.room_number = room_number
    room.bed_capacity = payload.bed_capacity
    room.is_active = payload.is_active
    room.notes = clean_text(payload.notes)
    db.add(room)
    db.commit()
    db.refresh(room)
    room = _get_room_or_404(room.id, db)
    refresh_room_occupancy(db, room)
    return HostelRoomSummary(**build_room_summary(room))


def _student_lookup(db: Session) -> dict[str, ERPStudent]:
    students = list(db.scalars(_students_base_query()))
    return {
        (student.application_number or "").strip(): student
        for student in students
        if student.application_number
    }


async def _process_bulk_shortlist_upload(
    file: UploadFile,
    hostel_name: str | None,
    db: Session,
) -> BulkCombinedUploadResponse:
    dataframe = await _load_dataframe(file, empty_message="Upload file is empty.")
    normalized_columns = {str(column).strip().lower(): column for column in dataframe.columns}

    registration_column = _pick_column(
        normalized_columns,
        ["registration number", "registration_no", "registration_no.", "application number", "application no", "application_no", "application"],
        required=True,
    )
    shortlist_column = _pick_column(normalized_columns, ["shortlist status", "shortlist", "status"])
    allotted_column = _pick_column(normalized_columns, ["allotted category", "allotted_category", "allotted cat"])
    applied_column = _pick_column(normalized_columns, ["applied category", "applied_category"])
    hostel_column = _pick_column(normalized_columns, ["hostel name", "hostel"])
    block_column = _pick_column(normalized_columns, ["hostel block", "block", "block name"])
    room_column = _pick_column(normalized_columns, ["room number", "room no", "room"])
    bed_column = _pick_column(normalized_columns, ["bed number", "bed no", "bed"])

    bulk_hostel_name = clean_text(hostel_name)
    validated_default_hostel = None
    if bulk_hostel_name:
        try:
            validated_default_hostel = ensure_valid_hostel_name(bulk_hostel_name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    students_by_registration = _student_lookup(db)
    rooms = list(db.scalars(_rooms_base_query()))
    room_key_lookup = {
        (room.hostel_name.lower(), room.block_name.lower(), room.room_number.lower()): room for room in rooms
    }
    block_room_lookup: dict[tuple[str, str], list[ERPHostelRoom]] = {}
    for room in rooms:
        block_room_lookup.setdefault((room.block_name.lower(), room.room_number.lower()), []).append(room)

    room_assignments: dict[int, dict[str, int]] = {}
    for room in rooms:
        assignments = {
            normalize_bed_number(application.bed_number): application.student_id
            for application in room.applications
            if application.allocated_room_id == room.id and application.bed_number
        }
        room_assignments[room.id] = {bed: sid for bed, sid in assignments.items() if bed}

    processed_rows = len(dataframe.index)
    shortlisted_yes = 0
    shortlisted_no = 0
    updated_allotted_category = 0
    allocated = 0
    auto_assigned_beds = 0
    invalid_registrations = 0
    not_shortlisted = 0
    room_errors = 0
    skipped_rows = 0
    processed_at = utc_now()

    for _, row in dataframe.iterrows():
        registration_number = clean_text(row[registration_column])
        if not registration_number:
            skipped_rows += 1
            continue

        student = students_by_registration.get(registration_number)
        application = student.application if student else None
        if not student or not application:
            invalid_registrations += 1
            continue

        shortlist_value = _parse_yes_no(row[shortlist_column]) if shortlist_column else None
        allotted_value = clean_text(row[allotted_column]) if allotted_column else None
        applied_value = clean_text(row[applied_column]) if applied_column else None
        target_allotted_category = allotted_value or applied_value

        target_block = clean_text(row[block_column]) if block_column else None
        target_room_number = clean_text(row[room_column]) if room_column else None
        target_bed_value = clean_text(row[bed_column]) if bed_column else None
        target_hostel_name = clean_text(row[hostel_column]) if hostel_column else None
        target_hostel_name = target_hostel_name or validated_default_hostel
        has_allocation_fields = bool(target_block and target_room_number)

        if shortlist_value is None and target_allotted_category is None and not has_allocation_fields:
            skipped_rows += 1
            continue

        if shortlist_value is True:
            if not application.is_shortlisted:
                shortlisted_yes += 1
            application.is_shortlisted = True
            application.shortlisted_at = application.shortlisted_at or processed_at
            if target_hostel_name:
                application.allocated_hostel = target_hostel_name
                application.hostel_allocated_at = application.hostel_allocated_at or processed_at
        elif shortlist_value is False:
            if application.is_shortlisted:
                shortlisted_no += 1
            application.is_shortlisted = False
            application.shortlisted_at = None
            application.allocated_hostel = None
            application.allocated_room_id = None
            application.bed_number = None
            application.hostel_allocated_at = None

        if target_allotted_category:
            trimmed_category = target_allotted_category[:20]
            if trimmed_category != application.allotted_category:
                updated_allotted_category += 1
            application.allotted_category = trimmed_category
        elif not application.allotted_category and application.category:
            application.allotted_category = application.category

        if has_allocation_fields:
            if not application.is_shortlisted:
                not_shortlisted += 1
                db.add(application)
                continue

            try:
                validated_hostel = ensure_valid_hostel_name(target_hostel_name) if target_hostel_name else None
            except ValueError:
                room_errors += 1
                db.add(application)
                continue

            candidate_room: ERPHostelRoom | None = None
            if validated_hostel:
                candidate_room = room_key_lookup.get((validated_hostel.lower(), target_block.lower(), target_room_number.lower()))
            else:
                candidates = block_room_lookup.get((target_block.lower(), target_room_number.lower()), [])
                if len(candidates) == 1:
                    candidate_room = candidates[0]
                elif len(candidates) > 1:
                    room_errors += 1
                    db.add(application)
                    continue

            if not candidate_room or not candidate_room.is_active:
                room_errors += 1
                db.add(application)
                continue

            previous_room_id = application.allocated_room_id
            previous_bed = normalize_bed_number(application.bed_number)
            if previous_room_id and previous_room_id in room_assignments and previous_bed:
                if room_assignments[previous_room_id].get(previous_bed) == student.id:
                    room_assignments[previous_room_id].pop(previous_bed, None)

            room_assignment = room_assignments.setdefault(candidate_room.id, {})
            if len(room_assignment) >= candidate_room.bed_capacity and target_bed_value is None:
                room_errors += 1
                db.add(application)
                continue

            bed_number = None
            if target_bed_value:
                try:
                    bed_number = _validate_bed_number(candidate_room, target_bed_value)
                except HTTPException:
                    room_errors += 1
                    db.add(application)
                    continue
            else:
                for index in range(1, candidate_room.bed_capacity + 1):
                    candidate_bed = f"B{index}"
                    if candidate_bed not in room_assignment:
                        bed_number = candidate_bed
                        auto_assigned_beds += 1
                        break

            if not bed_number:
                room_errors += 1
                db.add(application)
                continue

            existing_student_id = room_assignment.get(bed_number)
            if existing_student_id and existing_student_id != student.id:
                room_errors += 1
                db.add(application)
                continue
            if bed_number not in room_assignment and len(room_assignment) >= candidate_room.bed_capacity:
                room_errors += 1
                db.add(application)
                continue

            room_assignment[bed_number] = student.id
            application.allocated_hostel = candidate_room.hostel_name
            application.allocated_room_id = candidate_room.id
            application.bed_number = bed_number
            application.hostel_allocated_at = processed_at
            allocated += 1

        db.add(application)

    db.commit()

    return BulkCombinedUploadResponse(
        message="Shortlist and allocation processed successfully.",
        processed_rows=processed_rows,
        shortlisted_yes=shortlisted_yes,
        shortlisted_no=shortlisted_no,
        updated_allotted_category=updated_allotted_category,
        allocated=allocated,
        auto_assigned_beds=auto_assigned_beds,
        invalid_registrations=invalid_registrations,
        not_shortlisted=not_shortlisted,
        room_errors=room_errors,
        skipped_rows=skipped_rows,
    )


def _combined_template_response(students: list[ERPStudent], *, filename: str) -> StreamingResponse:
    records: list[dict[str, object | None]] = []
    for student in students:
        application = student.application
        if not application or application.form_status != "submitted":
            continue
        allocated_room = application.allocated_room
        records.append(
            {
                "Registration Number": student.application_number,
                "Student Name": application.name,
                "Applied Category": application.category,
                "Allotted Category": application.allotted_category or application.category,
                "Shortlist Status": "YES" if application.is_shortlisted else "NO",
                "Hostel Name": application.allocated_hostel,
                "Hostel Block": allocated_room.block_name if allocated_room else None,
                "Room Number": allocated_room.room_number if allocated_room else None,
                "Bed Number": application.bed_number,
            }
        )

    dataframe = pd.DataFrame(records or [{"Message": "No submitted applications found."}])
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Hostel Bulk")
    output.seek(0)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/bulk/shortlist/template")
def download_bulk_shortlist_template(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> StreamingResponse:
    students = list(db.scalars(_students_base_query()))
    return _combined_template_response(
        students,
        filename=f"hostel_bulk_template_{utc_now().date()}.xlsx",
    )


@router.post("/bulk/shortlist/upload", response_model=BulkCombinedUploadResponse)
async def bulk_upload_shortlist(
    file: UploadFile = File(...),
    hostel_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> BulkCombinedUploadResponse:
    return await _process_bulk_shortlist_upload(file=file, hostel_name=hostel_name, db=db)


@router.post("/upload-shortlist", response_model=BulkCombinedUploadResponse)
async def upload_shortlist(
    file: UploadFile = File(...),
    hostel_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> BulkCombinedUploadResponse:
    return await _process_bulk_shortlist_upload(file=file, hostel_name=hostel_name, db=db)


async def _process_bulk_allocation_upload(
    file: UploadFile,
    hostel_name: str | None,
    db: Session,
) -> BulkCombinedUploadResponse:
    return await _process_bulk_shortlist_upload(file=file, hostel_name=hostel_name, db=db)


@router.get("/bulk/allocation/template")
def download_bulk_allocation_template(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> StreamingResponse:
    students = list(db.scalars(_students_base_query()))
    return _combined_template_response(
        students,
        filename=f"hostel_bulk_template_{utc_now().date()}_allocation.xlsx",
    )


@router.post("/bulk/allocation/upload", response_model=BulkCombinedUploadResponse)
async def bulk_upload_allocation(
    file: UploadFile = File(...),
    hostel_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> BulkCombinedUploadResponse:
    return await _process_bulk_allocation_upload(file=file, hostel_name=hostel_name, db=db)


@router.get("/export-excel")
def export_students_excel(
    search: str = Query(default=""),
    course: str | None = Query(default=None),
    category: str | None = Query(default=None),
    session: str | None = Query(default=None),
    program: str | None = Query(default=None),
    shortlist: str | None = Query(default=None),
    verified: str | None = Query(default=None),
    hostel_state: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> StreamingResponse:
    students = list(db.scalars(_students_base_query()))
    filtered = _filter_students_by_query(
        students,
        search=search,
        course=course,
        category=category,
        session=session,
        program=program,
        shortlist=shortlist,
        verified=verified,
        hostel_state=hostel_state,
    )
    records: list[dict[str, object | None]] = []
    for student in filtered:
        if not student.application:
            continue
        app = student.application
        records.append(
            {
                "Application Number": student.application_number,
                "Student Name": app.name,
                "Email": student.email,
                "Mobile Number": student.mobile_number,
                "Course Name": app.course_name,
                "Category": app.category,
                "Allotted Category": app.allotted_category or app.category,
                "Session": app.session,
                "Program": app.program,
                "Form Status": app.form_status,
                "Verification Status": verification_status(app),
                "Application Payment Status": application_payment_status(app),
                "Shortlist Status": shortlist_status(app),
                "Preferred Hostel": app.preferred_hostel,
                "Allocated Hostel": app.allocated_hostel,
                "Hostel Status": hostel_status(app),
            }
        )

    dataframe = pd.DataFrame(records or [{"Message": "No records available"}])
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Hostel ERP")
    output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="hostel_erp_students.xlsx"',
    }
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
