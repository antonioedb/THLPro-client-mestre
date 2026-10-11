from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class SeriesConfig:
    asset: str
    option_symbol: str
    option_type: str
    strike: Decimal
    expiration_date: str
    rtd_symbol: str


@dataclass(slots=True)
class RTDQuoteUpdate:
    option_symbol: str
    last_price: float | None
    bid: float | None
    ask: float | None
    quote_timestamp: str
    source: str


@dataclass(slots=True)
class SendResult:
    accepted: int
    rejected: list[dict[str, Any]]
