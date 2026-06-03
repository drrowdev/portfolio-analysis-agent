"""Tax calculation storage and PDF generation."""

import json
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tax_calculation import TaxCalculation
from app.models.transaction import Transaction, TransactionType
from app.services import tax as tax_math

router = APIRouter(prefix="/transactions/tax-calculations", tags=["tax-calculations"])


class TaxCalculationCreate(BaseModel):
    """Payload to save a tax calculation."""
    symbol: str
    sell_date: date
    quantity_sold: str
    sell_price_eur: str
    fees_eur: str = "0"
    calculation_json: dict  # the full calculation result


class TaxCalculationRead(BaseModel):
    id: uuid.UUID
    transaction_id: Optional[uuid.UUID]
    symbol: str
    sell_date: date
    quantity_sold: str
    sell_price_eur: str
    fees_eur: str
    calculation_json: dict
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/", response_model=TaxCalculationRead, status_code=201)
async def save_tax_calculation(
    payload: TaxCalculationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Save a tax calculation and auto-link to the matching sell transaction."""
    from decimal import Decimal

    # Try to find the matching sell transaction
    sell_types = [TransactionType.sell, TransactionType.espp_sale]
    stmt = (
        select(Transaction)
        .where(Transaction.symbol == payload.symbol)
        .where(Transaction.transaction_type.in_(sell_types))
        .where(Transaction.date == payload.sell_date)
        .order_by(Transaction.created_at.desc())
        .limit(5)
    )
    result = await db.execute(stmt)
    sells = list(result.scalars().all())

    # Match by quantity and approximate price
    transaction_id = None
    qty = Decimal(payload.quantity_sold)
    price = Decimal(payload.sell_price_eur)
    for s in sells:
        if s.quantity == qty and abs(float(s.price_eur or 0) - float(price)) < 0.01:
            transaction_id = s.id
            break

    # Idempotent save: re-running the same sale (after a logic correction)
    # should REPLACE the previous calculation rather than create a duplicate.
    # Match on the linked transaction when known, otherwise on the natural key
    # (symbol + sell_date + quantity_sold).
    if transaction_id is not None:
        dup_stmt = select(TaxCalculation).where(
            TaxCalculation.transaction_id == transaction_id
        )
    else:
        dup_stmt = (
            select(TaxCalculation)
            .where(TaxCalculation.symbol == payload.symbol)
            .where(TaxCalculation.sell_date == payload.sell_date)
            .where(TaxCalculation.quantity_sold == payload.quantity_sold)
        )
    existing = list((await db.execute(dup_stmt)).scalars().all())
    for old in existing:
        await db.delete(old)

    calc = TaxCalculation(
        symbol=payload.symbol,
        sell_date=payload.sell_date,
        quantity_sold=payload.quantity_sold,
        sell_price_eur=payload.sell_price_eur,
        fees_eur=payload.fees_eur,
        calculation_json=json.dumps(payload.calculation_json),
        transaction_id=transaction_id,
    )
    db.add(calc)
    await db.commit()
    await db.refresh(calc)

    return _to_read(calc)


@router.get("/", response_model=list[TaxCalculationRead])
async def list_tax_calculations(
    symbol: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List saved tax calculations."""
    stmt = select(TaxCalculation).order_by(TaxCalculation.created_at.desc())

    if symbol:
        stmt = stmt.where(TaxCalculation.symbol == symbol)
    if year:
        stmt = stmt.where(TaxCalculation.sell_date >= date(year, 1, 1))
        stmt = stmt.where(TaxCalculation.sell_date <= date(year, 12, 31))

    result = await db.execute(stmt)
    return [_to_read(tc) for tc in result.scalars().all()]


@router.get("/summary")
async def tax_calculations_summary(
    year: Optional[int] = Query(None, description="Tax year (defaults to current year)"),
    db: AsyncSession = Depends(get_db),
):
    """Year-to-date capital-gains summary against the €30,000 bracket.

    Aggregates the taxable gains (luovutusvoitto) from the saved tax
    calculations whose sell date falls in the year, and applies the Finnish
    30 %/34 % pääomatulo bracket to the COMBINED net gain. The €30,000
    threshold is a per-year, total-capital-income figure (not per sale), so
    this combined view is the correct way to see how close the year is to the
    higher 34 % bracket. NOTE: it only reflects sales that have a SAVED tax
    calculation, and it does not include other capital income (dividends,
    rental, other gains), which also counts toward the same €30,000 limit.
    """
    target_year = year or date.today().year
    stmt = (
        select(TaxCalculation)
        .where(TaxCalculation.sell_date >= date(target_year, 1, 1))
        .where(TaxCalculation.sell_date <= date(target_year, 12, 31))
        .order_by(TaxCalculation.sell_date.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())

    sales = []
    total_gain = Decimal("0")
    gains_only = Decimal("0")
    losses_only = Decimal("0")
    total_proceeds = Decimal("0")
    for tc in rows:
        try:
            data = json.loads(tc.calculation_json)
        except (TypeError, ValueError):
            data = {}
        omavero = data.get("omavero", {}) if isinstance(data, dict) else {}
        gain = Decimal(str(omavero.get("luovutusvoitto", 0) or 0))
        proceeds = Decimal(str(omavero.get("luovutushinta", 0) or 0))
        total_gain += gain
        total_proceeds += proceeds
        if gain > 0:
            gains_only += gain
        elif gain < 0:
            losses_only += -gain
        sales.append(
            {
                "id": str(tc.id),
                "symbol": tc.symbol,
                "sell_date": tc.sell_date.isoformat(),
                "gain_eur": float(gain),
                "proceeds_eur": float(proceeds),
            }
        )

    net_gain = total_gain
    tax, eff = tax_math.capital_gains_tax(net_gain)
    threshold = tax_math.BRACKET_THRESHOLD
    remaining = max(Decimal("0"), threshold - net_gain)
    over = max(Decimal("0"), net_gain - threshold)

    return {
        "year": target_year,
        "calculation_count": len(sales),
        "net_gain_eur": float(net_gain),
        "gains_eur": float(gains_only),
        "losses_eur": float(losses_only),
        "total_proceeds_eur": float(total_proceeds),
        "bracket_threshold_eur": float(threshold),
        "remaining_at_30pct_eur": float(remaining),
        "amount_over_threshold_eur": float(over),
        "estimated_tax_eur": float(tax),
        "effective_rate": float(eff),
        "low_rate": float(tax_math.LOW_TAX_RATE),
        "high_rate": float(tax_math.HIGH_TAX_RATE),
        "sales": sales,
    }
async def delete_tax_calculations(
    symbol: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Delete saved tax calculations (optionally filtered by symbol/year).

    With no filters, deletes ALL saved calculations — useful for re-running
    them from scratch after a calculation-logic correction.
    """
    stmt = sa_delete(TaxCalculation)
    if symbol:
        stmt = stmt.where(TaxCalculation.symbol == symbol)
    if year:
        stmt = stmt.where(TaxCalculation.sell_date >= date(year, 1, 1))
        stmt = stmt.where(TaxCalculation.sell_date <= date(year, 12, 31))

    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount or 0}


@router.delete("/{calc_id}", status_code=204)
async def delete_tax_calculation(
    calc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single saved tax calculation by id."""
    result = await db.execute(
        select(TaxCalculation).where(TaxCalculation.id == calc_id)
    )
    calc = result.scalar_one_or_none()
    if calc is None:
        raise HTTPException(status_code=404, detail="Tax calculation not found")
    await db.delete(calc)
    await db.commit()


@router.get("/by-transaction/{transaction_id}", response_model=Optional[TaxCalculationRead])
async def get_tax_calculation_by_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a tax calculation linked to a specific transaction."""
    stmt = select(TaxCalculation).where(
        TaxCalculation.transaction_id == uuid.UUID(transaction_id)
    )
    result = await db.execute(stmt)
    tc = result.scalar_one_or_none()
    if not tc:
        return None
    return _to_read(tc)


@router.get("/{calc_id}", response_model=TaxCalculationRead)
async def get_tax_calculation(
    calc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific tax calculation."""
    stmt = select(TaxCalculation).where(TaxCalculation.id == uuid.UUID(calc_id))
    result = await db.execute(stmt)
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=404, detail="Tax calculation not found")
    return _to_read(tc)


@router.get("/{calc_id}/pdf")
async def download_tax_calculation_pdf(
    calc_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a PDF of the tax calculation."""
    stmt = select(TaxCalculation).where(TaxCalculation.id == uuid.UUID(calc_id))
    result = await db.execute(stmt)
    tc = result.scalar_one_or_none()
    if not tc:
        raise HTTPException(status_code=404, detail="Tax calculation not found")

    data = json.loads(tc.calculation_json)
    pdf_bytes = _generate_pdf(data)

    filename = f"ennakkovero_{tc.symbol}_{tc.sell_date.isoformat()}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _to_read(tc: TaxCalculation) -> TaxCalculationRead:
    return TaxCalculationRead(
        id=tc.id,
        transaction_id=tc.transaction_id,
        symbol=tc.symbol,
        sell_date=tc.sell_date,
        quantity_sold=tc.quantity_sold,
        sell_price_eur=tc.sell_price_eur,
        fees_eur=tc.fees_eur,
        calculation_json=json.loads(tc.calculation_json),
        created_at=tc.created_at.isoformat(),
    )


def _generate_pdf(data: dict) -> bytes:
    """Generate a Finnish ennakkovero PDF from the calculation data."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=16, spaceAfter=6)
    heading_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4)
    normal_style = styles["Normal"]
    small_style = ParagraphStyle("Small", parent=normal_style, fontSize=8, textColor=colors.grey)

    elements = []

    # Title
    elements.append(Paragraph("Ennakkoveroilmoitus — Luovutusvoiton laskenta", title_style))
    elements.append(Paragraph(f"Arvopaperi: {data['symbol']} | Myyntipäivä: {_fmt_date(data['sell_date'])}", normal_style))
    elements.append(Spacer(1, 8 * mm))

    # Sale summary
    elements.append(Paragraph("Myynti / Sale", heading_style))
    sale_data = [
        ["Päivämäärä", _fmt_date(data["sell_date"])],
        ["Määrä (kpl)", f"{data['quantity_sold']}"],
        ["Hinta / kpl (€)", _fmt_eur(data["sell_price_eur"])],
        ["Kulut (€)", _fmt_eur(data["fees_eur"])],
    ]
    if data.get("fx_rate"):
        sale_data.append(["Valuuttakurssi (USD/EUR)", f"{data['fx_rate']:.4f}"])
    elements.append(_make_table(sale_data))
    elements.append(Spacer(1, 4 * mm))

    # OmaVero fields
    omavero = data["omavero"]
    method_labels = {
        "hankintameno_olettama": "Hankintameno-olettama",
        "todellinen_hankintameno": "Todellinen hankintameno",
        "yhdistelma": "Eräkohtainen yhdistelmä",
    }
    elements.append(Paragraph("OmaVero — Täytettävät tiedot", heading_style))
    ov_data = [
        ["Luovutushinta (€)", _fmt_eur(omavero["luovutushinta"])],
        ["Hankintameno — todellinen (€)", _fmt_eur(omavero["hankintameno_todellinen"])],
        ["Hankintameno — olettama (€)", f'{_fmt_eur(omavero["hankintameno_olettama"])} ({omavero["hankintameno_olettama_rate"]})'],
    ]
    if omavero.get("hankintameno_kaytetty") is not None:
        ov_data.append(["Hankintameno — käytetty (€)", _fmt_eur(omavero["hankintameno_kaytetty"])])
    ov_data.extend([
        ["Suositeltu menetelmä", method_labels.get(omavero["recommended_method"], omavero["recommended_method"])],
        ["Luovutusvoitto (€)", _fmt_eur(omavero["luovutusvoitto"])],
        ["Ennakkovero (€)", _fmt_eur(omavero["veron_maara"])],
        ["Veroprosentti", omavero["veroprosentti"]],
    ])
    coverage = data.get("coverage") or {}
    if coverage.get("shortfall_qty", 0) > 0:
        ov_data.insert(
            1,
            ["⚠️ Kattamaton määrä (kpl)", f'{coverage["shortfall_qty"]} / {coverage["quantity_sold"]} (20 % olettama)'],
        )
    elements.append(_make_table(ov_data, highlight_last=True))
    elements.append(Spacer(1, 4 * mm))

    # Method comparison
    comp = data["comparison"]
    elements.append(Paragraph("Laskentatapojen vertailu", heading_style))
    comp_data = [
        ["", "Todellinen (FIFO)", f'Olettama ({omavero["hankintameno_olettama_rate"]})'],
        ["Hankintameno (€)", _fmt_eur(comp["fifo_cost_basis_eur"]), _fmt_eur(comp["deemed_cost_eur"])],
        ["Voitto (€)", _fmt_eur(comp["fifo_gain_eur"]), _fmt_eur(comp["deemed_gain_eur"])],
    ]
    t = Table(comp_data, colWidths=[120, 120, 120])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)

    if comp.get("tax_savings_eur", 0) > 0:
        elements.append(Spacer(1, 2 * mm))
        method_name = "hankintameno-olettama" if comp["better_method"] == "deemed" else "todellinen hankintameno"
        elements.append(Paragraph(
            f'💡 Käyttämällä menetelmää "{method_name}" säästät ~€{_fmt_eur(comp["tax_savings_eur"])} veroa.',
            normal_style,
        ))

    # FIFO lots
    lots = data.get("lots_consumed", [])
    if lots:
        elements.append(Spacer(1, 4 * mm))
        elements.append(Paragraph("Myydyt erät (FIFO)", heading_style))
        lot_header = ["Ostopäivä", "Määrä", "Hinta/kpl (€)", "Kustannus (€)", "Pitoaika"]
        lot_rows = [lot_header]
        for lot in lots:
            lot_rows.append([
                _fmt_date(lot["purchase_date"]),
                str(lot["quantity"]),
                _fmt_eur(lot["cost_per_share_eur"]),
                _fmt_eur(lot["lot_cost_eur"]),
                f'{lot["holding_years"]}v {"(>10v)" if lot["over_10_years"] else ""}',
            ])
        lt = Table(lot_rows, colWidths=[80, 50, 80, 80, 70])
        lt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(lt)

    # Notes
    notes = data.get("notes", [])
    if notes:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph("Huomautukset", heading_style))
        for note in notes:
            elements.append(Paragraph(f"• {note}", small_style))

    # Footer
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        f"Luotu: {data['sell_date']} | Tämä on laskennallinen arvio, ei virallinen veroilmoitus.",
        small_style,
    ))

    doc.build(elements)
    return buffer.getvalue()


def _fmt_date(iso: str) -> str:
    """Convert ISO date to Finnish format."""
    parts = str(iso).split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return iso


def _fmt_eur(value) -> str:
    """Format a number as EUR with 2 decimals."""
    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except (ValueError, TypeError):
        return str(value)


def _make_table(data: list[list[str]], highlight_last: bool = False):
    """Create a simple two-column table."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table(data, colWidths=[180, 200])
    style_commands = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    if highlight_last:
        style_commands.append(("BACKGROUND", (-1, -2), (-1, -1), colors.Color(1, 0.96, 0.88)))
        style_commands.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    t.setStyle(TableStyle(style_commands))
    return t
