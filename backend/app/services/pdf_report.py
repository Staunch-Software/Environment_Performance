"""PDF report generation using ReportLab — A4 landscape."""
import uuid
from io import BytesIO
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from app.models.orb_upload import OrbUpload
from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.orb_alert import OrbAlert
from app.models.vessel import Vessel

PAGE_W, PAGE_H = landscape(A4)
NAVY = colors.HexColor("#1F4E79")
LIGHT_BLUE = colors.HexColor("#EBF3FB")
ORANGE = colors.HexColor("#FFA500")
RED = colors.HexColor("#FFE0E0")


def make_footer(vessel_name: str, imo: str):
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        footer_text = f"{vessel_name} | IMO: {imo} | Page {doc.page}"
        canvas.drawString(cm, 0.5 * cm, footer_text)
        canvas.restoreState()
    return _footer


async def generate_pdf(upload_id: uuid.UUID, db: AsyncSession) -> bytes:
    upload_result = await db.execute(select(OrbUpload).where(OrbUpload.id == upload_id))
    upload = upload_result.scalar_one_or_none()

    vessel_result = await db.execute(select(Vessel).where(Vessel.id == upload.vessel_id))
    vessel = vessel_result.scalar_one_or_none()

    entries_result = await db.execute(
        select(OrbEntry).where(OrbEntry.upload_id == upload_id).order_by(OrbEntry.entry_date)
    )
    entries = entries_result.scalars().all()

    alerts_result = await db.execute(
        select(OrbAlert).where(OrbAlert.vessel_id == upload.vessel_id).order_by(OrbAlert.severity)
    )
    alerts = alerts_result.scalars().all()

    entry_quantities: dict[uuid.UUID, list] = {}
    for entry in entries:
        qty_result = await db.execute(
            select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id)
        )
        entry_quantities[entry.id] = qty_result.scalars().all()

    buf = BytesIO()
    styles = getSampleStyleSheet()

    vessel_name = vessel.name if vessel else "Unknown"
    vessel_imo = vessel.imo_number if vessel else "N/A"
    min_date = min((e.entry_date for e in entries), default=None)
    max_date = max((e.entry_date for e in entries), default=None)

    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        onFirstPage=make_footer(vessel_name, vessel_imo),
        onLaterPages=make_footer(vessel_name, vessel_imo),
    )

    story = []
    title_style = ParagraphStyle("title", parent=styles["Title"], textColor=NAVY, spaceAfter=12)
    h2_style = ParagraphStyle("h2", parent=styles["Heading2"], textColor=NAVY)
    normal = styles["Normal"]

    # ── Cover page ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("OIL RECORD BOOK — PART I", title_style))
    story.append(Paragraph("Machinery Space Operations", h2_style))
    story.append(Spacer(1, 1 * cm))

    cover_data = [
        ["Vessel Name:", vessel_name],
        ["IMO Number:", vessel_imo],
        ["Period:", f"{min_date} to {max_date}"],
        ["Generated:", datetime.now().strftime("%d %b %Y %H:%M UTC")],
        ["Total Entries:", str(len(entries))],
        ["Open Alerts:", str(sum(1 for a in alerts if not a.is_resolved))],
    ]
    cover_table = Table(cover_data, colWidths=[5 * cm, 12 * cm])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT_BLUE, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(cover_table)
    story.append(PageBreak())

    # ── Entry pages ──────────────────────────────────────────────────────────
    story.append(Paragraph("ORB Entries", h2_style))
    story.append(Spacer(1, 0.3 * cm))

    entry_headers = ["Date", "Code", "Item", "Operation", "Qty", "Officers"]
    col_widths = [2.5 * cm, 1.5 * cm, 1.5 * cm, 9 * cm, 4 * cm, 5 * cm]

    table_data = [entry_headers]
    row_fills = [NAVY]

    for idx, entry in enumerate(entries):
        quantities = entry_quantities.get(entry.id, [])
        qty_str = "\n".join(f"{q.qty_value} {q.qty_unit} ({q.qty_type})" for q in quantities)
        officers = "\n".join(filter(None, [
            f"{entry.officer_1_name or ''} ({entry.officer_1_rank or ''})".strip("() "),
            f"{entry.officer_2_name or ''} ({entry.officer_2_rank or ''})".strip("() "),
        ]))

        table_data.append([
            str(entry.entry_date),
            entry.orb_code,
            entry.item_number or "",
            Paragraph(entry.operation_description or "", normal),
            Paragraph(qty_str, normal),
            Paragraph(officers, normal),
        ])
        row_fills.append(LIGHT_BLUE if idx % 2 == 0 else colors.white)

    entry_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(table_data)):
        bg = LIGHT_BLUE if i % 2 == 0 else colors.white
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))

    entry_table.setStyle(TableStyle(style_cmds))
    story.append(entry_table)
    story.append(PageBreak())

    # ── Alert summary ────────────────────────────────────────────────────────
    story.append(Paragraph("Alert Summary", h2_style))
    story.append(Spacer(1, 0.3 * cm))

    alert_headers = ["Severity", "Type", "Message", "Status"]
    alert_data = [alert_headers]
    for alert in alerts:
        alert_data.append([
            alert.severity.upper(),
            alert.alert_type,
            Paragraph(alert.message, normal),
            "Resolved" if alert.is_resolved else "Open",
        ])

    if len(alert_data) > 1:
        alert_table = Table(alert_data, colWidths=[2.5 * cm, 5 * cm, 14 * cm, 2.5 * cm], repeatRows=1)
        severity_color_map = {
            "critical": colors.HexColor("#FFE0E0"),
            "major": colors.HexColor("#FFF0E0"),
            "minor": colors.HexColor("#FFFDE0"),
            "observation": colors.HexColor("#F5F5F5"),
        }
        alert_style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        for i, alert in enumerate(alerts, 1):
            bg = severity_color_map.get(alert.severity, colors.white)
            alert_style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        alert_table.setStyle(TableStyle(alert_style_cmds))
        story.append(alert_table)
    else:
        story.append(Paragraph("No alerts generated.", normal))

    doc.build(story)
    return buf.getvalue()
