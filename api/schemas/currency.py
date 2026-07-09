"""Currency monitor response schemas."""

from pydantic import BaseModel, ConfigDict, Field


class CurrencySignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    latest_rate: float
    range_low: float
    range_high: float
    range_position: float = Field(..., ge=0.0, le=1.0)
    procurement_signal: str


class CurrencyMonitorResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base: str
    as_of: str
    lookback_days: int
    currencies: list[CurrencySignalResponse]
