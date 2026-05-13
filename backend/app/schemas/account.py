import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.account import AccountType, TaxTreatment


class AccountCreate(BaseModel):
    name: str
    broker: str
    account_type: AccountType
    external_id: str
    currency: str = "EUR"
    tax_treatment: TaxTreatment
    ost_lifetime_deposits: Optional[Decimal] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    ost_lifetime_deposits: Optional[Decimal] = None


class AccountRead(BaseModel):
    id: uuid.UUID
    name: str
    broker: str
    account_type: AccountType
    external_id: str
    currency: str
    tax_treatment: TaxTreatment
    ost_lifetime_deposits: Optional[Decimal]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
