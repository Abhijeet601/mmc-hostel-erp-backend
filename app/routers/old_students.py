from __future__ import annotations

import json
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import get_current_admin
from ..erp_models import ERPApplication, ERPHostelRoom, ERPStudent
from ..erp_schemas import (
    BulkOldStudentIdPreview,
    BulkOldStudentRowResult,
    BulkUpsertOldStudentsResponse,
    GenericMessageResponse,
    OldStudentBase,
    OldStudentCreate,
    OldStudentListResponse,
    OldStudentResponse,
    OldStudentUpdate,
)
from ..erp_security import generate_random_password, hash_password
from ..services.erp_service import (
    build_old_student_summary,
    clean_text,
    normalize_bed_number,
    refresh_room_occupancy,
    utc_now,
    validate_old_student_allocation,
)
from ..utils.file_storage import save_upload_file_bytes

router = APIRouter(tags=["old-students"])

VISIBLE_BULK_FIELDS = ("name", "email", "course", "category", "hostel", "block", "room", "bed", "hostel_id")


def _ensure_old_student_application(student: ERPStudent, db: Session) -> ERPApplication:
    if student.application:
        return student.application
    application = ERPApplication(student=student, form_status="submitted")
    db.add(application)
    return application


def _apply_old_student_payload(student: ERPStudent, payload: OldStudentBase, db: Session) -> None:
    application = _ensure_old_student_application(student, db)
    application.name = payload.student_name
    application.email = payload.email or student.email
    application.mobile_number = payload.mobile_number
    application.admission_application_id = payload.admission_id
    application.roll_number = payload.roll_number
    application.course_name = payload.course_name
    application.session = payload.session
    application.category = payload.category

    if payload.email:
        student.email = payload.email
    student.mobile_number = payload.mobile_number
    student.old_student_status = payload.old_student_status
    student.hostel_name = payload.hostel_name
    student.block_name = payload.block_name
    student.room_number = payload.room_number
    student.bed_number = payload.bed_number


def _apply_old_student_updates(student: ERPStudent, updates: dict[str, object | None], db: Session) -> None:
    application = _ensure_old_student_application(student, db)
    if updates.get("student_name") is not None:
        application.name = updates["student_name"]
    if updates.get("email") is not None:
        application.email = updates["email"]
        student.email = updates["email"]
    if updates.get("course_name") is not None:
        application.course_name = updates["course_name"]
    if updates.get("category") is not None:
        application.category = updates["category"]
    if updates.get("session") is not None:
        application.session = updates["session"]
    if updates.get("admission_id") is not None:
        application.admission_application_id = updates["admission_id"]
    if updates.get("roll_number") is not None:
        application.roll_number = updates["roll_number"]
    if updates.get("mobile_number") is not None:
        application.mobile_number = updates["mobile_number"]
        student.mobile_number = updates["mobile_number"]
    if updates.get("old_student_status") is not None:
        student.old_student_status = updates["old_student_status"]
    if updates.get("hostel_name") is not None:
        student.hostel_name = updates["hostel_name"]
    if updates.get("block_name") is not None:
        student.block_name = updates["block_name"]
    if updates.get("room_number") is not None:
        student.room_number = updates["room_number"]
    if updates.get("bed_number") is not None:
        student.bed_number = updates["bed_number"]


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


def _normalize_room_key(hostel_name: str | None, block_name: str | None, room_number: str | None) -> tuple[str, str, str] | None:
    if not hostel_name or not block_name or not room_number:
        return None
    return (hostel_name.strip().lower(), block_name.strip().lower(), room_number.strip().lower())


def _normalize_email(value: object | None) -> str | None:
    normalized = clean_text(value)
    return normalized.lower() if normalized else None


def _current_year_prefix() -> str:
    return str(datetime.now().year)


def _parse_existing_sequence(hostel_id: str | None, prefix: str) -> int | None:
    if not hostel_id:
        return None
    normalized = hostel_id.strip()
    if not normalized.startswith(prefix):
        return None
    remainder = normalized[len(prefix) :]
    return int(remainder) if remainder.isdigit() else None


