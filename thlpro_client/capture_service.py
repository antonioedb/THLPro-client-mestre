from __future__ import annotations

import logging
import math
from threading import Event, Lock
from typing import Any

from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.rtd_client import BaseRTDClient
from thlpro_client.timezone_utils import now_iso_sp


EXCEL_ERROR_LIMIT = -2140000000


def is_valid_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return False

        return value > EXCEL_ERROR_LIMIT

    if isinstance(value, str):
        if value.startswith("#"):
            return False

        try:
            number = float(value)
        except ValueError:
            return False

        return math.isfinite(number) and number > EXCEL_ERROR_LIMIT

    return False


def infer_asset(
    assets: list[dict[str, Any]],
    option_symbol: str,
) -> str:
    symbols = [
        asset.get("symbol", "")
        for asset in assets
        if asset.get("symbol")
    ]

    def asset_root(symbol: str) -> str:
        i = len(symbol)
        while i > 0 and symbol[i - 1].isdigit():
            i -= 1
        return symbol[:i] if i > 0 else symbol

    roots = sorted(
        [(symbol, asset_root(symbol)) for symbol in symbols],
        key=lambda item: len(item[1]),
        reverse=True,
    )

    for symbol, root in roots:
        if root and option_symbol.startswith(root):
            return symbol

    return symbols[0] if symbols else "BOVA11"


