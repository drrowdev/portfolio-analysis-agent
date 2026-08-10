"""Deterministic output guards for non-executable shadow analysis."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypeAlias


_TRADE_VERB = (
    r"(?:buy(?:ing)?|sell(?:ing)?|trim(?:ming)?|reduc(?:e|ing)|"
    r"increas(?:e|ing)|add(?:ing)?\s+to|exit(?:ing)?|enter(?:ing)?|"
    r"rebalanc(?:e|ing)|rotat(?:e|ing)|allocat(?:e|ing)|invest(?:ing)?)"
)
_TRADE_IMPERATIVE = (
    r"(?:buy|sell|trim|reduce|increase|add\s+to|exit|enter|rebalance|"
    r"rotate|allocate|invest)"
)
_DIRECTIVE = re.compile(
    r"(?i)\b(?:you should|you need to|i recommend(?: that)?|"
    r"my recommendation is to|consider)\s+"
    r"(?!not\b|avoid\b)"
    + _TRADE_VERB
    + r"\b"
)
_IMPERATIVE_CLAUSE = re.compile(
    r"(?im)(?:^|[\n.!?:]\s+|[-*]\s+)"
    r"(?!do not\s+|don't\s+|avoid\s+)"
    + _TRADE_IMPERATIVE
    + r"\b"
)
_SIZED_TRADE = re.compile(
    r"(?i)\b(?:buy|sell|invest|allocate)\s+(?:€|\$)?\d"
)
_PASSIVE_DIRECTIVE = re.compile(
    r"(?i)\b(?:should|must|ought\s+to|needs?\s+to)\s+"
    r"(?!not\b)(?:be\s+)?"
    r"(?:bought|sold|trimmed|reduced|increased|exited|entered|"
    r"rebalanced|rotated|allocated|invested)\b"
)
_RECOMMENDED_GERUND = re.compile(
    r"(?i)\b"
    + _TRADE_VERB
    + r"\b.{0,60}\b(?:is|would\s+be)\s+(?:recommended|advised)\b"
)

NumericClaim: TypeAlias = tuple[str, str]

_NUMBER = r"[-+]?\d+(?:[.,]\d+)*(?:\s?[kKmMbB])?"
_DATE = re.compile(
    r"(?<!\d)(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?<!\d)(?P<euro>\d{1,2}\.\d{1,2}\.\d{4})(?!\d)"
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_ORDERED_LIST = re.compile(r"(?m)^\s*\d+[.)]\s+")
_PERCENT = re.compile(
    rf"(?<![\w])(?P<number>{_NUMBER})\s*(?:%|percent(?:age)?|pct|pp)(?!\w)",
    re.IGNORECASE,
)
_BASIS_POINTS = re.compile(
    rf"(?<![\w])(?P<number>{_NUMBER})\s*(?:basis\s+points?|bps)\b",
    re.IGNORECASE,
)
_CURRENCY_PREFIX = re.compile(
    rf"(?<![\w])(?P<currency>€|\$|EUR|USD)\s*(?P<number>{_NUMBER})(?![\w])",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX = re.compile(
    rf"(?<![\w])(?P<number>{_NUMBER})\s*(?P<currency>EUR|USD)\b",
    re.IGNORECASE,
)
_QUANTITY = re.compile(
    rf"(?<![\w])(?P<number>{_NUMBER})\s*(?:shares?|units?)\b",
    re.IGNORECASE,
)
_DURATION = re.compile(
    rf"(?<![\w])(?P<number>{_NUMBER})\s*(?:trading\s+)?"
    r"(?P<unit>sessions?|days?|weeks?|months?|years?|hours?)\b",
    re.IGNORECASE,
)
_GENERIC_NUMBER = re.compile(rf"(?<![\w])(?P<number>{_NUMBER})(?![\w])")


def contains_actionable_trade_instruction(text: str) -> bool:
    return bool(
        _DIRECTIVE.search(text)
        or _IMPERATIVE_CLAUSE.search(text)
        or _SIZED_TRADE.search(text)
        or _PASSIVE_DIRECTIVE.search(text)
        or _RECOMMENDED_GERUND.search(text)
    )


def any_actionable_trade_instruction(values: Iterable[str]) -> bool:
    return any(contains_actionable_trade_instruction(value) for value in values)


def _decimal_text(raw: str) -> str:
    compact = raw.replace("\u00a0", "").replace(" ", "")
    multiplier = Decimal("1")
    if compact[-1:].lower() in {"k", "m", "b"}:
        multiplier = {
            "k": Decimal("1000"),
            "m": Decimal("1000000"),
            "b": Decimal("1000000000"),
        }[compact[-1].lower()]
        compact = compact[:-1]

    if "," in compact and "." in compact:
        decimal_separator = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        compact = compact.replace(thousands_separator, "").replace(
            decimal_separator, "."
        )
    elif "," in compact:
        whole, fraction = compact.rsplit(",", 1)
        compact = (
            whole.replace(",", "") + fraction
            if len(fraction) == 3 and whole.lstrip("+-") != "0"
            else whole.replace(",", "") + "." + fraction
        )

    try:
        value = Decimal(compact) * multiplier
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numerical claim: {raw}") from exc
    if not value.is_finite():
        raise ValueError(f"Non-finite numerical claim: {raw}")
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _claim(kind: str, raw: str) -> NumericClaim:
    return kind, _decimal_text(raw)


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in occupied)


def numeric_claims_from_text(text: str) -> set[NumericClaim]:
    """Extract explicit numerical claims while ignoring URLs and list numbering."""
    claims: set[NumericClaim] = set()
    occupied = [match.span() for match in _URL.finditer(text)]
    occupied.extend(match.span() for match in _ORDERED_LIST.finditer(text))

    for match in _DATE.finditer(text):
        if _overlaps(match.span(), occupied):
            continue
        raw = match.group("iso") or match.group("euro")
        parsed = (
            date.fromisoformat(raw)
            if match.group("iso")
            else datetime.strptime(raw, "%d.%m.%Y").date()
        )
        claims.add(("date", parsed.isoformat()))
        occupied.append(match.span())

    extractors: tuple[tuple[re.Pattern[str], str], ...] = (
        (_BASIS_POINTS, "bps"),
        (_PERCENT, "percent"),
        (_CURRENCY_PREFIX, "currency"),
        (_CURRENCY_SUFFIX, "currency"),
        (_QUANTITY, "quantity"),
        (_DURATION, "duration"),
    )
    for pattern, kind in extractors:
        for match in pattern.finditer(text):
            if _overlaps(match.span(), occupied):
                continue
            claim_kind = kind
            if kind == "currency":
                currency = match.group("currency").upper()
                claim_kind = "eur" if currency in {"€", "EUR"} else "usd"
            elif kind == "duration":
                claim_kind = match.group("unit").lower().rstrip("s")
            claims.add(_claim(claim_kind, match.group("number")))
            occupied.append(match.span())

    for match in _GENERIC_NUMBER.finditer(text):
        if not _overlaps(match.span(), occupied):
            claims.add(_claim("number", match.group("number")))
    return claims


def _kind_for_path(path: tuple[str, ...]) -> str:
    key = path[-1].lower() if path else ""
    joined = ".".join(part.lower() for part in path)
    if key.endswith("_bps"):
        return "bps"
    if key.endswith("_pct") or "target_allocation" in joined:
        return "percent"
    if key.endswith("_eur"):
        return "eur"
    if "quantity" in key:
        return "quantity"
    for unit in ("sessions", "days", "weeks", "months", "years", "hours"):
        if key.endswith(f"_{unit}"):
            return unit.rstrip("s")
    return "number"


def numeric_grounding_claims(
    *,
    structured: Any = None,
    texts: Iterable[str] = (),
) -> set[NumericClaim]:
    """Build the set of numerical claims explicitly present in trusted inputs."""
    claims: set[NumericClaim] = set()

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, (*path, str(key)))
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                visit(child, path)
            return
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float, Decimal)):
            raw = str(value)
            kind = _kind_for_path(path)
            claims.add(_claim(kind, raw))
            claims.add(_claim("number", raw))
            return
        if not isinstance(value, str):
            return

        key = path[-1].lower() if path else ""
        if key.endswith("_date") or key in {"date", "as_of", "published_at"}:
            try:
                claims.add(("date", date.fromisoformat(value[:10]).isoformat()))
                return
            except ValueError:
                pass
        try:
            Decimal(value)
        except InvalidOperation:
            claims.update(numeric_claims_from_text(value))
        else:
            kind = _kind_for_path(path)
            claims.add(_claim(kind, value))
            claims.add(_claim("number", value))

    visit(structured, ())
    for text in texts:
        claims.update(numeric_claims_from_text(text))
    return claims


def unsupported_numeric_claims(
    values: Iterable[str],
    allowed_claims: set[NumericClaim],
) -> set[NumericClaim]:
    """Return output claims that are absent from supplied deterministic inputs."""
    return {
        claim
        for value in values
        for claim in numeric_claims_from_text(value)
        if claim not in allowed_claims
    }
