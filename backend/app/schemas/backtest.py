from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


BacktestTrack = Literal["actual_portfolio", "sp500_universe"]


class BacktestRunSummary(BaseModel):
    id: str
    track: BacktestTrack
    status: str
    spec_version: str
    specification_hash: str
    input_hash: str
    promotion_eligible: bool
    created_at: datetime


class BacktestRunDetail(BacktestRunSummary):
    policy: dict[str, Any]
    data_manifest: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None
