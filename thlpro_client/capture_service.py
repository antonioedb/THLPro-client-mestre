from __future__ import annotations




import logging
from threading import Event, Lock
from typing import Any




from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.rtd_client import BaseRTDClient
from thlpro_client.timezone_utils import now_iso_sp





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
        simulation_mode: bool,
    ):
        self.logger = logger
        self.rtd_client = rtd_client
        self.deduplicator = deduplicator
        self.queue_enqueue = queue_enqueue
        self.simulation_mode = simulation_mode



        self._stop = Event()
        self._pause = Event()
        self._pause.set()



        self._lock = Lock()
        self._last_values: dict[str, dict[str, Any]] = {}
        self._meta_by_rtd: dict[str, dict[str, Any]] = {}



        # Séries recebidas do backend, mas ainda não assinadas no RTD.
        self._pending_series: list[dict[str, Any]] = []



        # Séries já assinadas.
        self._configured_symbols: set[str] = set()





    def set_pending_config(self, config_payload: dict[str, Any]) -> None:
        """
        Recebe a configuração do backend e coloca as séries novas
        na fila de assinatura.



        A assinatura é feita aos poucos pelo capture_worker,
        no mesmo thread do Excel/RTD.
        """
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



        with self._lock:
            self._pending_series.extend(new_series)



        self.logger.info(
            "Configuração recebida: %s novas séries pendentes de assinatura.",
            len(new_series),
        )





    def _configure_batch(self, batch_size: int = 100) -> int:
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
            # Assina um lote de séries no mesmo thread do Excel/RTD.
            configured = self._configure_batch(batch_size=100)



            if configured:
                self.logger.info(
                    "Assinadas %s novas séries. Pendentes: %s",
                    configured,
                    len(self._pending_series),
                )



            if self._pause.is_set():
                self._stop.wait(0.2)
                continue



            updates = self.rtd_client.poll_updates(timeout_seconds=0.5)
            rows: list[dict[str, Any]] = []



            with self._lock:
                for upd in updates:
                    meta = self._meta_by_rtd.get(upd.rtd_symbol)



                    if not meta:
                        continue



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



                    # Não envia enquanto não houver nenhum dado útil
                    if last_price is None and bid is None and ask is None:
                        continue



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



            if rows:
                inserted = self.queue_enqueue(rows)



                self.logger.info(
                    "Captura: %s atualizações relevantes enfileiradas. Novas na fila: %s",
                    len(rows),
                    inserted,
                )