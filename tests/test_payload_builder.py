from thlpro_client.capture_service import map_series_by_rtd


def test_map_series_infers_asset_from_symbol_prefix():
    cfg = {
        "assets": [{"symbol": "BOVA11"}, {"symbol": "ABEV3"}],
        "active_series": [
            {
                "option_symbol": "BOVAJ185",
                "option_type": "CALL",
                "strike": "185",
                "expiration_date": "2026-10-16",
                "rtd_symbol": "BOVAJ185_B_0",
            }
        ],
    }
    result = map_series_by_rtd(cfg)
    assert result["BOVAJ185_B_0"]["asset"] == "BOVA11"
