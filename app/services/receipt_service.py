from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from reportlab.graphics.barcode import qr
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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


def _build_qr_value(payload: dict[str, object | None]) -> str:
    parts = [
        "Magadh Mahila College Hostel ERP",
        f"Application: {_clean_value(payload.get('application_number'))}",
        f"Cycle: {_clean_value(payload.get('cycle_reference'))}",
        f"Type: {_clean_value(payload.get('application_type'))}",
        f"Txn: {_clean_value(payload.get('transaction_id'))}",
    ]
    return " | ".join(parts)


def _photo_or_placeholder(photo_path: object | None) -> Table | Image:
    path = _clean_value(photo_path)
    if path != "-":
        absolute = (BASE_DIR / path).resolve()
        if absolute.exists():
            image = Image(str(absolute), width=28 * mm, height=34 * mm)
            return image
    table = Table([["PHOTO"]], colWidths=[28 * mm], rowHeights=[34 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#334155")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#475569")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _qr_block(payload: dict[str, object | None]) -> Table:
    code = qr.QrCodeWidget(_build_qr_value(payload))
    bounds = code.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    from reportlab.graphics.shapes import Drawing

    drawing = Drawing(28 * mm, 28 * mm, transform=[28 * mm / width, 0, 0, 28 * mm / height, 0, 0])
    drawing.add(code)
    block = Table([[drawing], [Paragraph("Scan for verification", ParagraphStyle("qr", fontSize=7, alignment=1, textColor=colors.HexColor("#475569")))]] , colWidths=[30 * mm])
    block.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return block


def _detail_table(rows: list[tuple[str, object | None]], label_style: ParagraphStyle, value_style: ParagraphStyle) -> Table:
    data = [
        [Paragraph(f"<b>{_clean_value(label)}</b>", label_style), Paragraph(_clean_value(value), value_style)]
        for label, value in rows
    ]
    table = Table(data, colWidths=[52 * mm, 94 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#1E3A8A")),
                ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#BFDBFE")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _build_receipt(
    *,
    filename_prefix: str,
    title: str,
    rows: list[tuple[str, object | None]],
    payload: dict[str, object | None],
) -> str:
    file_path = _receipt_dir() / f"{filename_prefix}_{uuid4().hex[:10]}.pdf"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=14, alignment=1, textColor=colors.HexColor("#0F172A"))
    sub_style = ParagraphStyle("sub", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=12, alignment=1, textColor=colors.HexColor("#334155"))
    label_style = ParagraphStyle("label", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8.2, textColor=colors.HexColor("#0F172A"))
    value_style = ParagraphStyle("value", parent=styles["Normal"], fontName="Helvetica", fontSize=8.4, leading=11, textColor=colors.HexColor("#1E293B"))
    note_style = ParagraphStyle("note", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#475569"))

    meta_rows = [
        ("Application No.", payload.get("application_number")),
        ("Application Type", "Hostel Renewal" if payload.get("application_type") == "renewal" else "New Registration"),
        ("Cycle Ref.", payload.get("cycle_reference")),
        ("Renewal Ref.", payload.get("renewal_reference_number")),
    ]

    doc = SimpleDocTemplate(str(file_path), pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=10 * mm, bottomMargin=12 * mm)
    story = []

    story.append(Paragraph("MAGADH MAHILA COLLEGE, PATNA UNIVERSITY", title_style))
    story.append(Paragraph("Hostel ERP Acknowledgement / Payment Receipt", sub_style))
    story.append(Paragraph(title, sub_style))
    story.append(Spacer(1, 4 * mm))

    hero = Table(
        [[
            _detail_table(meta_rows, label_style, value_style),
            Table([[_photo_or_placeholder(payload.get("student_photo_path"))], [_qr_block(payload)]], colWidths=[34 * mm]),
        ]],
        colWidths=[148 * mm, 34 * mm],
    )
    hero.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(hero)
    story.append(Spacer(1, 4 * mm))

    story.append(_detail_table(rows, label_style, value_style))
    story.append(Spacer(1, 4 * mm))

    signature = Table(
        [[
            Paragraph("Student Signature", note_style),
            Paragraph("Hostel Office Verification", note_style),
            Paragraph("Authorized Signature", note_style),
        ]],
        colWidths=[60 * mm, 60 * mm, 58 * mm],
        rowHeights=[16 * mm],
    )
    signature.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, -1), 0.65, colors.HexColor("#334155")),
                ("TOPPADDING", (0, 0), (-1, -1), 10 * mm),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(signature)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("This is a system-generated official hostel ERP receipt. Carry the printed copy during verification.", note_style))

    doc.build(story)
    return str(file_path.relative_to(BASE_DIR)).replace("\\", "/")


def generate_application_fee_receipt(*, payload: dict[str, object | None]) -> str:
    rows = [
        ("Student Name", payload.get("student_name")),
        ("Application Number", payload.get("application_number")),
        ("Renewal Reference", payload.get("renewal_reference_number")),
        ("Father Name", payload.get("father_name")),
        ("Mother Name", payload.get("mother_name")),
        ("Mobile Number", payload.get("mobile_number")),
        ("Email ID", payload.get("email")),
        ("Gender", payload.get("gender")),
        ("Category", payload.get("category")),
        ("Course", payload.get("course_name")),
        ("Honours Subject", payload.get("honours_subject")),
        ("Session", payload.get("session")),
        ("Payment Status", payload.get("payment_status")),
        ("Payment Mode", payload.get("payment_mode")),
        ("Transaction ID", payload.get("transaction_id")),
        ("Payment Date", payload.get("payment_date")),
        ("Paid Amount", payload.get("amount")),
    ]
    return _build_receipt(
        filename_prefix=f"application_fee_{payload.get('application_number', 'student')}",
        title="Application / Renewal Fee Receipt",
        rows=rows,
        payload=payload,
    )


def generate_hostel_receipt(*, payload: dict[str, object | None]) -> str:
    rows = [
        ("Student Name", payload.get("student_name")),
        ("Application Number", payload.get("application_number")),
        ("Renewal Reference", payload.get("renewal_reference_number")),
        ("Course Name", payload.get("course_name")),
        ("Program", payload.get("program")),
        ("Session", payload.get("session")),
        ("Roll Number", payload.get("roll_number")),
        ("Aadhaar Number", payload.get("aadhaar_number")),
        ("Blood Group", payload.get("blood_group")),
        ("Category", payload.get("category")),
        ("Religion", payload.get("religion")),
        ("Father Name", payload.get("father_name")),
        ("Guardian Name", payload.get("local_guardian_name")),
        ("Guardian Mobile", payload.get("guardian_mobile_number")),
        ("Address", payload.get("correspondence_address")),
        ("Hostel Name", payload.get("hostel_name")),
        ("Hostel Block", payload.get("hostel_block")),
        ("Room Number", payload.get("room_number")),
        ("Bed Number", payload.get("bed_number")),
        ("Payment Status", payload.get("payment_status")),
        ("Payment Mode", payload.get("payment_mode")),
        ("Payment Amount", payload.get("amount")),
        ("Transaction ID", payload.get("transaction_id")),
        ("Payment Date", payload.get("payment_date")),
    ]
    return _build_receipt(
        filename_prefix=f"hostel_fee_{payload.get('application_number', 'student')}",
        title="Hostel Allotment / Renewal Receipt",
        rows=rows,
        payload=payload,
    )
