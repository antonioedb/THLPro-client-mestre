from __future__ import annotations

import logging
from threading import Event

from thlpro_client.api_client import APIError, THLProAPIClient


class ConfigPollerService:
    def __init__(self, logger: logging.Logger, api_client: THLProAPIClient, on_config, interval_seconds: int = 60):
        self.logger = logger
        self.api = api_client
        self.on_config = on_config
        self.interval_seconds = interval_seconds
        self._stop = Event()

    def stop(self):
        self._stop.set()

    def run_forever(self):
        self.logger.info("Serviço de atualização de configuração iniciado (intervalo=%ss)", self.interval_seconds)
        while not self._stop.is_set():
            try:
                cfg = self.api.get_config()
                self.on_config(cfg)
            except APIError as exc:
                self.logger.warning("Falha ao atualizar config do servidor: %s", exc)
            except Exception as exc:  # pragma: no cover
                self.logger.exception("Erro inesperado no config poller: %s", exc)
            self._stop.wait(max(5, self.interval_seconds))