def _latest_hostel_id(existing_ids: set[str], prefix: str) -> str | None:
    last_hostel_id = None
    last_sequence = 0
    for hostel_id in existing_ids:
        sequence = _parse_existing_sequence(hostel_id, prefix)
        if sequence is not None and sequence >= last_sequence:
            last_sequence = sequence
            last_hostel_id = hostel_id
    return last_hostel_id


def _next_old_student_sequence(existing_ids: set[str], prefix: str) -> int:
    latest_hostel_id = _latest_hostel_id(existing_ids, prefix)
    latest_sequence = _parse_existing_sequence(latest_hostel_id, prefix) if latest_hostel_id else None
    return (latest_sequence or 0) + 1


def _default_session() -> str:
    year = datetime.now().year
    return f"{year}-{str(year + 1)[-2:]}"


def _snapshot_old_student(student: ERPStudent | None) -> dict[str, str | None]:
    if not student:
        return {field: None for field in VISIBLE_BULK_FIELDS}
    application = student.application
    return {
        "name": clean_text(application.name if application else None) or student.application_number,
        "email": student.email,
        "course": clean_text(application.course_name if application else None),
        "category": clean_text(application.category if application else None),
        "hostel": clean_text(student.hostel_name),
        "block": clean_text(student.block_name),
        "room": clean_text(student.room_number),
        "bed": normalize_bed_number(student.bed_number) or clean_text(student.bed_number),
        "hostel_id": student.application_number,
    }


def _next_generated_mobile(used_mobile_numbers: set[str]) -> str:
    candidate = 9000000000
    while True:
        mobile_number = str(candidate)
        if mobile_number not in used_mobile_numbers:
            used_mobile_numbers.add(mobile_number)
            return mobile_number
        candidate += 1


def _normalize_bulk_row(raw_row: dict[str, object | None], index: int) -> dict[str, object | None]:
    normalized_row = {str(key).strip().lower(): value for key, value in raw_row.items()}
    return {
        "row_number": int(normalized_row.get("row_number") or normalized_row.get("__row_number") or index + 2),
        "name": clean_text(
            normalized_row.get("name")
            or normalized_row.get("student name")
            or normalized_row.get("student_name")
        ),
        "email": _normalize_email(normalized_row.get("email")),
        "course": clean_text(normalized_row.get("course") or normalized_row.get("course name") or normalized_row.get("course_name")),
        "category": clean_text(normalized_row.get("category")),
        "hostel": clean_text(normalized_row.get("hostel") or normalized_row.get("hostel name") or normalized_row.get("hostel_name")),
        "block": clean_text(normalized_row.get("block") or normalized_row.get("block name") or normalized_row.get("block_name")),
        "room": clean_text(normalized_row.get("room") or normalized_row.get("room number") or normalized_row.get("room_number")),
        "bed": normalize_bed_number(
            normalized_row.get("bed") or normalized_row.get("bed number") or normalized_row.get("bed_number")
        )
        or clean_text(normalized_row.get("bed") or normalized_row.get("bed number") or normalized_row.get("bed_number")),
        "hostel_id": clean_text(
            normalized_row.get("hostel id") or normalized_row.get("hostel_id") or normalized_row.get("hostelid")
        ),
        "session": clean_text(normalized_row.get("session")),
        "mobile_number": clean_text(normalized_row.get("mobile") or normalized_row.get("mobile number") or normalized_row.get("mobile_number")),
        "old_student_status": clean_text(normalized_row.get("status") or normalized_row.get("old_student_status")) or "ACTIVE",
        "admission_id": clean_text(normalized_row.get("admission id") or normalized_row.get("admission_id")),
        "roll_number": clean_text(normalized_row.get("roll number") or normalized_row.get("roll_number")),
    }


async def _load_bulk_rows(file: UploadFile | None, rows_json: str | None) -> list[dict[str, object | None]]:
    if rows_json:
        try:
            parsed_rows = json.loads(rows_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rows_json must be a valid JSON array.",
            ) from exc
        if not isinstance(parsed_rows, list) or not all(isinstance(item, dict) for item in parsed_rows):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rows_json must be a JSON array of row objects.",
            )
        return [{str(key): value for key, value in row.items()} for row in parsed_rows]

    if file is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either an Excel file or rows_json.",
        )

    dataframe = await _load_dataframe(file)
    return [
        {str(key).strip(): value for key, value in row.items()}
        for row in dataframe.to_dict(orient="records")
    ]


