"""Parsing for Nordnet CSV exports and Fidelity PDF statements.

Nordnet exports are UTF-16 LE tab-separated files with Finnish locale
(comma as decimal separator, dd.mm.yyyy dates).

Fidelity Stock Plan statements are PDFs — we extract holdings and
transaction data from the text.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.utils.finnish_numbers import parse_finnish_date, parse_finnish_decimal


# ── Nordnet CSV columns (ostoerittäin / lot-level export) ──────────────────

NORDNET_COLUMNS = [
    "tulostuspaiva",       # 0  Tulostuspäivä (report date)
    "salkku",              # 1  Salkku (portfolio ID)
    "hankintapaiva",       # 2  Hankintapäivä (purchase date)
    "instrumentti",        # 3  Instrumentti (instrument name)
    "tunnus",              # 4  Tunnus (ticker)
    "isin",                # 5  ISIN
    "valuutta",            # 6  Valuutta (currency)
    "maara",               # 7  Määrä (quantity)
    "hankintahinta_native",  # 8  Hankintahinta (Noteerausvaluutta)
    "hankintahinta_eur",     # 9  Hankintahinta (EUR)
    "hankintaarvo_native",   # 10 Hankinta-arvo (Noteerausvaluutta)
    "hankintaarvo_eur",      # 11 Hankinta-arvo (EUR)
    "markkinaarvo_native",   # 12 Markkina-arvo (Noteerausvaluutta)
    "markkinaarvo_eur",      # 13 Markkina-arvo (EUR)
    "tuotto_pct",            # 14 Tuotto-%
    "tuotto_pa_pct",         # 15 Tuotto-% (p.a)
]


@dataclass
class NordnetLot:
    """A single purchase lot from a Nordnet export."""
    portfolio_id: str
    purchase_date: date
    instrument_name: str
    ticker: str
    isin: str
    currency: str
    quantity: Decimal
    cost_price_native: Decimal
    cost_price_eur: Decimal
    cost_value_native: Decimal
    cost_value_eur: Decimal
    market_value_native: Decimal
    market_value_eur: Decimal
    return_pct: Decimal
    return_pa_pct: Decimal


@dataclass
class NordnetParseResult:
    """Result of parsing a Nordnet CSV file."""
    portfolio_id: str
    report_date: date
    lots: list[NordnetLot] = field(default_factory=list)
    holdings_summary: list[dict[str, Any]] = field(default_factory=list)


def _decode_nordnet_content(content: bytes) -> str:
    """Decode Nordnet CSV content, trying UTF-16 LE then UTF-8."""
    # Nordnet exports are typically UTF-16 LE with BOM
    for encoding in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("Could not decode Nordnet CSV — unsupported encoding")


def parse_nordnet_csv_sync(content: bytes) -> NordnetParseResult:
    """Parse a Nordnet 'ostoerittäin' (lot-level) CSV export.

    File format: UTF-16 LE, tab-separated, Finnish locale.
    Returns structured lot data + aggregated holdings summary.
    """
    text = _decode_nordnet_content(content)
    lines = [line for line in text.strip().splitlines() if line.strip()]

    if not lines:
        raise ValueError("Empty Nordnet CSV file")

    # Skip header row
    data_lines = lines[1:]
    if not data_lines:
        raise ValueError("Nordnet CSV has header but no data rows")

    lots: list[NordnetLot] = []
    portfolio_id = ""
    report_date = None

    for line in data_lines:
        cols = line.split("\t")
        if len(cols) < 16:
            continue  # skip malformed rows

        # Strip whitespace from all columns
        cols = [c.strip() for c in cols]

        try:
            lot = NordnetLot(
                portfolio_id=cols[1],
                purchase_date=parse_finnish_date(cols[2]),
                instrument_name=cols[3],
                ticker=cols[4],
                isin=cols[5],
                currency=cols[6],
                quantity=parse_finnish_decimal(cols[7]),
                cost_price_native=parse_finnish_decimal(cols[8]),
                cost_price_eur=parse_finnish_decimal(cols[9]),
                cost_value_native=parse_finnish_decimal(cols[10]),
                cost_value_eur=parse_finnish_decimal(cols[11]),
                market_value_native=parse_finnish_decimal(cols[12]),
                market_value_eur=parse_finnish_decimal(cols[13]),
                return_pct=parse_finnish_decimal(cols[14]),
                return_pa_pct=parse_finnish_decimal(cols[15]),
            )
            lots.append(lot)
            portfolio_id = cols[1]
            if report_date is None:
                report_date = parse_finnish_date(cols[0])
        except (InvalidOperation, ValueError):
            continue  # skip rows with unparseable data

    if not lots:
        raise ValueError("No valid data rows found in Nordnet CSV")

    # Aggregate lots into holdings (per symbol)
    holdings_map: dict[str, dict[str, Any]] = {}
    for lot in lots:
        key = f"{lot.ticker}:{lot.isin}"
        if key not in holdings_map:
            holdings_map[key] = {
                "ticker": lot.ticker,
                "isin": lot.isin,
                "instrument_name": lot.instrument_name,
                "currency": lot.currency,
                "total_quantity": Decimal("0"),
                "total_cost_eur": Decimal("0"),
                "total_market_value_eur": Decimal("0"),
                "lot_count": 0,
            }
        h = holdings_map[key]
        h["total_quantity"] += lot.quantity
        h["total_cost_eur"] += lot.cost_value_eur
        h["total_market_value_eur"] += lot.market_value_eur
        h["lot_count"] += 1

    # Compute derived fields
    holdings_summary = []
    for h in holdings_map.values():
        qty = h["total_quantity"]
        cost = h["total_cost_eur"]
        market = h["total_market_value_eur"]
        pnl = market - cost
        pnl_pct = (pnl / cost * 100) if cost else Decimal("0")
        avg_cost = (cost / qty) if qty else Decimal("0")

        holdings_summary.append({
            **h,
            "avg_cost_basis_eur": avg_cost.quantize(Decimal("0.001")),
            "unrealized_pnl_eur": pnl.quantize(Decimal("0.01")),
            "unrealized_pnl_pct": pnl_pct.quantize(Decimal("0.01")),
        })

    return NordnetParseResult(
        portfolio_id=portfolio_id,
        report_date=report_date or date.today(),
        lots=lots,
        holdings_summary=holdings_summary,
    )


async def parse_nordnet_csv(content: bytes) -> NordnetParseResult:
    """Async wrapper for Nordnet CSV parsing."""
    return parse_nordnet_csv_sync(content)


# ── Fidelity PDF parsing ───────────────────────────────────────────────────

@dataclass
class FidelityHolding:
    """A holding extracted from a Fidelity Stock Plan statement."""
    symbol: str
    name: str
    quantity: Decimal
    price_usd: Decimal
    market_value_usd: Decimal
    cost_basis_usd: Decimal
    unrealized_gain_usd: Decimal


@dataclass
class FidelityTransaction:
    """A transaction from the Fidelity activity section."""
    date: date
    symbol: str
    name: str
    transaction_type: str  # dividend, reinvestment, conversion, tax
    quantity: Decimal | None
    price_usd: Decimal | None
    amount_usd: Decimal | None
    cost_basis_usd: Decimal | None


@dataclass
class FidelityParseResult:
    """Result of parsing a Fidelity PDF statement."""
    participant_number: str
    period_start: date
    period_end: date
    account_value_usd: Decimal
    holdings: list[FidelityHolding] = field(default_factory=list)
    transactions: list[FidelityTransaction] = field(default_factory=list)
    espp_contributions_usd: Decimal = Decimal("0")
    espp_contribution_rate_pct: Decimal = Decimal("0")


def _parse_usd(value: str) -> Decimal:
    """Parse a USD amount like '$224,179.86' or '-81.20' to Decimal."""
    cleaned = value.replace("$", "").replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned == "--" or cleaned == "-":
        return Decimal("0")
    return Decimal(cleaned)


def _parse_date_fidelity(month_day: str, year: int) -> date:
    """Parse 'MM/DD' with a given year to a date."""
    parts = month_day.strip().split("/")
    if len(parts) == 2:
        return date(year, int(parts[0]), int(parts[1]))
    raise ValueError(f"Cannot parse date: {month_day}")


def parse_fidelity_pdf_sync(content: bytes) -> FidelityParseResult:
    """Parse a Fidelity Stock Plan Services Report PDF.

    Extracts holdings (with cost basis), transactions, and ESPP info.
    Uses line-by-line parsing since PyMuPDF outputs each cell on a separate line.
    Requires PyMuPDF (fitz) to be installed.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF is required for Fidelity PDF parsing: pip install pymupdf")

    doc = fitz.open(stream=content, filetype="pdf")
    full_text = ""
    pages_text: list[str] = []
    for page in doc:
        page_text = page.get_text()
        pages_text.append(page_text)
        full_text += page_text + "\n"
    doc.close()

    lines = full_text.splitlines()

    # Extract period dates
    period_match = re.search(
        r"(\w+ \d{1,2}, \d{4})\s*-\s*(\w+ \d{1,2}, \d{4})",
        full_text,
    )
    if period_match:
        from datetime import datetime as dt
        period_start = dt.strptime(period_match.group(1), "%B %d, %Y").date()
        period_end = dt.strptime(period_match.group(2), "%B %d, %Y").date()
    else:
        period_start = period_end = date.today()

    year = period_end.year

    # Extract participant number
    participant_match = re.search(r"Participant Number:\s*(\w+)", full_text)
    participant_number = participant_match.group(1) if participant_match else ""

    # Extract account value
    value_match = re.search(
        r"(?:Your Stock Plan Account Value|Ending Account Value)[:\s]*\$([\d,]+\.\d{2})",
        full_text,
    )
    account_value = _parse_usd(value_match.group(1)) if value_match else Decimal("0")

    # ── Extract MSFT holdings using line-by-line scanning ──
    holdings: list[FidelityHolding] = []
    for i, line in enumerate(lines):
        if "MICROSOFT CORP (MSFT)" in line or "MICROSOFT CORP\xa0(MSFT)" in line:
            # Look ahead for the numeric fields within next 10 lines
            nums = []
            for j in range(i + 1, min(i + 15, len(lines))):
                stripped = lines[j].strip()
                # Stop if we hit another section
                if "Total" in stripped and "Stock" in stripped:
                    break
                # Match dollar amounts and plain numbers
                amount_match = re.match(r'^[\$]?([\d,]+\.\d{2,4})$', stripped)
                if amount_match:
                    nums.append(amount_match.group(1).replace(",", ""))
            # Expected order: beg_value, quantity, price, end_value, cost_basis, gain
            if len(nums) >= 6:
                holdings.append(FidelityHolding(
                    symbol="MSFT",
                    name="Microsoft Corp",
                    quantity=Decimal(nums[1]),
                    price_usd=Decimal(nums[2]),
                    market_value_usd=Decimal(nums[3]),
                    cost_basis_usd=Decimal(nums[4]),
                    unrealized_gain_usd=Decimal(nums[5]),
                ))
                break  # Only one MSFT holding expected

    # ── Extract transactions line-by-line ──
    transactions: list[FidelityTransaction] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect date lines like "03/12 " or "t 03/02 "
        date_match = re.match(r'^t?\s*(\d{2}/\d{2})\s*$', stripped)
        if not date_match:
            continue

        date_str = date_match.group(1)
        try:
            tx_date = _parse_date_fidelity(date_str, year)
        except ValueError:
            continue

        # Look at next lines to determine transaction type
        lookahead = []
        for j in range(i + 1, min(i + 12, len(lines))):
            lookahead.append(lines[j].strip())
        lookahead_text = " ".join(lookahead)

        # ESPP Conversion (shares deposited)
        if "MICROSOFT CORP" in lookahead_text and "Conversion" in lookahead_text:
            qty = None
            price = None
            cost = None
            for la_line in lookahead:
                if la_line.startswith("Conversion"):
                    continue
                # Quantity: plain decimal like "1.599" or "2.400"
                if qty is None and re.match(r'^\d+\.\d{3}$', la_line):
                    qty = Decimal(la_line)
                # Price: with or without $ like "$392.7392" or "392.7392"
                elif price is None and re.match(r'^\$?\d+\.\d{4}$', la_line):
                    price = Decimal(la_line.replace("$", ""))
                # Cost basis: "$627.99" or "627.99"
                elif cost is None and price is not None and re.match(r'^\$?\d+\.\d{2}$', la_line):
                    cost = Decimal(la_line.replace("$", ""))
                    break
            if qty and price:
                transactions.append(FidelityTransaction(
                    date=tx_date,
                    symbol="MSFT",
                    name="Microsoft Corp",
                    transaction_type="espp_purchase",
                    quantity=qty,
                    price_usd=price,
                    amount_usd=None,
                    cost_basis_usd=cost,
                ))
            continue

        # Dividend received
        if "MICROSOFT CORP" in lookahead_text and "Dividend Received" in lookahead_text:
            amount = None
            for la_line in lookahead:
                if la_line == "-":
                    continue
                amt_match = re.match(r'^\$?([\d,]+\.\d{2})$', la_line)
                if amt_match and "Dividend" not in la_line:
                    amount = Decimal(amt_match.group(1).replace(",", ""))
            if amount:
                transactions.append(FidelityTransaction(
                    date=tx_date,
                    symbol="MSFT",
                    name="Microsoft Corp",
                    transaction_type="dividend",
                    quantity=None,
                    price_usd=None,
                    amount_usd=amount,
                    cost_basis_usd=None,
                ))
            continue

        # Dividend reinvestment
        if "MICROSOFT CORP" in lookahead_text and "Reinvestment" in lookahead_text:
            qty = None
            price = None
            amount = None
            for la_line in lookahead:
                if la_line.startswith("Reinvestment"):
                    continue
                if qty is None and re.match(r'^\d+\.\d{3}$', la_line):
                    qty = Decimal(la_line)
                elif price is None and re.match(r'^\d+\.\d{4,5}$', la_line):
                    price = Decimal(la_line)
                elif amount is None and re.match(r'^-?\d+\.\d{2}$', la_line):
                    amount = Decimal(la_line)
                    break
            if qty and price:
                transactions.append(FidelityTransaction(
                    date=tx_date,
                    symbol="MSFT",
                    name="Microsoft Corp",
                    transaction_type="reinvestment",
                    quantity=qty,
                    price_usd=price,
                    amount_usd=amount,
                    cost_basis_usd=None,
                ))
            continue

    # Tax withheld — scan for Non-Resident Tax lines
    for i, line in enumerate(lines):
        stripped = line.strip()
        date_match = re.match(r'^(\d{2}/\d{2})\s*$', stripped)
        if not date_match:
            continue
        # Check if next lines contain tax info
        lookahead = " ".join(
            lines[j].strip() for j in range(i + 1, min(i + 5, len(lines)))
        )
        if "MICROSOFT CORP" in lookahead and "Non-Resident Tax" in lookahead:
            tax_date = _parse_date_fidelity(date_match.group(1), year)
            # Find the amount
            for j in range(i + 1, min(i + 6, len(lines))):
                amt_match = re.match(r'^-\$([\d,]+\.\d{2})', lines[j].strip())
                if amt_match:
                    transactions.append(FidelityTransaction(
                        date=tax_date,
                        symbol="MSFT",
                        name="Microsoft Corp",
                        transaction_type="tax_withheld",
                        quantity=None,
                        price_usd=None,
                        amount_usd=-_parse_usd(amt_match.group(1)),
                        cost_basis_usd=None,
                    ))
                    break

    # ESPP contribution info
    espp_rate = Decimal("0")
    espp_contributions = Decimal("0")
    for i, line in enumerate(lines):
        if "Section 423" in line or "Qualified" in line:
            # Look for rate and amount in surrounding lines
            nearby = " ".join(
                lines[j].strip() for j in range(max(0, i - 3), min(i + 5, len(lines)))
            )
            rate_match = re.search(r'(\d+\.\d+)%', nearby)
            amt_match = re.search(r'\$([\d,]+\.\d{2})', nearby)
            if rate_match:
                espp_rate = Decimal(rate_match.group(1))
            if amt_match:
                espp_contributions = _parse_usd(amt_match.group(1))
            break

    return FidelityParseResult(
        participant_number=participant_number,
        period_start=period_start,
        period_end=period_end,
        account_value_usd=account_value,
        holdings=holdings,
        transactions=transactions,
        espp_contributions_usd=espp_contributions,
        espp_contribution_rate_pct=espp_rate,
    )


async def parse_fidelity_pdf(content: bytes) -> FidelityParseResult:
    """Async wrapper for Fidelity PDF parsing."""
    return parse_fidelity_pdf_sync(content)
