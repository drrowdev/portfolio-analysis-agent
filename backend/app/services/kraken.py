"""Kraken API integration — fetch ledger entries and compute holdings.

Uses the Ledgers endpoint with spend/receive pairs (instant buy feature).
Only considers buys/sells — ignores transfers/deposits/withdrawals/staking
so that crypto moved to external wallets (e.g. Ledger) is still counted.
"""

import hashlib
import hmac
import base64
import logging
import time
import urllib.parse
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import Account, AccountType, TaxTreatment
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)

KRAKEN_API_URL = "https://api.kraken.com"

ASSET_MAP = {
    "XXBT": "BTC", "XBT": "BTC",
    "XETH": "ETH", "ETH": "ETH",
    "XXRP": "XRP", "XRP": "XRP",
    "XLTC": "LTC", "LTC": "LTC",
    "XXLM": "XLM", "XLM": "XLM",
    "XDOT": "DOT", "DOT": "DOT",
    "XXMR": "XMR", "XMR": "XMR",
    "XZEC": "ZEC", "ZEC": "ZEC",
    "XADA": "ADA", "ADA": "ADA",
    "SOL": "SOL", "ATOM": "ATOM", "AVAX": "AVAX",
    "LINK": "LINK", "UNI": "UNI", "MATIC": "MATIC", "POL": "POL",
    "KAS": "KAS", "PEPE": "PEPE", "HNT": "HNT",
    "DYDX": "DYDX", "FIL": "FIL",
    "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP",
    "USD": "USD", "EUR": "EUR", "USDG": "USDG",
}

FIAT_ASSETS = {"EUR", "USD", "GBP", "USDG"}

# Assets actually held on external wallets (e.g. Ledger).
# Only these get external-wallet quantity added to Kraken balance.
# Coins withdrawn and later sold/swapped elsewhere should NOT be listed here.
EXTERNAL_WALLET_ASSETS = {"BTC", "SOL"}


def _normalize_asset(kraken_asset: str) -> str:
    return ASSET_MAP.get(kraken_asset, kraken_asset)


def _kraken_signature(urlpath: str, data: dict, secret: str) -> str:
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


async def _kraken_private(endpoint: str, extra_data: dict | None = None) -> dict[str, Any]:
    if not settings.KRAKEN_API_KEY or not settings.KRAKEN_API_SECRET:
        raise ValueError("Kraken API key/secret not configured")

    urlpath = f"/0/private/{endpoint}"
    data = {"nonce": str(int(time.time() * 1000))}
    if extra_data:
        data.update(extra_data)

    sig = _kraken_signature(urlpath, data, settings.KRAKEN_API_SECRET)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{KRAKEN_API_URL}{urlpath}",
            data=data,
            headers={"API-Key": settings.KRAKEN_API_KEY, "API-Sign": sig},
        )
        resp.raise_for_status()
        result = resp.json()

    if result.get("error"):
        raise RuntimeError(f"Kraken API error: {result['error']}")
    return result.get("result", {})


async def fetch_ledgers() -> list[dict]:
    """Fetch all ledger entries, paginating."""
    all_entries: list[dict] = []
    offset = 0
    while True:
        result = await _kraken_private("Ledgers", {"ofs": offset})
        ledger = result.get("ledger", {})
        if not ledger:
            break
        for eid, entry in ledger.items():
            all_entries.append({"ledger_id": eid, **entry})
        count = result.get("count", 0)
        offset += len(ledger)
        if offset >= count:
            break
    return all_entries


async def fetch_balances() -> dict[str, Decimal]:
    """Fetch current balances (excludes fiat and dust)."""
    result = await _kraken_private("Balance")
    balances = {}
    for asset, bal in result.items():
        std = _normalize_asset(asset)
        if std not in FIAT_ASSETS and Decimal(str(bal)) > Decimal("0.00000001"):
            balances[std] = Decimal(str(bal))
    return balances


