from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any


ASSET_REFRESH_INTERVAL_SECONDS = 30.0


@dataclass
class QuoteState:
    last_price: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    sent_at_monotonic: float
    pending: bool = False


def to_decimal(value: Any) -> Decimal | None:
    """
    Converte valor numérico do RTD em Decimal.

    Aceita valores numéricos e texto com vírgula decimal simples,
    como "15,99".
    """
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    raw = str(value).strip()

    if not raw or raw.startswith("#"):
        return None

    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")

    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class QuoteDeduplicator:
    """
    Deduplica opções e ativos-base.

    Chaves:
    - option:<option_symbol>
    - asset:<asset>

    Regras:
    - Opções: primeiro valor válido e, depois, somente mudanças reais de
      last_price, bid ou ask.
    - Ativos-base: primeiro valor válido, mudanças reais e refresh de
      segurança periódico.
    """

    def __init__(
        self,
        min_interval_ms: int = 250,
        asset_refresh_interval_seconds: float = (
            ASSET_REFRESH_INTERVAL_SECONDS
        ),
    ):
        self.min_interval_ms = max(0, min_interval_ms)

        self.asset_refresh_interval_seconds = max(
            1.0,
            asset_refresh_interval_seconds,
        )

        self._state: dict[str, QuoteState] = {}

    def should_send(self, payload: dict[str, Any]) -> bool:
        """
        Retorna True quando a cotação deve entrar na fila de envio.

        Para opções:
        - primeira leitura válida;
        - alteração em último preço, bid ou ask;
        - alteração pendente após passar o intervalo mínimo.

        Para ativos-base:
        - as mesmas regras acima;
        - refresh de segurança quando vence o intervalo configurado.
        """
        state_key, is_asset = self._get_state_key(payload)

        if state_key is None:
            return False

        now_mono = monotonic()

        current = QuoteState(
            last_price=to_decimal(
                payload.get("last_price", payload.get("premium"))
            ),
            bid=to_decimal(payload.get("bid")),
            ask=to_decimal(payload.get("ask")),
            sent_at_monotonic=now_mono,
        )

        if (
            current.last_price is None
            and current.bid is None
            and current.ask is None
        ):
            return False

        old = self._state.get(state_key)

        # Primeira cotação válida de uma opção ou ativo-base.
        if old is None:
            self._state[state_key] = current
            return True

        changed = (
            current.last_price != old.last_price
            or current.bid != old.bid
            or current.ask != old.ask
        )

        elapsed_seconds = now_mono - old.sent_at_monotonic
        elapsed_ms = elapsed_seconds * 1000.0

        # Somente ativos-base têm refresh forçado. Para opções, uma
        # cotação idêntica não deve voltar à fila apenas pelo tempo.
        refresh_due = (
            is_asset
            and elapsed_seconds >= self.asset_refresh_interval_seconds
        )

        # Nem preço nem livro mudaram; e o ativo ainda não precisa de
        # refresh periódico.
        if not changed and not old.pending and not refresh_due:
            return False

        # Houve mudança, mas ela chegou antes do intervalo mínimo. Guarda
        # o dado novo e permite que uma leitura posterior o envie.
        if elapsed_ms < self.min_interval_ms:
            self._state[state_key] = QuoteState(
                last_price=current.last_price,
                bid=current.bid,
                ask=current.ask,
                sent_at_monotonic=old.sent_at_monotonic,
                pending=True,
            )
            return False

        # Mudança real, refresh de ativo-base ou mudança pendente liberada.
        self._state[state_key] = QuoteState(
            last_price=current.last_price,
            bid=current.bid,
            ask=current.ask,
            sent_at_monotonic=now_mono,
            pending=False,
        )

        return True

    @staticmethod
    def _get_state_key(
        payload: dict[str, Any],
    ) -> tuple[str | None, bool]:
        """
        Retorna (chave, é_ativo_base).

        option_symbol tem prioridade porque o payload de uma opção também
        contém o campo asset com o ativo subjacente.
        """
        option_symbol = str(
            payload.get("option_symbol", "")
        ).strip().upper()

        if option_symbol:
            return f"option:{option_symbol}", False

        asset = str(payload.get("asset", "")).strip().upper()

        if asset:
            return f"asset:{asset}", True

        return None, False