class CaptureService:
    def __init__(
        self,
        logger: logging.Logger,
        rtd_client: BaseRTDClient,
        deduplicator: QuoteDeduplicator,
        queue_enqueue,
        queue_enqueue_asset,
        simulation_mode: bool,
    ):
        self.logger = logger
        self.rtd_client = rtd_client
        self.deduplicator = deduplicator
        self.queue_enqueue = queue_enqueue
        self.queue_enqueue_asset = queue_enqueue_asset
        self.simulation_mode = simulation_mode

        self._stop = Event()
        self._pause = Event()
        self._pause.set()

        self._lock = Lock()
        self._last_values: dict[str, dict[str, Any]] = {}
        self._meta_by_rtd: dict[str, dict[str, Any]] = {}

        self._pending_series: list[dict[str, Any]] = []
        self._pending_assets: list[str] = []

        self._configured_symbols: set[str] = set()
        self._asset_symbols: set[str] = set()

    def set_pending_config(self, config_payload: dict[str, Any]) -> None:
        assets = config_payload.get("assets", [])
        active_series = config_payload.get("active_series", [])

        new_series = []

        for row in active_series:
            option_symbol = row["option_symbol"]

            if option_symbol in self._configured_symbols:
                continue

            new_series.append(
                {
                    "id": row.get("id"),
                    "option_symbol": option_symbol,
                    "option_type": row.get("option_type"),
                    "strike": str(row.get("strike")),
                    "expiration_date": row.get("expiration_date"),
                    "asset": infer_asset(assets, option_symbol),
                }
            )

        new_assets = []

        for asset in assets:
            symbol = asset.get("symbol")

            if not symbol:
                continue

            if symbol in self._asset_symbols:
                continue

            if symbol in self._pending_assets:
                continue

            new_assets.append(symbol)

        with self._lock:
            self._pending_series.extend(new_series)
            self._pending_assets.extend(new_assets)

        self.logger.info(
            "Configuração recebida: %s novas séries e %s novos ativos-base pendentes.",
            len(new_series),
            len(new_assets),
        )

    def _configure_series_batch(self, batch_size: int = 100) -> int:
        with self._lock:
            batch = self._pending_series[:batch_size]
            self._pending_series = self._pending_series[batch_size:]

        configured_symbols: list[str] = []

        for row in batch:
            option_symbol = row["option_symbol"]
            option_series_id = row.get("id")

            if option_series_id is not None:
                self.rtd_client.register_meta(
                    option_series_id,
                    option_symbol,
                )

            meta = {
                "id": option_series_id,
                "asset": row["asset"],
                "option_symbol": option_symbol,
                "option_type": row.get("option_type"),
                "strike": row.get("strike"),
                "expiration_date": row.get("expiration_date"),
            }

            with self._lock:
                self._configured_symbols.add(option_symbol)
                self._meta_by_rtd[option_symbol] = meta

            configured_symbols.append(option_symbol)

        if configured_symbols:
            configured_symbols = self.rtd_client.subscribe_batch(
                configured_symbols,
                ["ULT", "OCP", "OVD", "VEN", "PEX"],
            )

        return len(configured_symbols)

    def _configure_asset_batch(self, batch_size: int = 50) -> int:
        with self._lock:
            batch = self._pending_assets[:batch_size]
            self._pending_assets = self._pending_assets[batch_size:]

        if not batch:
            return 0

        for symbol in batch:
            self.rtd_client.register_asset(symbol)

            with self._lock:
                self._asset_symbols.add(symbol)

        configured = self.rtd_client.subscribe_batch(
            batch,
            ["ULT"],
        )

        return len(configured)

    def start_capture(self):
        self._pause.clear()

    def stop_capture(self):
        self._pause.set()

    def stop(self):
        self._stop.set()

    def run_forever(self):
        self.rtd_client.connect()

        source = "SIMULATED" if self.simulation_mode else "Profit RTD"
        self.logger.info("Serviço de captura iniciado. source=%s", source)

        while not self._stop.is_set():
            configured_series = self._configure_series_batch(batch_size=100)
            configured_assets = self._configure_asset_batch(batch_size=50)

            if configured_series or configured_assets:
                self.logger.info(
                    "Assinadas %s séries e %s ativos-base. Pendentes: %s séries, %s ativos.",
                    configured_series,
                    configured_assets,
                    len(self._pending_series),
                    len(self._pending_assets),
                )

            if self._pause.is_set():
                self._stop.wait(0.2)
                continue

            updates = self.rtd_client.poll_updates(timeout_seconds=0.5)

            option_rows: list[dict[str, Any]] = []
            asset_rows: list[dict[str, Any]] = []

            with self._lock:
                for upd in updates:
                    if upd.rtd_symbol in self._asset_symbols:
                        self._handle_asset_update(
                            upd,
                            source,
                            asset_rows,
                        )
                        continue

                    self._handle_option_update(
                        upd,
                        source,
                        option_rows,
                    )

            if option_rows:
                inserted = self.queue_enqueue(option_rows)

                self.logger.info(
                    "Captura: %s cotações de opções enfileiradas. Novas na fila: %s",
                    len(option_rows),
                    inserted,
                )

            if asset_rows:
                inserted = self.queue_enqueue_asset(asset_rows)

                self.logger.info(
                    "Captura: %s cotações de ativos-base enfileiradas. Novas na fila: %s",
                    len(asset_rows),
                    inserted,
                )

    def _handle_option_update(
        self,
        upd,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        meta = self._meta_by_rtd.get(upd.rtd_symbol)

        if not meta:
            return

        if not is_valid_number(upd.value):
            return

        bucket = self._last_values.setdefault(
            upd.rtd_symbol,
            {
                "ULT": None,
                "OCP": None,
                "OVD": None,
            },
        )

        bucket[upd.field] = upd.value

        last_price = bucket.get("ULT")
        bid = bucket.get("OCP")
        ask = bucket.get("OVD")

        if last_price is None and bid is None and ask is None:
            return

        payload = {
            "option_series_id": meta.get("id"),
            "asset": meta["asset"],
            "option_symbol": meta["option_symbol"],
            "option_type": meta.get("option_type"),
            "strike": meta.get("strike"),
            "expiration_date": meta.get("expiration_date"),
            "last_price": last_price,
            "bid": bid,
            "ask": ask,
            "premium": last_price,
            "quote_timestamp": upd.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        if self.deduplicator.should_send(payload):
            rows.append(payload)

    def _handle_asset_update(
        self,
        upd,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if upd.field != "ULT":
            return

        if not is_valid_number(upd.value):
            return

        payload = {
            "asset": upd.rtd_symbol,
            "last_price": upd.value,
            "variation_points": None,
            "variation_pct": None,
            "high": None,
            "low": None,
            "quote_timestamp": upd.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        rows.append(payload)