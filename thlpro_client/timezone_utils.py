from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


def now_iso_sp() -> str:
    return datetime.now(SAO_PAULO_TZ).isoformat(timespec="seconds")