def _pair_buy_entries(entries: list[dict]) -> list[dict]:
    """Pair spend/receive entries by refid to reconstruct instant buys.

    Kraken's instant buy creates:
      - spend: EUR outflow (negative amount, has fee)
      - receive: crypto inflow (positive amount)
    Both share the same refid.

    Also handles traditional trade entries (type=trade) paired the same way.
    """
    by_ref: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        etype = entry.get("type", "")
        if etype in ("spend", "receive", "trade"):
            by_ref[entry.get("refid", "")].append(entry)

    buys = []
    for refid, pair in by_ref.items():
        fiat_entry = None
        crypto_entry = None

        for e in pair:
            asset = _normalize_asset(e.get("asset", ""))
            if asset in FIAT_ASSETS:
                fiat_entry = e
            else:
                crypto_entry = e

        if not crypto_entry:
            continue

        crypto_amount = Decimal(str(crypto_entry.get("amount", "0")))
        if crypto_amount <= 0:
            continue  # This would be a sell — skip for now (user hasn't sold)

        asset = _normalize_asset(crypto_entry.get("asset", ""))
        crypto_fee = Decimal(str(crypto_entry.get("fee", "0")))
        ts = float(crypto_entry.get("time", 0))

        eur_cost = Decimal("0")
        eur_fee = Decimal("0")
        if fiat_entry:
            eur_cost = abs(Decimal(str(fiat_entry.get("amount", "0"))))
            eur_fee = Decimal(str(fiat_entry.get("fee", "0")))
            fiat_asset = _normalize_asset(fiat_entry.get("asset", ""))
            if fiat_asset == "USD":
                eur_cost = eur_cost / Decimal("1.08")
                eur_fee = eur_fee / Decimal("1.08")

        net_qty = crypto_amount - crypto_fee
        price_per_unit = (eur_cost + eur_fee) / net_qty if net_qty > 0 else Decimal("0")

        buys.append({
            "refid": refid,
            "asset": asset,
            "quantity": net_qty,
            "eur_cost": eur_cost,
            "eur_fee": eur_fee,
            "total_cost_eur": eur_cost + eur_fee,
            "price_per_unit_eur": price_per_unit,
            "timestamp": ts,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).date(),
        })

    return sorted(buys, key=lambda b: b["timestamp"])


def compute_holdings_from_buys(buys: list[dict]) -> dict[str, dict]:
    """Aggregate buys per asset into cost basis (used for avg cost, not quantity)."""
    positions: dict[str, dict] = defaultdict(lambda: {
        "quantity": Decimal("0"),
        "total_cost_eur": Decimal("0"),
        "buys": 0,
    })

    for buy in buys:
        asset = buy["asset"]
        positions[asset]["quantity"] += buy["quantity"]
        positions[asset]["total_cost_eur"] += buy["total_cost_eur"]
        positions[asset]["buys"] += 1

    return {
        asset: {
            "symbol": asset,
            "quantity": pos["quantity"],
            "total_cost_eur": pos["total_cost_eur"],
            "avg_cost_eur": pos["total_cost_eur"] / pos["quantity"] if pos["quantity"] > 0 else Decimal("0"),
            "buys": pos["buys"],
        }
        for asset, pos in positions.items()
        if pos["quantity"] > Decimal("0.00000001")
    }


def compute_net_external(entries: list[dict]) -> dict[str, Decimal]:
    """Compute net crypto on external wallets (withdrawals minus deposits).

    Tracks what's actually still on external wallets (e.g. Ledger).
    If coins were withdrawn then deposited back for conversion, net is ~0.
    """
    external: dict[str, Decimal] = defaultdict(Decimal)
    for entry in entries:
        etype = entry.get("type", "")
        if etype not in ("withdrawal", "deposit"):
            continue
        asset = _normalize_asset(entry.get("asset", ""))
        if asset in FIAT_ASSETS:
            continue
        amount = abs(Decimal(str(entry.get("amount", "0"))))
        fee = Decimal(str(entry.get("fee", "0")))
        if etype == "withdrawal":
            external[asset] += amount - fee  # net received on external wallet
        else:
            external[asset] -= amount  # came back from external wallet
    # Only return assets with meaningful positive balance on external wallets
    # AND that are configured as actually held externally
    return {a: q for a, q in external.items()
            if q > Decimal("0.00000001") and a in EXTERNAL_WALLET_ASSETS}


