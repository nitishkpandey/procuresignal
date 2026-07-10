"""Tests for EUR currency monitor."""

from datetime import date

import pytest
from procuresignal.currency.service import DEFAULT_EUR_QUOTES, CurrencyMonitor


def test_default_quotes_cover_global_supplier_markets():
    assert len(DEFAULT_EUR_QUOTES) >= 25
    for currency in ["USD", "GBP", "CNY", "INR", "JPY", "KRW", "MXN", "CAD", "AUD"]:
        assert currency in DEFAULT_EUR_QUOTES


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return _FakeResponse(self.responses.pop(0))


class _FailingAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def get(self, url, **kwargs):
        raise TimeoutError("provider unavailable")


@pytest.mark.asyncio
async def test_currency_monitor_computes_range_position():
    fake_client = _FakeAsyncClient(
        [
            {
                "base": "EUR",
                "date": "2026-07-09",
                "rates": {"USD": 1.2, "GBP": 0.9},
            },
            {
                "base": "EUR",
                "rates": {
                    "2026-07-07": {"USD": 1.1, "GBP": 0.8},
                    "2026-07-08": {"USD": 1.15, "GBP": 0.85},
                    "2026-07-09": {"USD": 1.2, "GBP": 0.9},
                },
            },
        ]
    )
    monitor = CurrencyMonitor(client_factory=lambda: fake_client)

    result = await monitor.get_eur_monitor(
        quotes=["USD", "GBP"],
        days=30,
        today=date(2026, 7, 9),
    )

    assert result.base == "EUR"
    assert [item.currency for item in result.currencies] == ["USD", "GBP"]
    assert result.currencies[0].latest_rate == 1.2
    assert result.currencies[0].range_high == 1.2
    assert result.currencies[0].range_low == 1.1
    assert result.currencies[0].range_position == 1.0
    assert "near its 30-day high" in result.currencies[0].procurement_signal


@pytest.mark.asyncio
async def test_currency_monitor_returns_neutral_rows_when_provider_fails():
    monitor = CurrencyMonitor(client_factory=lambda: _FailingAsyncClient())

    result = await monitor.get_eur_monitor(
        quotes=["USD", "GBP"],
        days=30,
        today=date(2026, 7, 9),
    )

    assert result.as_of == "2026-07-09"
    assert [item.currency for item in result.currencies] == ["USD", "GBP"]
    assert all(item.range_position == 0.5 for item in result.currencies)
    assert all("provider unavailable" in item.procurement_signal for item in result.currencies)


@pytest.mark.asyncio
async def test_currency_monitor_accepts_frankfurter_row_payloads():
    fake_client = _FakeAsyncClient(
        [
            [
                {"date": "2026-07-09", "base": "EUR", "quote": "USD", "rate": 1.2},
                {"date": "2026-07-09", "base": "EUR", "quote": "GBP", "rate": 0.9},
            ],
            [
                {"date": "2026-07-07", "base": "EUR", "quote": "USD", "rate": 1.1},
                {"date": "2026-07-08", "base": "EUR", "quote": "USD", "rate": 1.15},
                {"date": "2026-07-09", "base": "EUR", "quote": "USD", "rate": 1.2},
            ],
        ]
    )
    monitor = CurrencyMonitor(client_factory=lambda: fake_client)

    result = await monitor.get_eur_monitor(
        quotes=["USD"],
        days=30,
        today=date(2026, 7, 9),
    )

    assert result.as_of == "2026-07-09"
    assert result.currencies[0].latest_rate == 1.2
    assert result.currencies[0].range_low == 1.1
