from __future__ import annotations





import abc
import logging
import random
import time
from dataclasses import dataclass
from typing import Iterable





import requests





from thlpro_client.compat_windows import IS_WINDOWS
from thlpro_client.timezone_utils import now_iso_sp





try:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
except Exception:  # pragma: no cover
    pythoncom = None
    win32com = None






@dataclass(slots=True)
class RTDUpdate:
    rtd_symbol: str
    field: str
    value: float | str | None
    timestamp: str






class BaseRTDClient(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> None:
        raise NotImplementedError




    @abc.abstractmethod
    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        raise NotImplementedError




    @abc.abstractmethod
    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        raise NotImplementedError




    @abc.abstractmethod
    def close(self) -> None:
        raise NotImplementedError




    def register_meta(self, option_series_id: int, rtd_symbol: str) -> None:
        """Opcional: registra metadados da série no cliente RTD."""
        return None




    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        """Assina várias séries. O padrão assina uma por uma."""
        configured = []


        for rtd_symbol in rtd_symbols:
            self.subscribe(rtd_symbol, fields)


            configured.append(rtd_symbol)


        return configured






class ComRTDClient(BaseRTDClient):
    """Leitura direta do RTD COM do Profit (mantida para referência/fallback)."""




    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._connected = False
        self._subs: set[tuple[str, str]] = set()
        self._server = None




    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError(
                "COM RTD só disponível em Windows com pywin32 instalado."
            )




        pythoncom.CoInitialize()
        self._server = win32com.client.Dispatch("rtdtrading.rtdserver")
        self._connected = True
        self.logger.info("Conectado ao servidor COM rtdtrading.rtdserver")




    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        for field in fields:
            self._subs.add((rtd_symbol, field))




    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        if not self._connected:
            return []




        time.sleep(timeout_seconds)
        return []




    def close(self) -> None:
        self._connected = False
        self._subs.clear()
        self._server = None




        if IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()






class ExcelBridgeRTDClient(BaseRTDClient):
    """
    Lê o RTD do Profit através de uma instância oculta do Excel.




    A fórmula usada é:
    =RTD("rtdtrading.rtdserver";;"TICKER_DA_OPÇÃO";"CAMPO")
    """




    def __init__(
        self,
        logger: logging.Logger,
        server_url: str = "",
        api_key: str = "",
    ):
        self.logger = logger
        self.server_url = server_url
        self.api_key = api_key




        self._excel = None
        self._wb = None
        self._ws = None




        # (symbol, field) -> célula
        self._subs: dict[tuple[str, str], str] = {}




        # rtd_symbol -> option_series_id
        self._meta_by_symbol: dict[str, int] = {}




        self._row = 1




    def set_credentials(self, server_url: str, api_key: str) -> None:
        self.server_url = server_url
        self.api_key = api_key




    def register_meta(
        self,
        option_series_id: int,
        rtd_symbol: str,
    ) -> None:
        self._meta_by_symbol[rtd_symbol] = option_series_id




    def _acquire_lease(self, option_series_id: int) -> bool:
        if not (self.server_url and self.api_key):
            return True




        try:
            resp = requests.post(
                f"{self.server_url}/clients/lease/acquire",
                params={"option_series_id": option_series_id},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=8,
            )
            return resp.status_code == 200
        except requests.RequestException as exc:
            self.logger.warning(
                "Falha ao adquirir lease para %s: %s",
                option_series_id,
                exc,
            )
            return False




    def _acquire_leases_batch(
        self,
        option_series_ids: list[int],
    ) -> list[int]:
        if not (self.server_url and self.api_key):
            return option_series_ids




        if not option_series_ids:
            return []




        try:
            resp = requests.post(
                f"{self.server_url}/clients/lease/acquire-batch",
                json={"option_series_ids": option_series_ids},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )


            if resp.status_code != 200:
                self.logger.warning(
                    "Falha ao adquirir leases em lote: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return []


            body = resp.json()
            return body.get("acquired", [])


        except requests.RequestException as exc:
            self.logger.warning(
                "Falha ao adquirir leases em lote: %s",
                exc,
            )
            return []




    def _release_lease(self, option_series_id: int) -> None:
        if not (self.server_url and self.api_key):
            return




        try:
            requests.post(
                f"{self.server_url}/clients/lease/release",
                params={"option_series_id": option_series_id},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=8,
            )
        except requests.RequestException as exc:
            self.logger.warning(
                "Falha ao liberar lease para %s: %s",
                option_series_id,
                exc,
            )




    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError(
                "COM RTD só disponível em Windows com pywin32 instalado."
            )




        # Evita criar uma nova pasta do Excel quando já existe uma conexão.
        if self._excel is not None and self._wb is not None and self._ws is not None:
            return




        pythoncom.CoInitialize()




        # DispatchEx cria uma instância nova, sem interferir no Excel do usuário.
        self._excel = win32com.client.DispatchEx("Excel.Application")
        self._excel.Visible = False
        self._excel.DisplayAlerts = False
        self._excel.AskToUpdateLinks = False




        self._wb = self._excel.Workbooks.Add()
        self._ws = self._wb.Worksheets(1)




        self.logger.info("Excel oculto iniciado como ponte RTD")




    def _reset_excel(self) -> None:
        self._excel = None
        self._wb = None
        self._ws = None




    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        self.subscribe_batch([rtd_symbol], fields)




    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        fields = list(fields)


        option_series_ids: list[int] = []
        symbol_by_id: dict[int, str] = {}


        for rtd_symbol in rtd_symbols:
            option_series_id = self._meta_by_symbol.get(rtd_symbol)


            if option_series_id is None:
                self.logger.warning(
                    "Sem meta para %s, assumindo lease local",
                    rtd_symbol,
                )
                option_series_id = 0


            option_series_ids.append(option_series_id)
            symbol_by_id[option_series_id] = rtd_symbol


        acquired_ids = self._acquire_leases_batch(option_series_ids)


        acquired_symbols = [
            symbol_by_id[option_series_id]
            for option_series_id in acquired_ids
            if option_series_id in symbol_by_id
        ]


        # Garante que o Excel oculto já foi iniciado.
        self.connect()


        configured = []


        for rtd_symbol in acquired_symbols:
            formula_failed = False


            for field in fields:
                key = (rtd_symbol, field)


                if key in self._subs:
                    continue


                cell = f"A{self._row}"


                formula = (
                    f'=RTD("rtdtrading.rtdserver";;'
                    f'"{rtd_symbol}";"{field}")'
                )


                try:
                    self._ws.Range(cell).FormulaLocal = formula


                    self._subs[key] = cell
                    self._row += 1


                except Exception as exc:
                    formula_failed = True


                    self.logger.warning(
                        "Falha ao assinar %s %s em %s: %s",
                        rtd_symbol,
                        field,
                        cell,
                        exc,
                    )


                    # O Excel pode ter caído ou desconectado.
                    # Recria a ponte e interrompe este lote.
                    self._reset_excel()


                    try:
                        self.connect()
                    except Exception as reconnect_exc:
                        self.logger.error(
                            "Falha ao recriar Excel oculto: %s",
                            reconnect_exc,
                        )


                    break


            if not formula_failed:
                configured.append(rtd_symbol)


        if configured:
            self.logger.info(
                "Assinadas %s séries. Campos por série: %s",
                len(configured),
                len(fields),
            )


        return configured






    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        if not self._is_connected():
            return []




        time.sleep(timeout_seconds)




        last_row = self._row - 1




        if last_row < 1:
            return []




        try:
            values = self._ws.Range(f"A1:A{last_row}").Value
        except Exception as exc:
            self.logger.error("Falha ao ler células RTD: %s", exc)


            # Excel pode ter caído. Reseta para ser recriado no próximo lote.
            self._reset_excel()


            return []




        if values is None:
            return []




        # Excel retorna:
        # - valor simples quando há apenas uma célula
        # - tupla de tuplas quando há várias células
        if last_row == 1:
            normalized_values = [(values,)]
        else:
            normalized_values = values




        updates: list[RTDUpdate] = []
        timestamp = now_iso_sp()




        for (symbol, field), cell in self._subs.items():
            row = int(cell[1:])




            if row - 1 >= len(normalized_values):
                continue




            value = normalized_values[row - 1][0]




            if value is None:
                continue




            # Ignora erros do Excel/RTD, como #N/A, #NAME? etc.
            if isinstance(value, str) and value.startswith("#"):
                continue




            updates.append(
                RTDUpdate(
                    rtd_symbol=symbol,
                    field=field,
                    value=value,
                    timestamp=timestamp,
                )
            )





        return updates




    def _is_connected(self) -> bool:
        return (
            self._excel is not None
            and self._wb is not None
            and self._ws is not None
        )




    def close(self) -> None:
        for symbol, option_series_id in self._meta_by_symbol.items():
            self._release_lease(option_series_id)




        if self._wb:
            try:
                self._wb.Close(SaveChanges=False)
            except Exception as exc:
                self.logger.warning("Falha ao fechar pasta Excel: %s", exc)




        if self._excel:
            try:
                self._excel.Quit()
            except Exception as exc:
                self.logger.warning("Falha ao encerrar Excel: %s", exc)




        self._excel = None
        self._wb = None
        self._ws = None
        self._subs.clear()




        if IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()






class ProfitApiRtdClient(BaseRTDClient):
    """Stub documentado para API/plugin oficial da Nelogica."""




    def connect(self) -> None:
        raise NotImplementedError(
            "Integração Profit API/plugin COM ainda pendente de validação."
        )




    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        raise NotImplementedError




    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        raise NotImplementedError




    def close(self) -> None:
        return






class SimulatedRTDClient(BaseRTDClient):
    def __init__(self):
        self._subs: dict[str, dict[str, float]] = {}
        self._connected = False




    def connect(self) -> None:
        self._connected = True




    def register_meta(
        self,
        option_series_id: int,
        rtd_symbol: str,
    ) -> None:
        """Mantido para compatibilidade com o CaptureService."""
        return None




    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        base = 1.0 + random.uniform(0.1, 20)




        self._subs[rtd_symbol] = {
            "ULT": base,
            "OCP": max(0.01, base - 0.05),
            "OVD": base + 0.05,
            "VEN": 20261016,
            "PEX": random.choice([170, 175, 180, 185, 190, 195, 200]),
        }




    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        time.sleep(timeout_seconds)




        updates: list[RTDUpdate] = []




        for symbol, values in self._subs.items():
            delta = random.uniform(-0.03, 0.03)




            values["ULT"] = max(0.01, values["ULT"] + delta)
            values["OCP"] = max(0.01, values["ULT"] - 0.03)
            values["OVD"] = max(values["OCP"], values["ULT"] + 0.03)




            timestamp = now_iso_sp()




            for field in ["ULT", "OCP", "OVD"]:
                updates.append(
                    RTDUpdate(
                        rtd_symbol=symbol,
                        field=field,
                        value=round(values[field], 2),
                        timestamp=timestamp,
                    )
                )




        return updates




    def close(self) -> None:
        self._subs.clear()
        self._connected = False






def create_rtd_client(
    mode: str,
    logger: logging.Logger,
    server_url: str = "",
    api_key: str = "",
) -> BaseRTDClient:
    mode_l = mode.lower()




    if mode_l == "com":
        return ExcelBridgeRTDClient(
            logger,
            server_url=server_url,
            api_key=api_key,
        )




    if mode_l == "profit_api":
        return ProfitApiRtdClient()




    if mode_l == "simulate":
        return SimulatedRTDClient()




    raise ValueError(f"Modo RTD inválido: {mode}")