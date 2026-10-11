from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from thlpro_client.models import SendResult


class APIError(Exception):
    pass


def compute_backoff_seconds(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    return delay


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
        resp = requests.post(
            self._url("/auth/login"),
            json={"email": email, "password": password},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(f"Falha no login: {resp.status_code} {resp.text}")
        token = resp.json()["access_token"]
        self.token = token
        return token

    def register_client(self, client_name: str, computer_name: str, version: str) -> dict[str, Any]:
        payload = {
            "client_name": client_name,
            "computer_name": computer_name,
            "version": version,
        }
        resp = requests.post(
            self._url("/clients/register"),
            json=payload,
            headers=self._headers_user(),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(f"Falha no registro: {resp.status_code} {resp.text}")
        body = resp.json()
        self.api_key = body["api_key"]
        return body

    def get_config(self) -> dict[str, Any]:
        resp = requests.get(
            self._url("/clients/config"),
            headers=self._headers_client(),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(f"Falha ao obter config: {resp.status_code} {resp.text}")
        return resp.json()

    def heartbeat(self) -> dict[str, Any]:
        resp = requests.post(
            self._url("/clients/heartbeat"),
            headers=self._headers_client(),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(f"Falha heartbeat: {resp.status_code} {resp.text}")
        return resp.json()

    def send_quotes(self, rows: list[dict[str, Any]]) -> SendResult:
        resp = requests.post(
            self._url("/clients/quotes"),
            json=rows,
            headers=self._headers_client(),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(f"Falha envio quotes: {resp.status_code} {resp.text}")
        body = resp.json()
        return SendResult(
            accepted=body.get("accepted", 0),
            rejected=body.get("rejected", []),
        )

    def send_asset_quotes(self, rows: list[dict[str, Any]]) -> SendResult:
        """
        Envia cotações do ativo-base, como BOVA11 e ABEV3.

        Usa a API key do cliente; o backend aceita API key ou JWT.
        """
        headers = self._headers_client() if self.api_key else self._headers_user()

        if not headers.get("Authorization"):
            raise APIError(
                "Nenhuma credencial disponível para enviar cotações de ativos."
            )

        resp = requests.post(
            self._url("/assets/quotes"),
            json=rows,
            headers=headers,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise APIError(
                f"Falha envio asset quotes: {resp.status_code} {resp.text}"
            )
        body = resp.json()
        return SendResult(
            accepted=body.get("accepted", 0),
            rejected=body.get("rejected", []),
        )