def compute_actual_quantities(
    balances: dict[str, Decimal],
    withdrawals: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Total holdings = Kraken balance + net withdrawals to external wallets."""
    all_assets = set(balances) | set(withdrawals)
    result = {}
    for asset in all_assets:
        qty = balances.get(asset, Decimal("0")) + withdrawals.get(asset, Decimal("0"))
        if qty > Decimal("0.00000001"):
            result[asset] = qty
    return result


async def sync_kraken(db: AsyncSession) -> dict[str, Any]:
    """Full sync: fetch Kraken ledger + balances, compute holdings, update DB.

    Quantities = Kraken balance + net external wallet positions
    (withdrawals minus deposits — so altcoins deposited back and converted
    don't appear as ghost holdings).
    Cost basis = from buy (spend/receive) history.
    """
    ledger_entries = await fetch_ledgers()
    balances = await fetch_balances()

    buys = _pair_buy_entries(ledger_entries)
    cost_basis = compute_holdings_from_buys(buys)
    external = compute_net_external(ledger_entries)
    actual_quantities = compute_actual_quantities(balances, external)

    logger.info(f"Kraken sync: {len(ledger_entries)} ledger entries, {len(buys)} buys, "
                f"{len(balances)} on Kraken, {len(external)} on external wallets, "
                f"{len(actual_quantities)} total assets")

    # Find or create Kraken account
    stmt = select(Account).where(
        Account.broker == "kraken",
        Account.account_type == AccountType.crypto,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        account = existing
        for h in (await db.execute(select(Holding).where(Holding.account_id == account.id))).scalars().all():
            await db.delete(h)
        for t in (await db.execute(select(Transaction).where(Transaction.account_id == account.id))).scalars().all():
            await db.delete(t)
        await db.flush()
    else:
        account = Account(
            id=uuid.uuid4(),
            name="Kraken Crypto",
            broker="kraken",
            account_type=AccountType.crypto,
            external_id="kraken",
            currency="EUR",
            tax_treatment=TaxTreatment.crypto,
        )
        db.add(account)
        await db.flush()

    # Insert buy transactions
    for buy in buys:
        tx = Transaction(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=buy["asset"],
            isin="",
            instrument_name=buy["asset"],
            currency="EUR",
            transaction_type=TransactionType.buy,
            date=buy["date"],
            quantity=buy["quantity"],
            price_native=buy["price_per_unit_eur"],
            price_eur=buy["price_per_unit_eur"],
            total_native=buy["total_cost_eur"],
            total_eur=buy["total_cost_eur"],
            fees=buy["eur_fee"],
            notes=f"Kraken instant buy {buy['refid']}",
        )
        db.add(tx)

    # Create holdings using actual quantities (Kraken balance + net external wallets)
    # with cost basis from buy history
    holdings_count = 0
    for asset, qty in actual_quantities.items():
        cb = cost_basis.get(asset, {})
        total_cost = cb.get("total_cost_eur", Decimal("0"))
        avg_cost = total_cost / qty if qty > 0 and total_cost > 0 else Decimal("0")

        h = Holding(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=asset,
            isin="",
            instrument_name=asset,
            currency="EUR",
            total_quantity=qty,
            avg_cost_basis_eur=avg_cost,
            total_cost_eur=total_cost,
        )
        db.add(h)
        holdings_count += 1

    await db.flush()

    return {
        "account_id": str(account.id),
        "trades_imported": len(buys),
        "holdings_created": holdings_count,
        "holdings": {
            asset: {
                "quantity": str(qty),
                "cost_eur": str(cost_basis.get(asset, {}).get("total_cost_eur", "0")),
                "on_kraken": str(balances.get(asset, Decimal("0"))),
                "on_external": str(external.get(asset, Decimal("0"))),
            }
            for asset, qty in actual_quantities.items()
        },
    }
