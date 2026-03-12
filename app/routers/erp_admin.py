from __future__ import annotations

from collections import Counter
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_admin
from ..erp_models import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPStudent
from ..erp_schemas import (
    AdminAllocationRequest,
    AdminDashboardResponse,
    AdminStudentDetailResponse,
    AdminShortlistRequest,
    AdminStudentListResponse,
    AdminVerifyRequest,
    ChartDatum,
    GenericMessageResponse,
    ShortlistUploadResponse,
)
from ..services.erp_service import (
    application_payment_status,
    build_admin_student_detail,
    build_admin_student_summary,
    clean_text,
    current_application_status,
    ensure_valid_hostel_name,
    hostel_status,
    shortlist_status,
    utc_now,
    verification_status,
)

router = APIRouter(prefix="/admin", tags=["erp-admin"])


def _students_base_query():
    return select(ERPStudent).options(
        selectinload(ERPStudent.application).selectinload(ERPApplication.application_payments),
        selectinload(ERPStudent.application).selectinload(ERPApplication.hostel_payments),
    )


def _get_student_with_application(student_id: int, db: Session) -> ERPStudent:
    student = db.scalar(_students_base_query().where(ERPStudent.id == student_id))
    if not student or not student.application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student application not found.")
    return student


def _chart_data(counter: Counter[str]) -> list[ChartDatum]:
    return [ChartDatum(label=label, value=value) for label, value in counter.items() if label]


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> AdminDashboardResponse:
    students = list(db.scalars(_students_base_query()))
    applications = [student.application for student in students if student.application]
    application_payments = list(db.scalars(select(ERPApplicationPayment)))
    hostel_payments = list(db.scalars(select(ERPHostelPayment)))

    by_course = Counter(app.course_name or "Unassigned" for app in applications)
    by_category = Counter(app.category or "Unassigned" for app in applications)
    by_status = Counter(current_application_status(app) for app in applications)
    by_hostel = Counter(app.allocated_hostel or "Pending" for app in applications if app.is_shortlisted)

    return AdminDashboardResponse(
        total_applications=sum(1 for app in applications if app.form_status == "submitted"),
        total_paid=sum(1 for app in applications if application_payment_status(app) == "paid"),
        pending_applications=sum(1 for app in applications if app.form_status == "submitted" and not app.is_verified),
        shortlisted_students=sum(1 for app in applications if app.is_shortlisted),
        verified_students=sum(1 for app in applications if app.is_verified),
        hostel_allocated_students=sum(1 for app in applications if app.allocated_hostel),
        hostel_paid_students=len(hostel_payments),
        application_revenue=float(sum(float(payment.amount) for payment in application_payments)),
        hostel_revenue=float(sum(float(payment.amount) for payment in hostel_payments)),
        by_course=_chart_data(by_course),
        by_category=_chart_data(by_category),
        by_status=_chart_data(by_status),
        by_hostel=_chart_data(by_hostel),
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
    _=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = _get_student_with_application(student_id, db)
    if not student.application.is_shortlisted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Student is not shortlisted yet.")

    student.application.allocated_hostel = ensure_valid_hostel_name(payload.hostel_name)
    student.application.hostel_allocated_at = utc_now()
    db.add(student.application)
    db.commit()
    return GenericMessageResponse(message="Hostel allocated successfully.")


@router.post("/upload-shortlist", response_model=ShortlistUploadResponse)
async def upload_shortlist(
    file: UploadFile = File(...),
    hostel_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> ShortlistUploadResponse:
    bulk_hostel_name = clean_text(hostel_name)
    validated_hostel_name = ensure_valid_hostel_name(bulk_hostel_name) if bulk_hostel_name else None
    filename = (file.filename or "").lower()
    try:
        if filename.endswith(".csv"):
            dataframe = pd.read_csv(file.file)
        else:
            dataframe = pd.read_excel(file.file)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unable to parse shortlist file.") from exc
    finally:
        await file.close()

    if dataframe.empty:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Shortlist file is empty.")

    normalized_columns = {str(column).strip().lower(): column for column in dataframe.columns}
    preferred_columns = [
        "application_number",
        "application no",
        "application_no",
        "application",
    ]
    target_column = next((normalized_columns[key] for key in preferred_columns if key in normalized_columns), None)
    series = dataframe[target_column] if target_column is not None else dataframe.iloc[:, 0]

    application_numbers = {
        str(value).strip()
        for value in series.tolist()
        if value is not None and str(value).strip() and str(value).strip().lower() != "nan"
    }
    students = list(db.scalars(_students_base_query()))
    marked = 0
    allocated = 0
    matched = 0
    processed_at = utc_now()

    for student in students:
        app = student.application
        if not app:
            continue
        if student.application_number in application_numbers:
            matched += 1
            if not app.is_shortlisted:
                marked += 1
            app.is_shortlisted = True
            app.shortlisted_at = app.shortlisted_at or processed_at
            if validated_hostel_name:
                if app.allocated_hostel != validated_hostel_name or app.hostel_allocated_at is None:
                    allocated += 1
                app.allocated_hostel = validated_hostel_name
                app.hostel_allocated_at = processed_at
            db.add(app)

    db.commit()

    return ShortlistUploadResponse(
        message="Shortlist processed successfully.",
        marked_shortlisted=marked,
        allocated_hostel_count=allocated,
        allocated_hostel_name=validated_hostel_name,
        ignored_rows=max(len(application_numbers) - matched, 0),
        total_rows=len(application_numbers),
    )


@router.get("/export-excel")
def export_students_excel(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> StreamingResponse:
    students = list(db.scalars(_students_base_query()))
    records: list[dict[str, object | None]] = []
    for student in students:
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
