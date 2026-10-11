from pathlib import Path

from thlpro_client.queue_store import OfflineQueue


def test_queue_enqueue_dequeue_ack(tmp_path: Path):
    q = OfflineQueue(tmp_path / "queue.db")
    rows = [
        {"option_symbol": "BOVAJ185", "quote_timestamp": "2026-10-08T10:00:00-03:00", "last_price": 1.23},
        {"option_symbol": "BOVAJ185", "quote_timestamp": "2026-10-08T10:00:01-03:00", "last_price": 1.24},
    ]
    assert q.enqueue_many(rows) == 2
    assert q.enqueue_many(rows) == 0
    assert q.size() == 2

    batch = q.dequeue_batch(10)
    assert len(batch) == 2
    q.ack_ids([batch[0][0]])
    assert q.size() == 1
