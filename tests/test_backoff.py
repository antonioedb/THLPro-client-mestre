from thlpro_client.api_client import compute_backoff_seconds


def test_backoff_exponential_with_cap():
    assert compute_backoff_seconds(1) == 1.0
    assert compute_backoff_seconds(2) == 2.0
    assert compute_backoff_seconds(3) == 4.0
    assert compute_backoff_seconds(10) == 30.0
