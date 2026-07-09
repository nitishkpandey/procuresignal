"""Tests for EUR currency monitor."""

from datetime import date

import pytest
from procuresignal.currency.service import CurrencyMonitor


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
