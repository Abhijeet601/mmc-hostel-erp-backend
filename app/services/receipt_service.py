from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import settings

BASE_DIR = Path(__file__).resolve().parents[2]


def _receipt_dir() -> Path:
    target = BASE_DIR / settings.RECEIPT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _clean_value(value: object | None) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _build_receipt(
    *,
    filename_prefix: str,
    title: str,
    subtitle: str,
    rows: list[tuple[str, object | None]],
) -> str:
    file_path = _receipt_dir() / f"{filename_prefix}_{uuid4().hex[:10]}.pdf"
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle(
        "ReceiptHeading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )
    subheading_style = ParagraphStyle(
        "ReceiptSubheading",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        leading=14,
        spaceAfter=14,
    )
    value_style = ParagraphStyle(
        "ReceiptValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0F172A"),
    )
    label_style = ParagraphStyle(
        "ReceiptLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1E293B"),
    )

    table_data = [
        [
            Paragraph(f"<b>{_clean_value(label)}</b>", label_style),
            Paragraph(_clean_value(value), value_style),
        ]
        for label, value in rows
    ]

    table = Table(table_data, colWidths=[58 * mm, 120 * mm], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    story = [
        Paragraph("Magadh Mahila College", heading_style),
        Paragraph(title, heading_style),
        Paragraph(subtitle, subheading_style),
        Spacer(1, 6),
        table,
    ]
    doc.build(story)
    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")


def generate_application_fee_receipt(*, payload: dict[str, object | None]) -> str:
    rows = [
        ("Application Number", payload.get("application_number")),
        ("Student Name", payload.get("student_name")),
        ("Course", payload.get("course_name")),
        ("Session", payload.get("session")),
        ("Transaction ID", payload.get("transaction_id")),
        ("Payment Date", payload.get("payment_date")),
        ("Amount", payload.get("amount")),
    ]
    return _build_receipt(
        filename_prefix=f"application_fee_{payload.get('application_number', 'student')}",
        title="Application Fee Receipt",
        subtitle="Registration fee payment acknowledgement.",
        rows=rows,
    )


def generate_hostel_receipt(*, payload: dict[str, object | None]) -> str:
    rows = [
        ("Application Number", payload.get("application_number")),
        ("Student Name", payload.get("student_name")),
        ("Gender", payload.get("gender")),
        ("Date of Birth", payload.get("date_of_birth")),
        ("Mobile Number", payload.get("mobile_number")),
        ("Email", payload.get("email")),
        ("Blood Group", payload.get("blood_group")),
        ("Aadhaar Number", payload.get("aadhaar_number")),
        ("Category", payload.get("category")),
        ("Religion", payload.get("religion")),
        ("Nationality", payload.get("nationality")),
        ("Father Name", payload.get("father_name")),
        ("Mother Name", payload.get("mother_name")),
        ("Guardian Name", payload.get("local_guardian_name")),
        ("Guardian Mobile", payload.get("guardian_mobile_number")),
        ("Correspondence Address", payload.get("correspondence_address")),
        ("Admission Application ID", payload.get("admission_application_id")),
        ("College Name", payload.get("college_name")),
        ("Course Name", payload.get("course_name")),
        ("Honours Subject", payload.get("honours_subject")),
        ("Session", payload.get("session")),
        ("Program", payload.get("program")),
        ("Roll Number", payload.get("roll_number")),
        ("Hostel Name", payload.get("hostel_name")),
        ("Payment Amount", payload.get("amount")),
        ("Transaction ID", payload.get("transaction_id")),
        ("Payment Date", payload.get("payment_date")),
    ]
    return _build_receipt(
        filename_prefix=f"hostel_fee_{payload.get('application_number', 'student')}",
        title="Hostel Allocation Receipt",
        subtitle="Final hostel allotment payment receipt.",
        rows=rows,
    )
