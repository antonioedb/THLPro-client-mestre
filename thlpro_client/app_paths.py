from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "THLPro"
CLIENT_MUTEX_NAME = "Global\THLProClient"


def get_appdata_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / ".thlpro"


def ensure_app_dirs() -> dict[str, Path]:
    root = get_appdata_dir()
    logs = root / "logs"
    root.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "logs": logs,
        "config": root / "config.json",
        "queue": root / "queue.db",
    }
