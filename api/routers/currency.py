"""Currency monitoring endpoints."""

from fastapi import APIRouter, Query
from procuresignal.currency import CurrencyMonitor

from api.schemas.currency import CurrencyMonitorResponseSchema

router = APIRouter(prefix="/api/currency", tags=["currency"])


@router.get("/eur-monitor", response_model=CurrencyMonitorResponseSchema)
async def get_eur_currency_monitor(
    quotes: str = Query("USD,GBP,CHF,JPY,CNY,INR,PLN", min_length=3, max_length=100),
    days: int = Query(30, ge=7, le=365),
) -> CurrencyMonitorResponseSchema:
    """Return EUR exchange-rate positioning for procurement planning."""

    quote_list = [quote.strip().upper() for quote in quotes.split(",") if quote.strip()]
    result = await CurrencyMonitor().get_eur_monitor(quotes=quote_list, days=days)
    return CurrencyMonitorResponseSchema.model_validate(result)