def _build_error_row(row_number: int, values: dict[str, str | None], messages: list[str]) -> dict[str, object | None]:
    return {
        "row_number": row_number,
        **values,
        "errors": messages,
    }


def _coerce_bool(value: object | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _build_bulk_plan(
    db: Session,
    rows: list[dict[str, object | None]],
    *,
    generate_ids: bool,
    update_existing: bool,
    allocate_rooms: bool,
    overwrite_hostel_id: bool,
) -> dict[str, object]:
    students = list(
        db.scalars(
            select(ERPStudent).options(selectinload(ERPStudent.application))
        )
    )
    rooms = list(
        db.scalars(
            select(ERPHostelRoom).options(selectinload(ERPHostelRoom.applications))
        )
    )

    old_students_by_email: dict[str, ERPStudent] = {}
    old_students_by_hostel_id: dict[str, ERPStudent] = {}
    any_students_by_email: dict[str, ERPStudent] = {}
    any_students_by_hostel_id: dict[str, ERPStudent] = {}
    existing_hostel_ids = {student.application_number for student in students if student.application_number}
    used_mobile_numbers = {student.mobile_number for student in students if student.mobile_number}

    room_lookup: dict[tuple[str, str, str], ERPHostelRoom] = {}
    occupancy_map: dict[int, set[str]] = {}
    old_student_slots: dict[int, tuple[int, str]] = {}

    for room in rooms:
        room_lookup[(room.hostel_name.lower(), room.block_name.lower(), room.room_number.lower())] = room
        occupancy_map[room.id] = set()
        for application in room.applications:
            if application.allocated_hostel and application.allocated_room_id == room.id:
                occupancy_map[room.id].add(
                    normalize_bed_number(application.bed_number) or f"APP-{application.student_id}"
                )

    for student in students:
        if student.email:
            any_students_by_email[student.email.lower()] = student
        if student.application_number:
            any_students_by_hostel_id[student.application_number.lower()] = student

        if not student.is_old_student:
            continue

        old_students_by_email[student.email.lower()] = student
        old_students_by_hostel_id[student.application_number.lower()] = student
        room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
        if room_key and room_key in room_lookup:
            room = room_lookup[room_key]
            slot = normalize_bed_number(student.bed_number) or f"OLD-{student.id}"
            occupancy_map[room.id].add(slot)
            old_student_slots[student.id] = (room.id, slot)

    current_year_prefix = _current_year_prefix()
    next_sequence = _next_old_student_sequence(existing_hostel_ids, current_year_prefix)
    last_hostel_id = _latest_hostel_id(existing_hostel_ids, current_year_prefix)

    reserved_emails: set[str] = set()
    reserved_hostel_ids: set[str] = set()
    processed_existing_ids: set[int] = set()

    row_results: list[BulkOldStudentRowResult] = []
    plans: list[dict[str, object]] = []
    error_rows: list[dict[str, object | None]] = []
    preview_created = 0
    preview_updated = 0
    preview_errors = 0
    preview_generated_ids = 0
    preview_allocated = 0
    preview_next_ids: list[str] = []

    for index, raw_row in enumerate(rows):
        normalized_row = _normalize_bulk_row(raw_row, index)
        row_number = int(normalized_row["row_number"])
        current_values = {field: None for field in VISIBLE_BULK_FIELDS}
        proposed_values = {field: None for field in VISIBLE_BULK_FIELDS}
        messages: list[str] = []
        row_errors: list[str] = []
        matched_by: str | None = None
        generated_hostel_id = False
        allocation_updated = False
        action = "create"

        email = normalized_row["email"]
        hostel_id = normalized_row["hostel_id"]
        email_match = old_students_by_email.get(email) if email else None
        hostel_id_match = old_students_by_hostel_id.get(hostel_id.lower()) if hostel_id else None

        if email_match and hostel_id_match and email_match.id != hostel_id_match.id:
            row_errors.append("Email and hostel ID point to different students.")

        existing_student = email_match or hostel_id_match
        if email_match and hostel_id_match:
            matched_by = "email+hostel_id"
        elif email_match:
            matched_by = "email"
        elif hostel_id_match:
            matched_by = "hostel_id"

        if existing_student:
            current_values = _snapshot_old_student(existing_student)
            if existing_student.id in processed_existing_ids:
                row_errors.append("The same existing student appears more than once in this upload.")
        else:
            generic_email_match = any_students_by_email.get(email) if email else None
            generic_hostel_match = any_students_by_hostel_id.get(hostel_id.lower()) if hostel_id else None
            if generic_email_match and not generic_email_match.is_old_student:
                row_errors.append("Email already belongs to another student record.")
            if generic_hostel_match and not generic_hostel_match.is_old_student:
                row_errors.append("Hostel ID already belongs to another student record.")

        if existing_student and not update_existing:
            row_errors.append("Row matches an existing student but update_existing is disabled.")

        if not existing_student and not email:
            row_errors.append("Email is required for new students.")
        if not existing_student and not normalized_row["name"]:
            row_errors.append("Name is required for new students.")
        if not existing_student and not normalized_row["course"]:
            row_errors.append("Course is required for new students.")

        final_hostel_id = current_values["hostel_id"] if existing_student else hostel_id
        if not final_hostel_id:
            if generate_ids:
                while True:
                    candidate = f"{current_year_prefix}{next_sequence:06d}"
                    next_sequence += 1
                    if candidate not in existing_hostel_ids and candidate.lower() not in reserved_hostel_ids:
                        final_hostel_id = candidate
                        generated_hostel_id = True
                        preview_generated_ids += 1
                        if len(preview_next_ids) < 5:
                            preview_next_ids.append(candidate)
                        messages.append(f"Hostel ID {candidate} will be generated.")
                        break
            else:
                row_errors.append("Hostel ID is missing and generate_ids is disabled.")
        elif existing_student and not overwrite_hostel_id and hostel_id and hostel_id != current_values["hostel_id"]:
            messages.append("Provided hostel ID was ignored because overwrite_hostel_id is disabled.")
            final_hostel_id = current_values["hostel_id"]

        final_email = email or current_values["email"]
        if final_email:
            conflicting_email_student = any_students_by_email.get(final_email.lower())
            if conflicting_email_student and conflicting_email_student.id != (existing_student.id if existing_student else None):
                row_errors.append("Duplicate email conflict with an existing student.")
            if final_email.lower() in reserved_emails:
                row_errors.append("Duplicate email found within this upload.")

        if final_hostel_id:
            conflicting_hostel_student = any_students_by_hostel_id.get(final_hostel_id.lower())
            if conflicting_hostel_student and conflicting_hostel_student.id != (existing_student.id if existing_student else None):
                row_errors.append("Hostel ID conflicts with an existing student.")
            if final_hostel_id.lower() in reserved_hostel_ids:
                row_errors.append("Duplicate hostel ID found within this upload.")

        proposed_values = dict(current_values)
        proposed_values["name"] = normalized_row["name"] or current_values["name"]
        proposed_values["email"] = final_email
        proposed_values["course"] = normalized_row["course"] or current_values["course"]
        proposed_values["category"] = normalized_row["category"] or current_values["category"]
        proposed_values["hostel_id"] = final_hostel_id

        requested_allocation_change = any(
            normalized_row.get(field) for field in ("hostel", "block", "room", "bed")
        )
        if not row_errors and allocate_rooms and requested_allocation_change:
            target_hostel = normalized_row["hostel"] or current_values["hostel"]
            target_block = normalized_row["block"] or current_values["block"]
            target_room = normalized_row["room"] or current_values["room"]
            if not all([target_hostel, target_block, target_room]):
                row_errors.append("Hostel, block, and room are required for room allocation.")
            else:
                room_key = _normalize_room_key(target_hostel, target_block, target_room)
                room = room_lookup.get(room_key) if room_key else None
                if not room or not room.is_active:
                    row_errors.append("Invalid room selection.")
                else:
                    current_slot = old_student_slots.get(existing_student.id) if existing_student else None
                    occupied_slots = set(occupancy_map[room.id])
                    if current_slot and current_slot[0] == room.id:
                        occupied_slots.discard(current_slot[1])

                    target_bed = normalize_bed_number(normalized_row["bed"])
                    current_room_key = _normalize_room_key(
                        current_values["hostel"],
                        current_values["block"],
                        current_values["room"],
                    )
                    if (
                        not target_bed
                        and current_slot
                        and room_key == current_room_key
                        and current_values["bed"]
                    ):
                        target_bed = normalize_bed_number(current_values["bed"])

                    if target_bed and target_bed in occupied_slots:
                        row_errors.append("Selected bed is already occupied.")
                    elif len(occupied_slots) >= room.bed_capacity and not target_bed:
                        row_errors.append("Room is full.")
                    else:
                        if not target_bed:
                            for bed_index in range(1, room.bed_capacity + 1):
                                candidate_bed = f"B{bed_index}"
                                if candidate_bed not in occupied_slots:
                                    target_bed = candidate_bed
                                    messages.append(f"Bed {candidate_bed} will be auto-assigned.")
                                    break
                        if not target_bed:
                            row_errors.append("No bed is available in the selected room.")
                        else:
                            if current_slot:
                                occupancy_map[current_slot[0]].discard(current_slot[1])
                            occupancy_map[room.id].add(target_bed)
                            if existing_student:
                                old_student_slots[existing_student.id] = (room.id, target_bed)
                            proposed_values["hostel"] = room.hostel_name
                            proposed_values["block"] = room.block_name
                            proposed_values["room"] = room.room_number
                            proposed_values["bed"] = target_bed
                            allocation_updated = True
                            preview_allocated += 1
        elif requested_allocation_change and not row_errors:
            messages.append("Room allocation fields were ignored because allocate_rooms is disabled.")

        changed_fields = [
            field
            for field in VISIBLE_BULK_FIELDS
            if proposed_values.get(field) != current_values.get(field)
        ]

        if row_errors:
            preview_errors += 1
            row_results.append(
                BulkOldStudentRowResult(
                    row_number=row_number,
                    action="error",
                    matched_by=matched_by,
                    changed_fields=[],
                    generated_hostel_id=generated_hostel_id,
                    allocation_updated=False,
                    messages=row_errors,
                    current_values=current_values,
                    proposed_values=proposed_values,
                )
            )
            error_rows.append(_build_error_row(row_number, proposed_values, row_errors))
            continue

        if not changed_fields and existing_student:
            action = "no_change"
            messages.append("No changes detected for this row.")
        elif existing_student:
            action = "update"
            preview_updated += 1
            processed_existing_ids.add(existing_student.id)
            messages.append(f"Existing student matched by {matched_by or 'hostel_id'} and will be updated.")
        else:
            action = "create"
            preview_created += 1
            messages.append("New old student record will be created.")

        if final_email:
            reserved_emails.add(final_email.lower())
        if final_hostel_id:
            reserved_hostel_ids.add(final_hostel_id.lower())

        row_results.append(
            BulkOldStudentRowResult(
                row_number=row_number,
                action=action,
                matched_by=matched_by,
                changed_fields=changed_fields,
                generated_hostel_id=generated_hostel_id,
                allocation_updated=allocation_updated,
                messages=messages,
                current_values=current_values,
                proposed_values=proposed_values,
            )
        )

        if action in {"create", "update"}:
            plans.append(
                {
                    "row_number": row_number,
                    "action": action,
                    "student_id": existing_student.id if existing_student else None,
                    "hostel_id": final_hostel_id,
                    "values": proposed_values,
                    "session": normalized_row["session"]
                    or (
                        existing_student.application.session
                        if existing_student and existing_student.application
                        else None
                    )
                    or _default_session(),
                    "mobile_number": normalized_row["mobile_number"]
                    or (existing_student.mobile_number if existing_student else None)
                    or _next_generated_mobile(used_mobile_numbers),
                    "old_student_status": normalized_row["old_student_status"]
                    or (existing_student.old_student_status if existing_student else None)
                    or "ACTIVE",
                    "admission_id": normalized_row["admission_id"]
                    or (
                        existing_student.application.admission_application_id
                        if existing_student and existing_student.application
                        else None
                    ),
                    "roll_number": normalized_row["roll_number"]
                    or (
                        existing_student.application.roll_number
                        if existing_student and existing_student.application
                        else None
                    ),
                }
            )

    return {
        "rows": row_results,
        "plans": plans,
        "total": len(rows),
        "created": preview_created,
        "updated": preview_updated,
        "errors": preview_errors,
        "generated_ids": preview_generated_ids,
        "allocated": preview_allocated,
        "error_rows": error_rows,
        "hostel_id_preview": BulkOldStudentIdPreview(
            last_id=last_hostel_id,
            next_ids=preview_next_ids,
            generated_count=preview_generated_ids,
        ),
    }


def _apply_bulk_upsert_plan(db: Session, plan: dict[str, object]) -> tuple[str, ERPStudent]:
    values = plan["values"]
    action = str(plan["action"])

    if action == "create":
        student = ERPStudent(
            application_number=str(plan["hostel_id"]),
            hostel_id=str(plan["hostel_id"]),
            email=str(values["email"]),
            date_of_birth=date.today(),
            mobile_number=str(plan["mobile_number"]),
            password_hash=hash_password(generate_random_password()),
            is_old_student=True,
            old_student_status=str(plan["old_student_status"]),
            hostel_name=values["hostel"],
            block_name=values["block"],
            room_number=values["room"],
            bed_number=values["bed"],
        )
        db.add(student)
        application = _ensure_old_student_application(student, db)
    else:
        student = db.get(ERPStudent, int(plan["student_id"]))
        if not student or not student.is_old_student:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Old student not found during bulk update.")
        student.email = str(values["email"])
        student.old_student_status = str(plan["old_student_status"])
        student.hostel_name = values["hostel"]
        student.block_name = values["block"]
        student.room_number = values["room"]
        student.bed_number = values["bed"]
        student.updated_at = utc_now()
        application = _ensure_old_student_application(student, db)

    student.mobile_number = str(plan["mobile_number"])
    application.name = values["name"]
    application.email = values["email"]
    application.course_name = values["course"]
    application.category = values["category"]
    application.session = str(plan["session"])
    application.mobile_number = str(plan["mobile_number"])
    application.admission_application_id = plan["admission_id"]
    application.roll_number = plan["roll_number"]

    db.add(student)
    db.commit()
    db.refresh(student)
    return action, student


def _build_error_report(error_rows: list[dict[str, object | None]]) -> str | None:
    if not error_rows:
        return None
    errors_df = pd.DataFrame(
        [
            {
                **{key: value for key, value in row.items() if key != "errors"},
                "errors": "; ".join(str(message) for message in row.get("errors", [])),
            }
            for row in error_rows
        ]
    )
    error_buffer = BytesIO()
    errors_df.to_excel(error_buffer, index=False, engine="openpyxl")
    error_buffer.seek(0)
    error_filename = f"old_students_bulk_errors_{uuid4().hex[:8]}.xlsx"
    error_path = save_upload_file_bytes(error_buffer, "uploads/error_reports", error_filename)
    return f"/uploads/error_reports/{Path(error_path).name}"


@router.get("/admin/old-students", response_model=OldStudentListResponse)
def list_old_students(
    search: str = Query(default=""),
    hostel_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> OldStudentListResponse:
    query = select(ERPStudent).outerjoin(ERPApplication).where(ERPStudent.is_old_student == True)

    if search:
        query = query.where(
            or_(
                ERPStudent.application_number.ilike(f"%{search}%"),
                ERPStudent.email.ilike(f"%{search}%"),
                ERPApplication.name.ilike(f"%{search}%"),
            )
        )
    if hostel_name:
        query = query.where(ERPStudent.hostel_name == hostel_name)
    if status:
        query = query.where(ERPStudent.old_student_status == status)

    query = query.order_by(ERPStudent.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = [build_old_student_summary(student) for student in db.scalars(query.limit(limit).offset(offset)).all()]
    return OldStudentListResponse(total=total, items=items)


@router.post("/admin/old-students", response_model=OldStudentResponse, status_code=status.HTTP_201_CREATED)
def create_old_student(
    payload: OldStudentCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> OldStudentResponse:
    existing = db.scalar(
        select(ERPStudent).where(
            or_(
                ERPStudent.application_number == payload.hostel_id,
                ERPStudent.email == (payload.email or f"{payload.hostel_id}@old.student"),
            )
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel ID or email already exists.")

    if payload.hostel_name and payload.block_name and payload.room_number:
        validate_old_student_allocation(
            db,
            payload.hostel_name,
            payload.block_name,
            payload.room_number,
            payload.bed_number,
        )

    student = ERPStudent(
        application_number=payload.hostel_id,
        hostel_id=payload.hostel_id,
        email=payload.email or f"{payload.hostel_id}@old.student",
        date_of_birth=date.today(),
        mobile_number=payload.mobile_number,
        password_hash=hash_password(generate_random_password()),
        is_old_student=True,
        old_student_status=payload.old_student_status,
        hostel_name=payload.hostel_name,
        block_name=payload.block_name,
        room_number=payload.room_number,
        bed_number=payload.bed_number,
    )
    db.add(student)
    _apply_old_student_payload(student, payload, db)
    db.commit()
    db.refresh(student)
    room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
    if room_key:
        room = db.scalar(
            select(ERPHostelRoom).where(
                func.lower(ERPHostelRoom.hostel_name) == room_key[0],
                func.lower(ERPHostelRoom.block_name) == room_key[1],
                func.lower(ERPHostelRoom.room_number) == room_key[2],
            )
        )
        if room:
            refresh_room_occupancy(db, room)
            db.commit()
    return OldStudentResponse(**build_old_student_summary(student))


@router.put("/admin/old-students/{student_id}", response_model=OldStudentResponse)
def update_old_student(
    student_id: int,
    payload: OldStudentUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> OldStudentResponse:
    student = db.get(ERPStudent, student_id)
    if not student or not student.is_old_student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Old student not found.")

    previous_room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
    if payload.hostel_name and payload.block_name and payload.room_number:
        validate_old_student_allocation(
            db,
            payload.hostel_name,
            payload.block_name,
            payload.room_number,
            payload.bed_number,
            student.id,
        )

    _apply_old_student_payload(student, payload, db)
    student.updated_at = utc_now()
    db.add(student)
    db.commit()
    db.refresh(student)
    next_room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
    for room_key in {previous_room_key, next_room_key}:
        if not room_key:
            continue
        room = db.scalar(
            select(ERPHostelRoom).where(
                func.lower(ERPHostelRoom.hostel_name) == room_key[0],
                func.lower(ERPHostelRoom.block_name) == room_key[1],
                func.lower(ERPHostelRoom.room_number) == room_key[2],
            )
        )
        if room:
            refresh_room_occupancy(db, room)
    db.commit()
    return OldStudentResponse(**build_old_student_summary(student))


@router.delete("/admin/old-students/{student_id}", response_model=GenericMessageResponse)
def delete_old_student(
    student_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> GenericMessageResponse:
    student = db.get(ERPStudent, student_id)
    if not student or not student.is_old_student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Old student not found.")
    previous_room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
    db.delete(student)
    db.commit()
    if previous_room_key:
        room = db.scalar(
            select(ERPHostelRoom).where(
                func.lower(ERPHostelRoom.hostel_name) == previous_room_key[0],
                func.lower(ERPHostelRoom.block_name) == previous_room_key[1],
                func.lower(ERPHostelRoom.room_number) == previous_room_key[2],
            )
        )
        if room:
            refresh_room_occupancy(db, room)
            db.commit()
    return GenericMessageResponse(message="Old student deleted successfully.")


@router.post("/bulk-upsert-old-students", response_model=BulkUpsertOldStudentsResponse)
async def bulk_upsert_old_students(
    request: Request,
    file: UploadFile | None = File(default=None),
    rows_json: str | None = Form(default=None),
    preview_only: bool = Form(default=True),
    generate_ids: bool = Form(default=True),
    update_existing: bool = Form(default=True),
    allocate_rooms: bool = Form(default=True),
    overwrite_hostel_id: bool = Form(default=False),
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
) -> BulkUpsertOldStudentsResponse:
    if file is None and rows_json is None and "application/json" in request.headers.get("content-type", "").lower():
        payload = await request.json()
        rows_json = json.dumps(payload.get("rows") or [])
        preview_only = _coerce_bool(payload.get("preview_only"), preview_only)
        generate_ids = _coerce_bool(payload.get("generate_ids"), generate_ids)
        update_existing = _coerce_bool(payload.get("update_existing"), update_existing)
        allocate_rooms = _coerce_bool(payload.get("allocate_rooms"), allocate_rooms)
        overwrite_hostel_id = _coerce_bool(payload.get("overwrite_hostel_id"), overwrite_hostel_id)

    rows = await _load_bulk_rows(file, rows_json)
    bulk_plan = _build_bulk_plan(
        db,
        rows,
        generate_ids=generate_ids,
        update_existing=update_existing,
        allocate_rooms=allocate_rooms,
        overwrite_hostel_id=overwrite_hostel_id,
    )

    if preview_only:
        error_report_url = _build_error_report(bulk_plan["error_rows"])
        return BulkUpsertOldStudentsResponse(
            mode="preview",
            message="Preview generated successfully.",
            total=bulk_plan["total"],
            created=bulk_plan["created"],
            updated=bulk_plan["updated"],
            errors=bulk_plan["errors"],
            success_count=bulk_plan["created"] + bulk_plan["updated"],
            update_count=bulk_plan["updated"],
            error_count=bulk_plan["errors"],
            generated_ids=bulk_plan["generated_ids"],
            allocated=bulk_plan["allocated"],
            error_rows=bulk_plan["error_rows"],
            error_details=bulk_plan["error_rows"],
            rows=bulk_plan["rows"],
            hostel_id_preview=bulk_plan["hostel_id_preview"],
            error_report_url=error_report_url,
        )

    created = 0
    updated = 0
    committed_error_rows = list(bulk_plan["error_rows"])
    row_results_by_number = {row.row_number: row for row in bulk_plan["rows"]}
    affected_room_keys: set[tuple[str, str, str]] = set()

    for plan in bulk_plan["plans"]:
        row_number = int(plan["row_number"])
        row_result = row_results_by_number[row_number]
        try:
            action, student = _apply_bulk_upsert_plan(db, plan)
            if action == "create":
                created += 1
            else:
                updated += 1
            row_result.messages.append("Changes committed successfully.")
            room_key = _normalize_room_key(student.hostel_name, student.block_name, student.room_number)
            if room_key:
                affected_room_keys.add(room_key)
        except IntegrityError:
            db.rollback()
            row_result.action = "error"
            row_result.messages = ["Database constraint failed while saving this row."]
            committed_error_rows.append(_build_error_row(row_number, row_result.proposed_values, row_result.messages))
        except HTTPException as exc:
            db.rollback()
            row_result.action = "error"
            row_result.messages = [str(exc.detail)]
            committed_error_rows.append(_build_error_row(row_number, row_result.proposed_values, row_result.messages))
        except Exception as exc:
            db.rollback()
            row_result.action = "error"
            row_result.messages = [str(exc)]
            committed_error_rows.append(_build_error_row(row_number, row_result.proposed_values, row_result.messages))

    for room_key in affected_room_keys:
        room = db.scalar(
            select(ERPHostelRoom).where(
                func.lower(ERPHostelRoom.hostel_name) == room_key[0],
                func.lower(ERPHostelRoom.block_name) == room_key[1],
                func.lower(ERPHostelRoom.room_number) == room_key[2],
            )
        )
        if room:
            refresh_room_occupancy(db, room)
    if affected_room_keys:
        db.commit()

    error_count = len(committed_error_rows)
    error_report_url = _build_error_report(committed_error_rows)
    return BulkUpsertOldStudentsResponse(
        mode="commit",
        message=f"Bulk upsert complete: {created} created, {updated} updated, {error_count} errors.",
        total=bulk_plan["total"],
        created=created,
        updated=updated,
        errors=error_count,
        success_count=created + updated,
        update_count=updated,
        error_count=error_count,
        generated_ids=sum(1 for row in row_results_by_number.values() if row.generated_hostel_id and row.action != "error"),
        allocated=sum(1 for row in row_results_by_number.values() if row.allocation_updated and row.action != "error"),
        error_rows=committed_error_rows,
        error_details=committed_error_rows,
        rows=list(row_results_by_number.values()),
        hostel_id_preview=bulk_plan["hostel_id_preview"],
        error_report_url=error_report_url,
    )
