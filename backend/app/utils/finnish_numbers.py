"""Utilities for parsing Finnish locale numbers and dates."""

from datetime import date, datetime
from decimal import Decimal


def parse_finnish_decimal(value: str) -> Decimal:
    """Convert Finnish number format (1 234,56 or 1.234,56) to Decimal."""
    return Decimal(value.replace(" ", "").replace(".", "").replace(",", "."))


def parse_finnish_date(value: str) -> date:
    """Convert dd.mm.yyyy to date."""
    return datetime.strptime(value, "%d.%m.%Y").date()
