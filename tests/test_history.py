import asyncio

import pytest

from ha_agent.history import HomeAssistantHistory, _sample, derive_ha_base_url


def test_derive_ha_base_url_from_mcp_url():
    assert derive_ha_base_url("http://192.168.1.5:8123/api/mcp/assist") == "http://192.168.1.5:8123"


def test_sample_preserves_bounds():
    rows = list(range(100))
    sampled, truncated = _sample(rows, 10)
    assert truncated is True
    assert sampled[0] == 0
    assert sampled[-1] == 99
    assert len(sampled) <= 10


def test_history_tool_definitions_are_read_tools():
    history = HomeAssistantHistory(base_url="http://ha.local:8123", token="test")
    try:
        names = {tool.name for tool in history.tool_definitions()}
        assert names == {"GetHistory", "GetStatistics", "ListStatistics"}
    finally:
        asyncio.run(history._http.aclose())


def test_history_range_requires_timezone():
    history = HomeAssistantHistory(base_url="http://ha.local:8123", token="test")
    try:
        with pytest.raises(ValueError, match="timezone"):
            history._validate_range("2026-08-01T00:00:00", None, 14)
    finally:
        asyncio.run(history._http.aclose())


def test_statistics_rejects_too_detailed_range():
    history = HomeAssistantHistory(base_url="http://ha.local:8123", token="test", max_points=100)

    async def run():
        with pytest.raises(ValueError, match="too detailed"):
            await history.get_statistics(
                statistic_ids=["sensor.energy"],
                start_time="2026-01-01T00:00:00Z",
                end_time="2026-08-01T00:00:00Z",
                period="5minute",
            )
        await history._http.aclose()

    asyncio.run(run())


class FakeHistory(HomeAssistantHistory):
    async def _ws_command(self, message):
        if message["type"] == "recorder/list_statistic_ids":
            return [
                {"statistic_id": "sensor.indoor_temperature", "name": "Indoor"},
                {"statistic_id": "sensor.energy_total", "name": "Energy"},
            ]
        if message["type"] == "recorder/statistics_during_period":
            return {
                "sensor.indoor_temperature": [
                    {"start": 1, "mean": 20.0},
                    {"start": 2, "mean": 21.0},
                ]
            }
        raise AssertionError(message)


def test_list_statistics_filters_results():
    history = FakeHistory(base_url="http://ha.local:8123", token="test")

    async def run():
        result = await history.list_statistics(query="temperature")
        assert result["total_matches"] == 1
        assert result["matches"][0]["statistic_id"] == "sensor.indoor_temperature"
        await history._http.aclose()

    asyncio.run(run())


def test_get_statistics_returns_bounded_series():
    history = FakeHistory(base_url="http://ha.local:8123", token="test")

    async def run():
        result = await history.get_statistics(
            statistic_ids=["sensor.indoor_temperature"],
            start_time="2026-08-01T00:00:00Z",
            end_time="2026-08-02T00:00:00Z",
            period="hour",
            types=["mean"],
        )
        assert result["source"] == "home_assistant_long_term_statistics"
        assert len(result["series"]["sensor.indoor_temperature"]) == 2
        assert result["truncated"] is False
        await history._http.aclose()

    asyncio.run(run())
