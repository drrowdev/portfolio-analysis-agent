import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.transaction import TransactionType


class TransactionRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    symbol: str
    isin: str
    instrument_name: str
    currency: str
    transaction_type: TransactionType
    date: date
    quantity: Decimal
    price_native: Decimal
    price_eur: Decimal
    total_native: Decimal
    total_eur: Decimal
    fx_rate: Optional[Decimal]
    fees: Decimal
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionCreate(BaseModel):
    account_id: uuid.UUID
    symbol: str
    isin: str = ""
    instrument_name: str = ""
    currency: str = "EUR"
    transaction_type: TransactionType
    date: date
    quantity: Decimal = Decimal("0")
    price_native: Decimal = Decimal("0")
    price_eur: Decimal = Decimal("0")
    total_native: Decimal = Decimal("0")
    total_eur: Decimal = Decimal("0")
    fx_rate: Optional[Decimal] = None
    fees: Decimal = Decimal("0")
    notes: Optional[str] = None
