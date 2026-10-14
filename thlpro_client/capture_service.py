from __future__ import annotations

import logging
import math
from threading import Event, Lock
from typing import Any

from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.rtd_client import BaseRTDClient
from thlpro_client.timezone_utils import now_iso_sp


EXCEL_ERROR_LIMIT = -2140000000

OPTION_FIELDS = ["ULT", "OCP", "OVD"]
ASSET_FIELDS = ["ULT"]


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
            number = to_float(value)
        except (TypeError, ValueError):
            return False

        return (
            number is not None
            and math.isfinite(number)
            and number > EXCEL_ERROR_LIMIT
        )

    return False


def to_float(value: Any) -> float | None:
    """
    Converte números recebidos pelo Excel/RTD para float.

    Trata formatos brasileiros e internacionais sem corromper a parte decimal:
    - 200.15
    - 200,15
    - 1.234,56
    - 1,234.56
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    if not isinstance(value, str):
        return None

    normalized = value.strip()

    if not normalized or normalized.startswith("#"):
        return None

    normalized = normalized.replace("R$", "").replace(" ", "")

    comma_count = normalized.count(",")
    dot_count = normalized.count(".")

    if comma_count and dot_count:
        last_comma = normalized.rfind(",")
        last_dot = normalized.rfind(".")

        if last_comma > last_dot:
            # Exemplo: 1.234,56
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            # Exemplo: 1,234.56
            normalized = normalized.replace(",", "")

    elif comma_count:
        # Exemplo: 200,15
        normalized = normalized.replace(",", ".")

    try:
        number = float(normalized)
    except ValueError:
        return None

    return number if math.isfinite(number) else None


def infer_asset(
    assets: list[dict[str, Any]],
    option_symbol: str,
) -> str:
    symbols = [
        str(asset.get("symbol", "")).upper()
        for asset in assets
        if asset.get("symbol")
    ]

    def asset_root(symbol: str) -> str:
        index = len(symbol)

        while index > 0 and symbol[index - 1].isdigit():
            index -= 1

        return symbol[:index] if index > 0 else symbol

    roots = sorted(
        [(symbol, asset_root(symbol)) for symbol in symbols],
        key=lambda item: len(item[1]),
        reverse=True,
    )

    option_upper = option_symbol.upper()

    for symbol, root in roots:
        if root and option_upper.startswith(root):
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

        # Últimos valores válidos dos campos das opções.
        self._last_values: dict[str, dict[str, Any]] = {}

        # Último ULT válido de cada ativo-base. O ConfigPollerService usa
        # estes spots para solicitar ao backend somente strikes relevantes.
        self._asset_spots: dict[str, float] = {}

        # Último spot já registrado no log por ativo.
        self._logged_asset_spots: dict[str, float] = {}

        # Metadados somente das opções efetivamente assinadas.
        self._meta_by_rtd: dict[str, dict[str, Any]] = {}

        # Itens aguardando assinatura no Excel/RTD.
        self._pending_series: list[dict[str, Any]] = []
        self._pending_assets: list[str] = []

        # Evitam duplicação enquanto os itens aguardam assinatura.
        self._pending_series_symbols: set[str] = set()
        self._pending_asset_symbols: set[str] = set()

        # Somente símbolos confirmados pelo subscribe_batch.
        self._configured_symbols: set[str] = set()
        self._asset_symbols: set[str] = set()

    def get_asset_spots(self) -> dict[str, float]:
        """
        Retorna uma cópia segura do último ULT de cada ativo-base.

        Exemplo:
        {
            "BOVA11": 205.55,
            "ABEV3": 15.99,
        }
        """
        with self._lock:
            return dict(self._asset_spots)

    def set_pending_config(self, config_payload: dict[str, Any]) -> None:
        """
        Recebe a configuração do backend sem duplicar símbolos já
        configurados ou aguardando assinatura.
        """
        assets = config_payload.get("assets", [])
        active_series = config_payload.get("active_series", [])

        new_series: list[dict[str, Any]] = []
        new_assets: list[str] = []

        with self._lock:
            for row in active_series:
                option_symbol = str(row.get("option_symbol", "")).upper()

                if not option_symbol:
                    continue

                if option_symbol in self._configured_symbols:
                    continue

                if option_symbol in self._pending_series_symbols:
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
                self._pending_series_symbols.add(option_symbol)

            for asset in assets:
                symbol = str(asset.get("symbol", "")).upper()

                if not symbol:
                    continue

                if symbol in self._asset_symbols:
                    continue

                if symbol in self._pending_asset_symbols:
                    continue

                new_assets.append(symbol)
                self._pending_asset_symbols.add(symbol)

            self._pending_series.extend(new_series)
            self._pending_assets.extend(new_assets)

            pending_series_count = len(self._pending_series)
            pending_asset_count = len(self._pending_assets)

        self.logger.info(
            "Configuração recebida: %s novas séries e %s novos ativos-base. "
            "Fila atual: %s séries e %s ativos-base.",
            len(new_series),
            len(new_assets),
            pending_series_count,
            pending_asset_count,
        )

    def _configure_series_batch(self, batch_size: int = 100) -> int:
        with self._lock:
            batch = self._pending_series[:batch_size]
            self._pending_series = self._pending_series[batch_size:]

            for row in batch:
                self._pending_series_symbols.discard(row["option_symbol"])

        if not batch:
            return 0

        symbols = [row["option_symbol"] for row in batch]

        for row in batch:
            option_series_id = row.get("id")

            if option_series_id is not None:
                self.rtd_client.register_meta(
                    option_series_id,
                    row["option_symbol"],
                )

        try:
            subscribed_symbols = set(
                self.rtd_client.subscribe_batch(
                    symbols,
                    OPTION_FIELDS,
                )
            )
        except Exception as exc:
            self.logger.exception(
                "Falha ao assinar lote de %s opções no RTD: %s",
                len(batch),
                exc,
            )
            subscribed_symbols = set()

        configured_count = 0
        retry_rows: list[dict[str, Any]] = []

        with self._lock:
            for row in batch:
                option_symbol = row["option_symbol"]

                if option_symbol not in subscribed_symbols:
                    retry_rows.append(row)
                    continue

                self._configured_symbols.add(option_symbol)
                self._meta_by_rtd[option_symbol] = {
                    "id": row.get("id"),
                    "asset": row["asset"],
                    "option_symbol": option_symbol,
                    "option_type": row.get("option_type"),
                    "strike": row.get("strike"),
                    "expiration_date": row.get("expiration_date"),
                }
                configured_count += 1

            for row in retry_rows:
                option_symbol = row["option_symbol"]

                if option_symbol in self._configured_symbols:
                    continue

                if option_symbol in self._pending_series_symbols:
                    continue

                self._pending_series.append(row)
                self._pending_series_symbols.add(option_symbol)

            pending_count = len(self._pending_series)

        if retry_rows:
            failed_symbols = ", ".join(
                row["option_symbol"] for row in retry_rows[:10]
            )
            suffix = "..." if len(retry_rows) > 10 else ""

            self.logger.warning(
                "RTD não confirmou %s opções; elas voltarão à fila. "
                "Exemplos: %s%s",
                len(retry_rows),
                failed_symbols,
                suffix,
            )

        self.logger.info(
            "Assinatura RTD de opções: solicitadas=%s confirmadas=%s "
            "pendentes=%s",
            len(batch),
            configured_count,
            pending_count,
        )

        return configured_count

    def _configure_asset_batch(self, batch_size: int = 50) -> int:
        with self._lock:
            batch = self._pending_assets[:batch_size]
            self._pending_assets = self._pending_assets[batch_size:]

            for symbol in batch:
                self._pending_asset_symbols.discard(symbol)

        if not batch:
            return 0

        for symbol in batch:
            self.rtd_client.register_asset(symbol)

        try:
            subscribed_symbols = set(
                self.rtd_client.subscribe_batch(
                    batch,
                    ASSET_FIELDS,
                )
            )
        except Exception as exc:
            self.logger.exception(
                "Falha ao assinar lote de %s ativos-base no RTD: %s",
                len(batch),
                exc,
            )
            subscribed_symbols = set()

        configured_count = 0
        retry_symbols: list[str] = []

        with self._lock:
            for symbol in batch:
                if symbol not in subscribed_symbols:
                    retry_symbols.append(symbol)
                    continue

                self._asset_symbols.add(symbol)
                configured_count += 1

            for symbol in retry_symbols:
                if symbol in self._asset_symbols:
                    continue

                if symbol in self._pending_asset_symbols:
                    continue

                self._pending_assets.append(symbol)
                self._pending_asset_symbols.add(symbol)

            pending_count = len(self._pending_assets)

        if retry_symbols:
            self.logger.warning(
                "RTD não confirmou %s ativos-base; eles voltarão à fila: %s",
                len(retry_symbols),
                ", ".join(retry_symbols),
            )

        self.logger.info(
            "Assinatura RTD de ativos-base: solicitados=%s confirmados=%s "
            "pendentes=%s",
            len(batch),
            configured_count,
            pending_count,
        )

        return configured_count

    def start_capture(self) -> None:
        self._pause.clear()

    def stop_capture(self) -> None:
        self._pause.set()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        self.rtd_client.connect()

        source = "SIMULATED" if self.simulation_mode else "Profit RTD"
        self.logger.info("Serviço de captura iniciado. source=%s", source)

        while not self._stop.is_set():
            configured_assets = self._configure_asset_batch(batch_size=50)
            configured_series = self._configure_series_batch(batch_size=100)

            if configured_assets or configured_series:
                with self._lock:
                    pending_series_count = len(self._pending_series)
                    pending_asset_count = len(self._pending_assets)

                self.logger.info(
                    "Assinadas nesta rodada: %s séries e %s ativos-base. "
                    "Pendentes: %s séries e %s ativos-base.",
                    configured_series,
                    configured_assets,
                    pending_series_count,
                    pending_asset_count,
                )

            if self._pause.is_set():
                self._stop.wait(0.2)
                continue

            updates = self.rtd_client.poll_updates(timeout_seconds=0.5)

            option_rows: list[dict[str, Any]] = []
            asset_rows: list[dict[str, Any]] = []

            with self._lock:
                for update in updates:
                    if update.rtd_symbol in self._asset_symbols:
                        self._handle_asset_update(
                            update,
                            source,
                            asset_rows,
                        )
                        continue

                    self._handle_option_update(
                        update,
                        source,
                        option_rows,
                    )

            if option_rows:
                inserted = self.queue_enqueue(option_rows)

                self.logger.info(
                    "Captura: %s cotações de opções processadas; "
                    "%s novas na fila.",
                    len(option_rows),
                    inserted,
                )

            if asset_rows:
                inserted = self.queue_enqueue_asset(asset_rows)

                self.logger.info(
                    "Captura: %s cotações de ativos-base processadas; "
                    "%s novas na fila.",
                    len(asset_rows),
                    inserted,
                )

    def _handle_option_update(
        self,
        update,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        meta = self._meta_by_rtd.get(update.rtd_symbol)

        if not meta:
            return

        if update.field not in OPTION_FIELDS:
            return

        if not is_valid_number(update.value):
            return

        bucket = self._last_values.setdefault(
            update.rtd_symbol,
            {
                "ULT": None,
                "OCP": None,
                "OVD": None,
            },
        )

        bucket[update.field] = update.value

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
            "quote_timestamp": update.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        if self.deduplicator.should_send(payload):
            rows.append(payload)

    def _handle_asset_update(
        self,
        update,
        source: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if update.field != "ULT":
            return

        if not is_valid_number(update.value):
            return

        spot = to_float(update.value)

        if spot is None or spot <= 0:
            return

        symbol = update.rtd_symbol.upper()

        # Este método é chamado sob self._lock no loop principal.
        self._asset_spots[symbol] = spot

        logged_spot = self._logged_asset_spots.get(symbol)

        if (
            logged_spot is None
            or not math.isclose(
                logged_spot,
                spot,
                rel_tol=0.0,
                abs_tol=0.000001,
            )
        ):
            self.logger.info(
                "Spot RTD atualizado: %s = %.4f",
                symbol,
                spot,
            )
            self._logged_asset_spots[symbol] = spot

        payload = {
            "asset": symbol,
            "last_price": spot,
            "variation_points": None,
            "variation_pct": None,
            "high": None,
            "low": None,
            "quote_timestamp": update.timestamp or now_iso_sp(),
            "source": source,
            "data_status": "OK",
        }

        # Os ativos continuam atualizando _asset_spots em toda leitura,
        # mas somente vão para a fila se houver mudança ou refresh periódico.
        if self.deduplicator.should_send(payload):
            rows.append(payload)