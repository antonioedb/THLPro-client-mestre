from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests

from thlpro_client.models import SendResult


class APIError(Exception):
    pass


def compute_backoff_seconds(
    attempt: int,
    base: float = 1.0,
    cap: float = 30.0,
) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1)))


@dataclass
class THLProAPIClient:
    base_url: str
    timeout: float = 8.0
    token: str = ""
    api_key: str = ""

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _headers_user(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _headers_client(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def login(self, email: str, password: str) -> str:
        response = requests.post(
            self._url("/auth/login"),
            json={"email": email, "password": password},
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha no login: {response.status_code} {response.text}"
            )

        token = response.json()["access_token"]
        self.token = token
        return token

    def register_client(
        self,
        client_name: str,
        computer_name: str,
        version: str,
    ) -> dict[str, Any]:
        payload = {
            "client_name": client_name,
            "computer_name": computer_name,
            "version": version,
        }

        response = requests.post(
            self._url("/clients/register"),
            json=payload,
            headers=self._headers_user(),
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha no registro: {response.status_code} {response.text}"
            )

        body = response.json()
        self.api_key = body["api_key"]
        return body

    def get_config(
        self,
        include_series: bool = True,
        spots: dict[str, float | Decimal] | None = None,
    ) -> dict[str, Any]:
        """
        Busca a configuração de captura.

        Primeira chamada:
            get_config(include_series=False)

        Após o cliente obter ULT dos ativos-base:
            get_config(
                include_series=True,
                spots={"BOVA11": 200.00, "ABEV3": 14.50},
            )

        O backend recebe spots em parâmetros repetidos:
            ?spot=BOVA11:200.00&spot=ABEV3:14.50
        """
        params: list[tuple[str, str]] = [
            ("include_series", str(include_series).lower()),
        ]

        for symbol, value in (spots or {}).items():
            normalized_symbol = str(symbol).strip().upper()

            if not normalized_symbol:
                continue

            try:
                price = Decimal(str(value))
            except Exception:
                continue

            if price <= 0:
                continue

            params.append(
                (
                    "spot",
                    f"{normalized_symbol}:{price}",
                )
            )

        response = requests.get(
            self._url("/clients/config"),
            params=params,
            headers=self._headers_client(),
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha ao obter config: "
                f"{response.status_code} {response.text}"
            )

        return response.json()

    def heartbeat(self) -> dict[str, Any]:
        response = requests.post(
            self._url("/clients/heartbeat"),
            headers=self._headers_client(),
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha heartbeat: {response.status_code} {response.text}"
            )

        return response.json()

    def send_quotes(self, rows: list[dict[str, Any]]) -> SendResult:
        response = requests.post(
            self._url("/clients/quotes"),
            json=rows,
            headers=self._headers_client(),
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha envio quotes: "
                f"{response.status_code} {response.text}"
            )

        body = response.json()

        return SendResult(
            accepted=body.get("accepted", 0),
            rejected=body.get("rejected", []),
        )

    def send_asset_quotes(
        self,
        rows: list[dict[str, Any]],
    ) -> SendResult:
        """
        Envia cotações dos ativos-base, como BOVA11 e ABEV3.

        Usa a API key do cliente quando disponível; durante o registro,
        pode usar o JWT do usuário.
        """
        headers = (
            self._headers_client()
            if self.api_key
            else self._headers_user()
        )

        if not headers.get("Authorization"):
            raise APIError(
                "Nenhuma credencial disponível para enviar "
                "cotações de ativos."
            )

        response = requests.post(
            self._url("/assets/quotes"),
            json=rows,
            headers=headers,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise APIError(
                f"Falha envio asset quotes: "
                f"{response.status_code} {response.text}"
            )

        body = response.json()

        return SendResult(
            accepted=body.get("accepted", 0),
            rejected=body.get("rejected", []),
        )