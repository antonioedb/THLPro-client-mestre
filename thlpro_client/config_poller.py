from __future__ import annotations

import logging
from threading import Event
from typing import Any, Callable

from thlpro_client.api_client import APIError, THLProAPIClient
from thlpro_client.capture_service import CaptureService


class ConfigPollerService:
    """
    Atualiza a configuração de captura.

    Fluxo:
    1. Sem preços dos ativos-base: pede apenas os ativos habilitados.
    2. Com ULT válido no Excel: envia os spots ao backend.
    3. O backend devolve somente séries ativas, na faixa de ±15% e
       nos vencimentos dentro da janela configurada.
    """

    def __init__(
        self,
        logger: logging.Logger,
        api_client: THLProAPIClient,
        capture_service: CaptureService,
        on_config: Callable[[dict[str, Any]], None],
        interval_seconds: int = 60,
    ):
        self.logger = logger
        self.api = api_client
        self.capture_service = capture_service
        self.on_config = on_config
        self.interval_seconds = interval_seconds
        self._stop = Event()

        self._last_logged_spots: dict[str, float] = {}
        self._last_mode: str | None = None

    def stop(self) -> None:
        self._stop.set()

    def _get_spots(self) -> dict[str, float]:
        """
        Lê uma cópia segura dos últimos ULT válidos dos ativos-base.

        O método get_asset_spots() será adicionado ao CaptureService no
        próximo arquivo, para evitar acesso direto às estruturas internas.
        """
        spots = self.capture_service.get_asset_spots()

        normalized: dict[str, float] = {}

        for symbol, value in spots.items():
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue

            if price <= 0:
                continue

            normalized[str(symbol).upper()] = price

        return normalized

    def _log_mode(self, spots: dict[str, float]) -> None:
        if spots:
            mode = "filtered_series"

            if mode != self._last_mode or spots != self._last_logged_spots:
                rendered_spots = ", ".join(
                    f"{symbol}={price:.4f}"
                    for symbol, price in sorted(spots.items())
                )

                self.logger.info(
                    "Configuração de opções filtrada por spot: %s",
                    rendered_spots,
                )

                self._last_logged_spots = dict(spots)
                self._last_mode = mode

            return

        mode = "assets_only"

        if mode != self._last_mode:
            self.logger.info(
                "Aguardando ULT dos ativos-base no Excel; "
                "serão solicitados somente ativos-base."
            )
            self._last_mode = mode
            self._last_logged_spots = {}

    def run_forever(self) -> None:
        self.logger.info(
            "Serviço de atualização de configuração iniciado "
            "(intervalo=%ss).",
            self.interval_seconds,
        )

        while not self._stop.is_set():
            try:
                spots = self._get_spots()
                self._log_mode(spots)

                config = self.api.get_config(
                    include_series=bool(spots),
                    spots=spots or None,
                )

                self.on_config(config)

                self.logger.info(
                    "Configuração atualizada: %s ativos-base, %s séries.",
                    len(config.get("assets", [])),
                    len(config.get("active_series", [])),
                )

            except APIError as exc:
                self.logger.warning(
                    "Falha ao atualizar configuração do servidor: %s",
                    exc,
                )

            except Exception as exc:  # pragma: no cover
                self.logger.exception(
                    "Erro inesperado no config poller: %s",
                    exc,
                )

            self._stop.wait(max(5, self.interval_seconds))