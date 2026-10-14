from __future__ import annotations

import logging
import time
from threading import Event

from thlpro_client.api_client import (
    APIError,
    THLProAPIClient,
    compute_backoff_seconds,
)


OPTION_BATCH_SIZE = 100
ASSET_BATCH_SIZE = 100

# Evita centenas de POSTs repetidos de BOVA11 e ABEV3 quando o Excel
# está sendo consultado duas vezes por segundo.
ASSET_SEND_MIN_INTERVAL_SECONDS = 3.0

# Mantém prioridade para opções sem impedir que os ativos-base recebam
# atualização periódica. Em cada ciclo podem sair até cinco lotes de opções.
MAX_OPTION_BATCHES_PER_CYCLE = 5


class SenderService:
    def __init__(
        self,
        logger: logging.Logger,
        api_client: THLProAPIClient,
        queue,
        heartbeat_seconds: int = 30,
    ):
        self.logger = logger
        self.api = api_client
        self.queue = queue
        self.heartbeat_seconds = heartbeat_seconds
        self._stop = Event()

        self._last_asset_send_at = 0.0

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        self.logger.info("Serviço de envio iniciado")

        attempt = 1
        next_heartbeat_at = time.monotonic() + self.heartbeat_seconds

        while not self._stop.is_set():
            try:
                now = time.monotonic()

                if now >= next_heartbeat_at:
                    self.api.heartbeat()
                    self.logger.info("Heartbeat enviado com sucesso")
                    next_heartbeat_at = (
                        time.monotonic() + self.heartbeat_seconds
                    )

                option_batches_sent = 0

                while (
                    option_batches_sent < MAX_OPTION_BATCHES_PER_CYCLE
                    and not self._stop.is_set()
                ):
                    sent = self._send_option_quotes()

                    if not sent:
                        break

                    option_batches_sent += 1

                now = time.monotonic()

                if (
                    now - self._last_asset_send_at
                    >= ASSET_SEND_MIN_INTERVAL_SECONDS
                ):
                    asset_batch_sent = self._send_asset_quotes()

                    if asset_batch_sent:
                        self._last_asset_send_at = time.monotonic()

                attempt = 1
                self._stop.wait(0.5)

            except APIError as exc:
                delay = compute_backoff_seconds(attempt)

                self.logger.error(
                    "Erro de rede/API (%s). Tentando novamente em %.1fs",
                    exc,
                    delay,
                )

                attempt += 1
                self._stop.wait(delay)

            except Exception as exc:
                self.logger.exception(
                    "Erro inesperado no sender: %s",
                    exc,
                )
                self._stop.wait(1.0)

    def _send_option_quotes(self) -> bool:
        """
        Envia um lote de opções.

        Retorna True quando havia um lote e ele foi processado; False quando
        a fila estava vazia. Isso permite priorizar opções no loop principal.
        """
        batch = self.queue.dequeue_batch(OPTION_BATCH_SIZE)

        if not batch:
            return False

        ids = [row[0] for row in batch]
        payload = [row[1] for row in batch]

        result = self.api.send_quotes(payload)

        # A resposta foi recebida do backend. Mesmo uma cotação sem mudança
        # não deve ficar presa na fila para sempre.
        self.queue.ack_ids(ids)

        unchanged = 0
        rejected_errors = []

        for rejection in result.rejected:
            reason = str(rejection.get("reason", ""))

            if reason.strip().lower() == "valor igual, não atualiza.":
                unchanged += 1
                continue

            rejected_errors.append(rejection)

        self.logger.info(
            "Envio de opções: lote=%s accepted=%s sem_alteração=%s "
            "rejeitadas=%s",
            len(payload),
            result.accepted,
            unchanged,
            len(rejected_errors),
        )

        for rejection in rejected_errors:
            self.logger.warning(
                "Quote rejeitada pelo backend: %s",
                rejection,
            )

        return True

    def _send_asset_quotes(self) -> bool:
        """
        Envia um lote de ativos-base.

        O intervalo mínimo é controlado em run_forever(), para impedir que
        leituras repetidas de BOVA11 e ABEV3 congestionem o backend.
        """
        batch = self.queue.dequeue_asset_batch(ASSET_BATCH_SIZE)

        if not batch:
            return False

        ids = [row[0] for row in batch]
        payload = [row[1] for row in batch]

        result = self.api.send_asset_quotes(payload)

        # A resposta foi recebida; portanto, removemos o lote local mesmo
        # quando não houve mudança aceita no banco.
        self.queue.ack_asset_ids(ids)

        unchanged = 0
        rejected_errors = []

        for rejection in result.rejected:
            reason = str(rejection.get("reason", ""))

            if reason.strip().lower() == "valor igual, não atualiza.":
                unchanged += 1
                continue

            rejected_errors.append(rejection)

        self.logger.info(
            "Envio de ativos-base: lote=%s accepted=%s sem_alteração=%s "
            "rejeitadas=%s",
            len(payload),
            result.accepted,
            unchanged,
            len(rejected_errors),
        )

        for rejection in rejected_errors:
            self.logger.warning(
                "Asset quote rejeitada pelo backend: %s",
                rejection,
            )

        return True