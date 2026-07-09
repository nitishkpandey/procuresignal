"""EUR currency monitoring for procurement timing signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable

import httpx

DEFAULT_EUR_QUOTES = ("USD", "GBP", "CHF", "JPY", "CNY", "INR", "PLN")
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev"


@dataclass(slots=True)
class CurrencySignal:
    currency: str
    latest_rate: float
    range_low: float
    range_high: float
    range_position: float
    procurement_signal: str


@dataclass(slots=True)
class CurrencyMonitorResponse:
    base: str
    as_of: str
    lookback_days: int
    currencies: list[CurrencySignal]


class CurrencyMonitor:
    """Fetch EUR FX data and summarize procurement-relevant range signals."""

    def __init__(
        self,
        *,
        base_url: str = FRANKFURTER_BASE_URL,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=15.0))

    async def get_eur_monitor(
        self,
        *,
        quotes: Iterable[str] = DEFAULT_EUR_QUOTES,
        days: int = 30,
        today: date | None = None,
    ) -> CurrencyMonitorResponse:
        clean_quotes = _normalize_quotes(quotes)
        lookback_days = max(2, min(days, 365))
        end_date = today or date.today()
        start_date = end_date - timedelta(days=lookback_days)

        async with self.client_factory() as client:
            latest_response = await client.get(
                f"{self.base_url}/v2/rates",
                params={"base": "EUR", "quotes": ",".join(clean_quotes)},
            )
            latest_response.raise_for_status()
            latest_payload = latest_response.json()

            history_response = await client.get(
                f"{self.base_url}/v2/rates",
                params={
                    "base": "EUR",
                    "quotes": ",".join(clean_quotes),
                    "from": start_date.isoformat(),
                    "to": end_date.isoformat(),
                },
            )
            history_response.raise_for_status()
            history_payload = history_response.json()

        latest_rates = _extract_latest_rates(latest_payload)
        history_rates = _extract_history_rates(history_payload)
        signals: list[CurrencySignal] = []

        for currency in clean_quotes:
            latest = latest_rates.get(currency)
            values = [row[currency] for row in history_rates if currency in row]
            if latest is None and values:
                latest = values[-1]
            if latest is None:
                continue
            values = values or [latest]
            low = min(values)
            high = max(values)
            position = 0.5 if high == low else (latest - low) / (high - low)
            position = max(0.0, min(1.0, position))
            signals.append(
                CurrencySignal(
                    currency=currency,
                    latest_rate=latest,
                    range_low=low,
                    range_high=high,
                    range_position=position,
                    procurement_signal=_procurement_signal(currency, position, lookback_days),
                )
            )

        return CurrencyMonitorResponse(
            base="EUR",
            as_of=_extract_as_of(latest_payload) or end_date.isoformat(),
            lookback_days=lookback_days,
            currencies=signals,
        )


def _normalize_quotes(quotes: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for quote in quotes:
        code = str(quote).strip().upper()
        if len(code) == 3 and code != "EUR" and code not in normalized:
            normalized.append(code)
    return normalized or list(DEFAULT_EUR_QUOTES)


def _extract_latest_rates(payload: object) -> dict[str, float]:
    if isinstance(payload, list):
        return _extract_row_rates(payload)

    if not isinstance(payload, dict):
        return {}

    rates = payload.get("rates") or {}
    if not isinstance(rates, dict):
        return {}
    return {str(code).upper(): float(value) for code, value in rates.items() if value is not None}


def _extract_history_rates(payload: object) -> list[dict[str, float]]:
    if isinstance(payload, list):
        return [{code: value} for code, value in _extract_row_pairs(payload)]

    if not isinstance(payload, dict):
        return []

    rates = payload.get("rates") or {}
    if isinstance(rates, dict):
        rows = rates.values()
    elif isinstance(rates, list):
        rows = rates
    else:
        rows = []

    parsed: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parsed.append(
            {
                str(code).upper(): float(value)
                for code, value in row.items()
                if len(str(code)) == 3 and value is not None
            }
        )
    return parsed


def _extract_row_pairs(rows: list) -> list[tuple[str, float]]:
    parsed: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        quote = str(row.get("quote") or row.get("currency") or "").upper()
        rate = row.get("rate")
        if len(quote) == 3 and rate is not None:
            parsed.append((quote, float(rate)))
    return parsed


def _extract_row_rates(rows: list) -> dict[str, float]:
    rates: dict[str, float] = {}
    for code, value in _extract_row_pairs(rows):
        rates[code] = value
    return rates


def _extract_as_of(payload: object) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("date")
        return str(value) if value else None
    if isinstance(payload, list):
        dates = [
            str(row.get("date")) for row in payload if isinstance(row, dict) and row.get("date")
        ]
        return max(dates) if dates else None
    return None


def _procurement_signal(currency: str, position: float, days: int) -> str:
    if position >= 0.8:
        return (
            f"EUR is near its {days}-day high vs {currency}; euro-denominated buyers may have "
            "stronger purchasing power for suppliers priced in this currency."
        )
    if position <= 0.2:
        return (
            f"EUR is near its {days}-day low vs {currency}; consider extra review before timing "
            "large purchases priced in this currency."
        )
    return (
        f"EUR is mid-range vs {currency} over {days} days; currency timing is not sending a "
        "strong procurement signal."
    )
