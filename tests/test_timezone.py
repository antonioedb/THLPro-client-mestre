from datetime import datetime

from thlpro_client.timezone_utils import now_iso_sp


def test_timestamp_has_offset():
    ts = now_iso_sp()
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None
