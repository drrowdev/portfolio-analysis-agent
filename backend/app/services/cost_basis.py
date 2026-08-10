"""Shared acquisition-cost helpers."""

from __future__ import annotations

from decimal import Decimal


def acquisition_unit_cost_eur(
    price_eur: Decimal,
    quantity: Decimal,
    fees_eur: Decimal,
) -> Decimal:
    """Allocate acquisition fees across the purchased quantity."""
    if quantity <= 0:
        return price_eur
    return price_eur + fees_eur / quantity
