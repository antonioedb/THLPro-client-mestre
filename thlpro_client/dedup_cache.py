from __future__ import annotations


from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any



@dataclass
class QuoteState:
    last_price: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    sent_at_monotonic: float



def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None



class QuoteDeduplicator:
    def __init__(self, min_interval_ms: int = 250):
        self.min_interval_ms = min_interval_ms
        self._state: dict[str, QuoteState] = {}


    def should_send(self, payload: dict[str, Any]) -> bool:
        symbol = payload["option_symbol"]
        now_mono = monotonic()


        current = QuoteState(
            last_price=to_decimal(payload.get("last_price")),
            bid=to_decimal(payload.get("bid")),
            ask=to_decimal(payload.get("ask")),
            sent_at_monotonic=now_mono,
        )


        # Não envia cotação sem nenhum dado útil
        if current.last_price is None and current.bid is None and current.ask is None:
            return False


        old = self._state.get(symbol)


        # Primeira cotação válida da opção: sempre envia
        if old is None:
            self._state[symbol] = current
            return True


        changed = (
            current.last_price != old.last_price
            or current.bid != old.bid
            or current.ask != old.ask
        )


        if not changed:
            return False


        elapsed_ms = (now_mono - old.sent_at_monotonic) * 1000.0
        if elapsed_ms < self.min_interval_ms:
            # Guarda o novo valor, mas espera o intervalo mínimo
            self._state[symbol] = QuoteState(
                last_price=current.last_price,
                bid=current.bid,
                ask=current.ask,
                sent_at_monotonic=old.sent_at_monotonic,
            )
            return False


        self._state[symbol] = current
        return True