from thlpro_client.dedup_cache import QuoteDeduplicator


def test_dedup_only_on_changes():
    dedup = QuoteDeduplicator(min_interval_ms=0)
    payload = {
        "option_symbol": "BOVAJ185",
        "last_price": 1.2,
        "bid": 1.1,
        "ask": 1.3,
        "quote_timestamp": "2026-10-08T10:00:00-03:00",
    }
    assert dedup.should_send(payload) is True
    assert dedup.should_send(payload) is False

    payload2 = dict(payload)
    payload2["last_price"] = 1.21
    payload2["quote_timestamp"] = "2026-10-08T10:00:01-03:00"
    assert dedup.should_send(payload2) is True
