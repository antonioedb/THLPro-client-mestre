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


LEASE_RENEW_INTERVAL_SECONDS = 300

RTD_SERVER_PROGID = "rtdtrading.rtdserver"


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
        return None

    def register_asset(self, rtd_symbol: str) -> None:
        return None

    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        configured: list[str] = []

        for rtd_symbol in rtd_symbols:
            self.subscribe(rtd_symbol, fields)
            configured.append(rtd_symbol)

        return configured


class ComProbeRTDClient(BaseRTDClient):
    """
    Diagnóstico somente.

    Cria o objeto COM RTD sem abrir Excel para confirmar que o ProgID está
    registrado. Não é um leitor de cotações: servidores RTD normalmente
    dependem do protocolo/callback do Excel.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._server = None
        self._connected = False

    def connect(self) -> None:
        if not (IS_WINDOWS and pythoncom and win32com):
            raise RuntimeError(
                "COM RTD só está disponível no Windows com pywin32 instalado."
            )

        pythoncom.CoInitialize()

        try:
            self._server = win32com.client.Dispatch(RTD_SERVER_PROGID)
        except Exception as exc:
            pythoncom.CoUninitialize()
            raise RuntimeError(
                f"Não foi possível criar o servidor COM {RTD_SERVER_PROGID}: {exc}"
            ) from exc

        self._connected = True

        self.logger.info(
            "Servidor COM %s criado sem Excel. "
            "Este modo é somente diagnóstico e não captura cotações.",
            RTD_SERVER_PROGID,
        )

        raise RuntimeError(
            "O modo com_probe confirmou o servidor COM, mas não pode "
            "capturar cotações sem o protocolo RTD/callback do Excel. "
            "Use RTD_MODE=excel_bridge, RTD_MODE=profit_api ou execute "
            "o cliente em uma máquina dedicada."
        )

    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        raise RuntimeError("com_probe não assina símbolos.")

    def poll_updates(self, timeout_seconds: float = 1.0) -> list[RTDUpdate]:
        return []

    def close(self) -> None:
        self._connected = False
        self._server = None

        if IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()


class ExcelBridgeRTDClient(BaseRTDClient):
    """
    Ponte RTD por Excel oculto.

    IMPORTANTE:
    Este modo cria uma segunda instância de EXCEL.EXE. Alguns servidores
    RTD podem conflitar com planilhas Excel abertas pelo usuário. Use apenas
    em máquina dedicada, VM, ou quando não houver planilha manual usando RTD.
    """

    def __init__(
        self,
        logger: logging.Logger,
        server_url: str = "",
        api_key: str = "",
    ):
        self.logger = logger
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

        self._excel = None
        self._wb = None
        self._ws = None

        self._subs: dict[tuple[str, str], str] = {}
        self._meta_by_symbol: dict[str, int] = {}
        self._asset_symbols: set[str] = set()

        self._leased_option_ids: set[int] = set()
        self._last_lease_renewal_at = 0.0

        self._row = 1
        self._com_initialized = False

    def set_credentials(self, server_url: str, api_key: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

    def register_meta(
        self,
        option_series_id: int,
        rtd_symbol: str,
    ) -> None:
        self._meta_by_symbol[rtd_symbol] = option_series_id

    def register_asset(self, rtd_symbol: str) -> None:
        self._asset_symbols.add(rtd_symbol)

    def _request_leases_batch(
        self,
        option_series_ids: list[int],
        action_label: str,
    ) -> list[int]:
        unique_ids = sorted(
            {
                int(option_series_id)
                for option_series_id in option_series_ids
                if option_series_id is not None and int(option_series_id) > 0
            }
        )

        if not unique_ids:
            return []

        if not (self.server_url and self.api_key):
            return unique_ids

        try:
            response = requests.post(
                f"{self.server_url}/clients/lease/acquire-batch",
                json={"option_series_ids": unique_ids},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )

            if response.status_code != 200:
                self.logger.warning(
                    "Falha ao %s leases em lote: HTTP %s: %s",
                    action_label,
                    response.status_code,
                    response.text,
                )
                return []

            body = response.json()
            acquired = body.get("acquired", [])

            if not isinstance(acquired, list):
                self.logger.warning(
                    "Resposta inválida ao %s leases em lote: %r",
                    action_label,
                    body,
                )
                return []

            return [
                int(option_series_id)
                for option_series_id in acquired
                if option_series_id is not None and int(option_series_id) > 0
            ]

        except (TypeError, ValueError) as exc:
            self.logger.warning(
                "Resposta inválida ao %s leases em lote: %s",
                action_label,
                exc,
            )
            return []

        except requests.RequestException as exc:
            self.logger.warning(
                "Falha ao %s leases em lote: %s",
                action_label,
                exc,
            )
            return []

    def _acquire_leases_batch(
        self,
        option_series_ids: list[int],
    ) -> list[int]:
        return self._request_leases_batch(
            option_series_ids,
            action_label="adquirir",
        )

    def _renew_leases_if_needed(self) -> None:
        if not (self.server_url and self.api_key):
            return

        now = time.monotonic()

        if (
            now - self._last_lease_renewal_at
            < LEASE_RENEW_INTERVAL_SECONDS
        ):
            return

        option_ids = sorted(self._leased_option_ids)

        if not option_ids:
            self._last_lease_renewal_at = now
            return

        renewed_ids = self._request_leases_batch(
            option_ids,
            action_label="renovar",
        )

        renewed_set = set(renewed_ids)
        expected_set = set(option_ids)

        self._leased_option_ids.intersection_update(renewed_set)
        self._last_lease_renewal_at = now

        failed_ids = expected_set - renewed_set

        if failed_ids:
            failed_symbols = sorted(
                symbol
                for symbol, option_series_id in self._meta_by_symbol.items()
                if option_series_id in failed_ids
            )

            examples = ", ".join(failed_symbols[:10])
            suffix = "..." if len(failed_symbols) > 10 else ""

            self.logger.warning(
                "Lease não renovado para %s opções. Exemplos: %s%s",
                len(failed_ids),
                examples,
                suffix,
            )
            return

        self.logger.info(
            "Leases renovados para %s opções.",
            len(renewed_ids),
        )

    def _release_lease(self, option_series_id: int) -> None:
        if option_series_id is None or option_series_id <= 0:
            return

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
                "Ponte Excel RTD disponível apenas em Windows com pywin32."
            )

        if self._is_connected():
            return

        if not self._com_initialized:
            pythoncom.CoInitialize()
            self._com_initialized = True

        self._excel = win32com.client.DispatchEx("Excel.Application")
        self._excel.Visible = False
        self._excel.DisplayAlerts = False
        self._excel.AskToUpdateLinks = False

        self._wb = self._excel.Workbooks.Add()
        self._ws = self._wb.Worksheets(1)

        self.logger.warning(
            "Excel oculto iniciado como ponte RTD. "
            "Não abra planilhas RTD simultaneamente nesta máquina."
        )

    def _dispose_excel(self) -> None:
        workbook = self._wb
        excel = self._excel

        self._wb = None
        self._ws = None
        self._excel = None

        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass

        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass

    def _reset_excel(self) -> None:
        self._dispose_excel()
        self._subs.clear()
        self._row = 1

    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        self.subscribe_batch([rtd_symbol], fields)

    def subscribe_batch(
        self,
        rtd_symbols: list[str],
        fields: Iterable[str],
    ) -> list[str]:
        requested_fields = list(dict.fromkeys(fields))

        if not requested_fields:
            return []

        option_symbols = [
            symbol
            for symbol in rtd_symbols
            if symbol not in self._asset_symbols
        ]

        asset_symbols = [
            symbol
            for symbol in rtd_symbols
            if symbol in self._asset_symbols
        ]

        option_ids: list[int] = []
        symbol_by_option_id: dict[int, str] = {}
        symbols_without_meta: list[str] = []

        for rtd_symbol in option_symbols:
            option_series_id = self._meta_by_symbol.get(rtd_symbol)

            if option_series_id is None or option_series_id <= 0:
                symbols_without_meta.append(rtd_symbol)
                continue

            option_ids.append(option_series_id)
            symbol_by_option_id[option_series_id] = rtd_symbol

        if symbols_without_meta:
            self.logger.warning(
                "Opções sem option_series_id não serão assinadas: %s",
                ", ".join(symbols_without_meta[:10]),
            )

        acquired_ids = set(self._acquire_leases_batch(option_ids))

        acquired_symbols = [
            symbol_by_option_id[option_series_id]
            for option_series_id in acquired_ids
            if option_series_id in symbol_by_option_id
        ]

        symbols_to_configure = acquired_symbols + asset_symbols

        if not symbols_to_configure:
            return []

        self.connect()

        configured: list[str] = []

        for rtd_symbol in symbols_to_configure:
            created_keys: list[tuple[str, str]] = []
            formula_failed = False

            for field in requested_fields:
                key = (rtd_symbol, field)

                if key in self._subs:
                    continue

                cell = f"A{self._row}"
                formula = (
                    f'=RTD("{RTD_SERVER_PROGID}";;'
                    f'"{rtd_symbol}";"{field}")'
                )

                try:
                    self._ws.Range(cell).FormulaLocal = formula
                    self._subs[key] = cell
                    created_keys.append(key)
                    self._row += 1

                except Exception as exc:
                    formula_failed = True

                    self.logger.warning(
                        "Falha ao assinar %s %s na célula %s: %s",
                        rtd_symbol,
                        field,
                        cell,
                        exc,
                    )
                    break

            if formula_failed:
                for key in created_keys:
                    self._subs.pop(key, None)

                try:
                    self._reset_excel()
                    self.connect()
                except Exception as reconnect_exc:
                    self.logger.error(
                        "Falha ao recriar Excel oculto após erro RTD: %s",
                        reconnect_exc,
                    )

                break

            all_fields_configured = all(
                (rtd_symbol, field) in self._subs
                for field in requested_fields
            )

            if not all_fields_configured:
                self.logger.warning(
                    "Assinatura incompleta de %s; será tentada novamente.",
                    rtd_symbol,
                )
                continue

            configured.append(rtd_symbol)

            option_series_id = self._meta_by_symbol.get(rtd_symbol)

            if option_series_id is not None and option_series_id > 0:
                self._leased_option_ids.add(option_series_id)

        if configured:
            self.logger.info(
                "RTD configurado: %s símbolos; %s campos por símbolo.",
                len(configured),
                len(requested_fields),
            )

        not_configured = set(rtd_symbols) - set(configured)

        if not_configured:
            examples = ", ".join(sorted(not_configured)[:10])
            suffix = "..." if len(not_configured) > 10 else ""

            self.logger.warning(
                "RTD não confirmou %s símbolos. Exemplos: %s%s",
                len(not_configured),
                examples,
                suffix,
            )

        return configured

    def poll_updates(
        self,
        timeout_seconds: float = 1.0,
    ) -> list[RTDUpdate]:
        self._renew_leases_if_needed()

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
            self._reset_excel()
            return []

        if values is None:
            return []

        normalized_values = (
            [(values,)]
            if last_row == 1
            else values
        )

        updates: list[RTDUpdate] = []
        timestamp = now_iso_sp()

        for (symbol, field), cell in list(self._subs.items()):
            row = int(cell[1:])

            if row - 1 >= len(normalized_values):
                continue

            value = normalized_values[row - 1][0]

            if value is None:
                continue

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
        for option_series_id in sorted(self._leased_option_ids):
            self._release_lease(option_series_id)

        self._leased_option_ids.clear()
        self._last_lease_renewal_at = 0.0

        self._dispose_excel()

        self._subs.clear()
        self._meta_by_symbol.clear()
        self._asset_symbols.clear()
        self._row = 1

        if self._com_initialized and IS_WINDOWS and pythoncom:
            pythoncom.CoUninitialize()
            self._com_initialized = False


class ProfitApiRtdClient(BaseRTDClient):
    """
    Placeholder para integração oficial da Nelogica.

    Este modo só deve ser habilitado quando houver documentação e credenciais
    do plugin/API compatível com sua licença do Profit.
    """

    def connect(self) -> None:
        raise NotImplementedError(
            "Integração Profit API/plugin ainda não foi implementada. "
            "Ela é a solução recomendada para operar sem Excel oculto."
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
        return None

    def register_asset(self, rtd_symbol: str) -> None:
        return None

    def subscribe(self, rtd_symbol: str, fields: Iterable[str]) -> None:
        base = 1.0 + random.uniform(0.1, 20)

        self._subs[rtd_symbol] = {
            "ULT": base,
            "OCP": max(0.01, base - 0.05),
            "OVD": base + 0.05,
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
    mode_l = mode.lower().strip()

    if mode_l in {"excel_bridge", "excel", "com"}:
        return ExcelBridgeRTDClient(
            logger,
            server_url=server_url,
            api_key=api_key,
        )

    if mode_l in {"com_probe", "probe"}:
        return ComProbeRTDClient(logger)

    if mode_l == "profit_api":
        return ProfitApiRtdClient()

    if mode_l == "simulate":
        return SimulatedRTDClient()

    raise ValueError(
        "Modo RTD inválido. Use excel_bridge, com_probe, "
        "profit_api ou simulate."
    )