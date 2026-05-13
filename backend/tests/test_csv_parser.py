"""Tests for CSV parsing services.

STUB — will be filled with actual tests.
"""

from datetime import date
from decimal import Decimal

from app.utils.finnish_numbers import parse_finnish_date, parse_finnish_decimal


def test_parse_finnish_decimal_simple() -> None:
    assert parse_finnish_decimal("1234,56") == Decimal("1234.56")


def test_parse_finnish_decimal_with_thousands() -> None:
    assert parse_finnish_decimal("1.234,56") == Decimal("1234.56")


def test_parse_finnish_decimal_with_spaces() -> None:
    assert parse_finnish_decimal("1 234,56") == Decimal("1234.56")


def test_parse_finnish_date() -> None:
    assert parse_finnish_date("15.03.2024") == date(2024, 3, 15)


# TODO: add tests for parse_nordnet_csv and parse_fidelity_csv
