from thlpro_client.models import SendResult


def test_send_result_mapping():
    body = {"accepted": 3, "rejected": [{"symbol": "X", "reason": "old_timestamp"}]}
    r = SendResult(accepted=body["accepted"], rejected=body["rejected"])
    assert r.accepted == 3
    assert r.rejected[0]["reason"] == "old_timestamp"
