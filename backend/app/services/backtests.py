"""Orchestration and immutable persistence for both locked backtest tracks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.account import Account
from app.models.backtest import BacktestRun
from app.schemas.backtest import BacktestRunDetail, BacktestRunSummary, BacktestTrack
from app.services.backtest_engine import run_point_in_time_universe_backtest
from app.services.backtest_market_data import download_personal_eur_prices
from app.services.backtest_personal import (
    audit_personal_ledger,
    run_personal_transaction_backtest,
)
from app.services.backtest_spec import (
    BacktestDataError,
    load_eur_price_csv,
    load_locked_backtest_inputs,
)
from app.services.proof_of_value import get_policy


def _canonical_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _ledger_rows(
    db: AsyncSession,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    result = await db.execute(
        select(Account)
        .options(
            selectinload(Account.holdings),
            selectinload(Account.transactions),
        )
        .order_by(Account.id)
    )
    account_models = list(result.scalars().all())
    accounts: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    for account in account_models:
        account_id = str(account.id)
        accounts.append(
            {
                "id": account_id,
                "name": account.name,
                "broker": account.broker,
                "account_type": account.account_type.value,
                "tax_treatment": account.tax_treatment.value,
                "currency": account.currency,
            }
        )
        holdings.extend(
            {
                "id": str(holding.id),
                "account_id": account_id,
                "symbol": holding.symbol,
                "quantity": str(holding.total_quantity),
                "currency": holding.currency,
                "snapshot_date": (
                    holding.snapshot_date.isoformat()
                    if holding.snapshot_date
                    else None
                ),
            }
            for holding in account.holdings
        )
        transactions.extend(
            {
                "id": str(transaction.id),
                "account_id": account_id,
                "tax_treatment": account.tax_treatment.value,
                "symbol": transaction.symbol,
                "currency": transaction.currency,
                "transaction_type": transaction.transaction_type.value,
                "date": transaction.date,
                "quantity": str(transaction.quantity),
                "price_eur": str(transaction.price_eur),
                "total_eur": str(transaction.total_eur),
                "fees": str(transaction.fees or 0),
                "notes": transaction.notes,
            }
            for transaction in account.transactions
        )
    transactions.sort(key=lambda row: (row["date"], row["id"]))
    holdings.sort(key=lambda row: (row["account_id"], row["symbol"], row["id"]))
    return accounts, holdings, transactions


async def personal_ledger_coverage(db: AsyncSession) -> dict[str, Any]:
    accounts, holdings, transactions = await _ledger_rows(db)
    return audit_personal_ledger(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )


def backtest_specification() -> dict[str, Any]:
    locked = load_locked_backtest_inputs()
    return {
        "specification": locked.specification,
        "specification_hash": locked.specification_hash,
        "membership_provenance": locked.membership_provenance,
        "membership_hash": locked.membership_hash,
        "membership_interval_count": len(locked.membership_intervals),
        "required_market_data_csv_columns": [
            "date",
            "ticker",
            "adjusted_close_eur",
        ],
        "historical_evidence_is_proof_of_future_alpha": False,
    }


def _market_data_path() -> Path | None:
    configured = settings.BACKTEST_MARKET_DATA_PATH.strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        path = backend_root / path
    return path.resolve()


async def _persist_result(
    db: AsyncSession,
    *,
    track: BacktestTrack,
    policy_json: dict[str, Any],
    result: dict[str, Any],
    ledger_hash: str | None,
) -> dict[str, Any]:
    run_id = uuid.uuid4()
    data_manifest = dict(result.get("data_manifest") or {})
    if ledger_hash is not None:
        data_manifest["ledger_hash"] = ledger_hash
        result.setdefault("data_manifest", {})["ledger_hash"] = ledger_hash
    input_hash = _canonical_hash(
        {
            "track": track,
            "specification_hash": result["specification_hash"],
            "policy": policy_json,
            "data_manifest": data_manifest,
        }
    )
    result = {**result, "run_id": str(run_id), "input_hash": input_hash}
    db.add(
        BacktestRun(
            id=run_id,
            track=track,
            status=str(result["status"]),
            spec_version=str(result["spec_version"]),
            specification_hash=str(result["specification_hash"]),
            input_hash=input_hash,
            policy_json=policy_json,
            data_manifest_json=data_manifest,
            result_json=result,
            error_message=None,
        )
    )
    await db.flush()
    return result


async def run_backtest(
    db: AsyncSession,
    track: BacktestTrack,
) -> dict[str, Any]:
    locked = load_locked_backtest_inputs()
    policy = await get_policy(db)
    policy_json = policy.model_dump(mode="json")
    accounts, holdings, transactions = await _ledger_rows(db)
    ledger_hash = _canonical_hash(
        {
            "accounts": accounts,
            "holdings": holdings,
            "transactions": transactions,
        }
    )

    if track == "actual_portfolio":
        coverage = audit_personal_ledger(
            accounts=accounts,
            holdings=holdings,
            transactions=transactions,
        )
        candidate_accounts = {
            str(account["id"])
            for account in accounts
            if account["tax_treatment"] == "deferred"
            and account["account_type"] != "crypto"
            and any(
                row["account_id"] == str(account["id"])
                and row["transaction_type"]
                in {"buy", "sell", "espp_purchase", "espp_sale"}
                for row in transactions
            )
        }
        if not candidate_accounts:
            result = {
                "status": "blocked",
                "track": track,
                "spec_version": locked.specification["spec_version"],
                "specification_hash": locked.specification_hash,
                "coverage": coverage,
                "blockers": coverage["blockers"] or [
                    "No supported, reconciled account ledger is available."
                ],
                "historical_evidence_is_proof_of_future_alpha": False,
            }
        else:
            end_date = date.fromisoformat(
                locked.specification["periods"]["holdout"]["end"]
            )
            eligible_transactions = [
                row
                for row in transactions
                if row["account_id"] in candidate_accounts
            ]
            try:
                (
                    prices,
                    split_events,
                    price_hash,
                    price_source,
                ) = await asyncio.to_thread(
                    download_personal_eur_prices,
                    transactions=eligible_transactions,
                    benchmark=locked.specification["benchmark"]["ticker"],
                    end_date=end_date,
                )
                result = await asyncio.to_thread(
                    run_personal_transaction_backtest,
                    prices_eur=prices,
                    split_events=split_events,
                    price_data_hash=price_hash,
                    price_data_source=price_source,
                    locked=locked,
                    policy=policy,
                    accounts=accounts,
                    holdings=holdings,
                    transactions=transactions,
                )
            except BacktestDataError as exc:
                result = {
                    "status": "blocked",
                    "track": track,
                    "spec_version": locked.specification["spec_version"],
                    "specification_hash": locked.specification_hash,
                    "coverage": coverage,
                    "blockers": [str(exc)],
                    "historical_evidence_is_proof_of_future_alpha": False,
                }
        return await _persist_result(
            db,
            track=track,
            policy_json=policy_json,
            result=result,
            ledger_hash=ledger_hash,
        )

    market_data_path = _market_data_path()
    if market_data_path is None:
        result = {
            "status": "blocked",
            "track": track,
            "spec_version": locked.specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "blockers": [
                "BACKTEST_MARKET_DATA_PATH is not configured. The universe track "
                "requires a licensed EUR adjusted-close file with delisted names; "
                "Yahoo data is deliberately not accepted for alpha evidence."
            ],
            "data_manifest": {
                "membership_hash": locked.membership_hash,
                "membership_source_commit": (
                    locked.membership_provenance["source_commit"]
                ),
            },
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    else:
        try:
            prices, price_hash = await asyncio.to_thread(
                load_eur_price_csv,
                market_data_path,
            )
            result = await asyncio.to_thread(
                run_point_in_time_universe_backtest,
                prices_eur=prices,
                price_data_hash=price_hash,
                price_data_source=f"configured CSV {market_data_path.name}",
                locked=locked,
                policy=policy,
            )
        except BacktestDataError as exc:
            result = {
                "status": "blocked",
                "track": track,
                "spec_version": locked.specification["spec_version"],
                "specification_hash": locked.specification_hash,
                "blockers": [str(exc)],
                "data_manifest": {
                    "membership_hash": locked.membership_hash,
                },
                "historical_evidence_is_proof_of_future_alpha": False,
            }
    return await _persist_result(
        db,
        track=track,
        policy_json=policy_json,
        result=result,
        ledger_hash=None,
    )


async def list_backtest_runs(
    db: AsyncSession,
    limit: int = 20,
) -> list[BacktestRunSummary]:
    rows = list(
        (
            await db.execute(
                select(BacktestRun)
                .order_by(BacktestRun.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
    return [
        BacktestRunSummary(
            id=str(row.id),
            track=row.track,
            status=row.status,
            spec_version=row.spec_version,
            specification_hash=row.specification_hash,
            input_hash=row.input_hash,
            promotion_eligible=bool(
                row.result_json.get("promotion_eligible", False)
            ),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def get_backtest_run(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> BacktestRunDetail | None:
    row = await db.get(BacktestRun, run_id)
    if row is None:
        return None
    return BacktestRunDetail(
        id=str(row.id),
        track=row.track,
        status=row.status,
        spec_version=row.spec_version,
        specification_hash=row.specification_hash,
        input_hash=row.input_hash,
        promotion_eligible=bool(
            row.result_json.get("promotion_eligible", False)
        ),
        created_at=row.created_at,
        policy=row.policy_json,
        data_manifest=row.data_manifest_json,
        result=row.result_json,
        error_message=row.error_message,
    )
