import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class HoldingRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    symbol: str
    isin: str
    instrument_name: str
    exchange: Optional[str]
    currency: str
    total_quantity: Decimal
    avg_cost_basis_eur: Decimal
    total_cost_eur: Decimal
    current_price_native: Optional[Decimal]
    current_price_eur: Optional[Decimal]
    current_value_eur: Optional[Decimal]
    unrealized_pnl_eur: Optional[Decimal]
    unrealized_pnl_pct: Optional[Decimal]
    portfolio_weight_pct: Optional[Decimal]
    price_change_pct: Optional[Decimal]
    market_state: Optional[str]
    extended_hours_price: Optional[Decimal]
    extended_hours_change_pct: Optional[Decimal]
    last_price_update: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
