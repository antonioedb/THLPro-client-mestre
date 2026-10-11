from __future__ import annotations

import logging
from threading import Event

from thlpro_client.api_client import APIError, THLProAPIClient, compute_backoff_seconds


class SenderService:
    def __init__(self, logger: logging.Logger, api_client: THLProAPIClient, queue, heartbeat_seconds: int = 30):
        self.logger = logger
        self.api = api_client
        self.queue = queue
        self.heartbeat_seconds = heartbeat_seconds
        self._stop = Event()

    def stop(self):
        self._stop.set()

    def run_forever(self):
        self.logger.info("Serviço de envio iniciado")
        attempt = 1
        hb_counter = 0
        while not self._stop.is_set():
            try:
                hb_counter += 1
                if hb_counter >= self.heartbeat_seconds * 2:  # loop de 0.5s
                    hb_counter = 0
                    self.api.heartbeat()
                    self.logger.info("Heartbeat enviado com sucesso")

                batch = self.queue.dequeue_batch(100)
                if not batch:
                    self._stop.wait(0.5)
                    continue

                ids = [row[0] for row in batch]
                payload = [row[1] for row in batch]
                result = self.api.send_quotes(payload)
                self.queue.ack_ids(ids)
                self.logger.info("Envio OK: accepted=%s rejected=%s", result.accepted, len(result.rejected))
                for reject in result.rejected:
                    self.logger.warning("Quote rejeitada: %s", reject)
                attempt = 1
            except APIError as exc:
                delay = compute_backoff_seconds(attempt)
                self.logger.error("Erro de rede/API (%s). Tentando novamente em %.1fs", exc, delay)
                attempt += 1
                self._stop.wait(delay)
            except Exception as exc:  # pragma: no cover
                self.logger.exception("Erro inesperado no sender: %s", exc)
                self._stop.wait(1.0)
