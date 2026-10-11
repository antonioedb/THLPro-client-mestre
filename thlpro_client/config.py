from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from thlpro_client.compat_windows import protect_data, unprotect_data


@dataclass
class ClientConfig:
    server_url: str = "http://localhost:8000"
    email: str = ""
    client_name: str = "THLPro Local"
    computer_name: str = ""
    simulate: bool = False
    min_send_interval_ms: int = 500
    heartbeat_seconds: int = 30
    poll_config_seconds: int = 60
    encrypted_api_key: str = ""

    @property
    def has_api_key(self) -> bool:
        return bool(self.encrypted_api_key)


@dataclass
class RuntimeSecrets:
    password: str = ""
    jwt_token: str = ""
    api_key: str = ""


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> ClientConfig:
        if not self.path.exists():
            return ClientConfig()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        cfg = ClientConfig(**payload)
        return cfg

    def save(self, config: ClientConfig) -> None:
        self.path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")

    def set_api_key(self, config: ClientConfig, api_key: str) -> ClientConfig:
        config.encrypted_api_key = protect_data(api_key)
        self.save(config)
        return config

    def read_api_key(self, config: ClientConfig) -> str:
        if not config.encrypted_api_key:
            return ""
        return unprotect_data(config.encrypted_api_key)
