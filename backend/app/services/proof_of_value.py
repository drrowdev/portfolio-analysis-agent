from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_settings import UserSetting
from app.schemas.analysis import ProofOfValuePolicy, ProofOfValuePolicyState


POLICY_PREFIX = "proof_of_value."
REQUIRED_FIELDS = (
    "investment_horizon_years",
    "max_drawdown_pct",
    "max_annualized_volatility_pct",
    "max_tracking_error_pct",
    "max_single_position_pct",
    "max_sector_pct",
    "max_annual_turnover_pct",
    "estimated_transaction_cost_bps",
    "minimum_expected_net_alpha_pct",
)

_DECIMAL_FIELDS = {
    "max_drawdown_pct",
    "max_annualized_volatility_pct",
    "max_tracking_error_pct",
    "max_single_position_pct",
    "max_sector_pct",
    "max_annual_turnover_pct",
    "estimated_transaction_cost_bps",
    "minimum_expected_net_alpha_pct",
}
_INTEGER_FIELDS = {"investment_horizon_years", "price_stale_after_hours"}
_EDITABLE_FIELDS = REQUIRED_FIELDS + ("price_stale_after_hours",)


def _setting_key(field: str) -> str:
    return f"{POLICY_PREFIX}{field}"


def _parse_value(field: str, value: str) -> object:
    if field in _DECIMAL_FIELDS:
        return Decimal(value)
    if field in _INTEGER_FIELDS:
        return int(value)
    return value


def _policy_state(policy: ProofOfValuePolicy) -> ProofOfValuePolicyState:
    missing = [field for field in REQUIRED_FIELDS if getattr(policy, field) is None]
    return ProofOfValuePolicyState(
        **policy.model_dump(),
        is_complete=not missing,
        missing_fields=missing,
        objective=(
            "Maximize expected after-tax, after-cost return and outperform the "
            "configured benchmark while remaining inside the explicit risk budget."
        ),
        return_methodology=(
            "Shadow recommendations are compared with holding the current portfolio, "
            "a deterministic rebalance policy, and the benchmark. Cash, estimated "
            "transaction costs, realized taxes, turnover, and drawdown must be "
            "reported before the AI layer can be credited with value."
        ),
    )


async def get_policy(db: AsyncSession) -> ProofOfValuePolicyState:
    keys = [_setting_key(field) for field in _EDITABLE_FIELDS]
    result = await db.execute(select(UserSetting).where(UserSetting.key.in_(keys)))
    values = {
        row.key.removeprefix(POLICY_PREFIX): row.value
        for row in result.scalars().all()
    }
    parsed = {
        field: _parse_value(field, value)
        for field, value in values.items()
    }
    return _policy_state(ProofOfValuePolicy(**parsed))


async def save_policy(
    db: AsyncSession, policy: ProofOfValuePolicy
) -> ProofOfValuePolicyState:
    if (
        policy.benchmark_ticker != "^SP500TR"
        or policy.benchmark_currency.upper() != "EUR"
    ):
        raise ValueError(
            "Only the existing S&P 500 Total Return benchmark in EUR is supported "
            "until configurable benchmark pricing is implemented."
        )

    keys = [_setting_key(field) for field in _EDITABLE_FIELDS]
    result = await db.execute(select(UserSetting).where(UserSetting.key.in_(keys)))
    existing = {row.key: row for row in result.scalars().all()}

    for field in _EDITABLE_FIELDS:
        key = _setting_key(field)
        value = getattr(policy, field)
        if value is None:
            if key in existing:
                await db.execute(delete(UserSetting).where(UserSetting.key == key))
            continue
        serialized = str(value)
        if key in existing:
            existing[key].value = serialized
        else:
            db.add(UserSetting(key=key, value=serialized))

    await db.flush()
    return _policy_state(policy)
