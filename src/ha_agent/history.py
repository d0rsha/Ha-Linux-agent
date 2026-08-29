from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

from .models import ToolDefinition


_PERIOD_SECONDS = {
    "5minute": 300,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2419200,
    "year": 31536000,
}
_ALLOWED_STAT_TYPES = {"change", "max", "mean", "min", "state", "sum"}


def derive_ha_base_url(mcp_url: str) -> str:
    parsed = urlsplit(mcp_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("HA_MCP_URL must be an absolute http(s) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be RFC3339/ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sample(rows: list[Any], limit: int) -> tuple[list[Any], bool]:
    if len(rows) <= limit:
        return rows, False
    if limit <= 1:
        return [rows[-1]], True
    indexes = {round(i * (len(rows) - 1) / (limit - 1)) for i in range(limit)}
    return [rows[i] for i in sorted(indexes)], True


class HomeAssistantHistory:
    """Read-only access to Home Assistant Recorder history and statistics APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        max_entities: int = 5,
        max_history_days: int = 14,
        max_statistics_days: int = 3650,
        max_points: int = 2000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_entities = max_entities
        self.max_history_days = max_history_days
        self.max_statistics_days = max_statistics_days
        self.max_points = max_points
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "HomeAssistantHistory":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._http.aclose()

    @property
    def websocket_url(self) -> str:
        parsed = urlsplit(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, "/api/websocket", "", ""))

    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="GetHistory",
                description=(
                    "Get recent Home Assistant Recorder state history for one or more entity IDs. "
                    "Use for recent state changes and availability/offline events. Read-only. "
                    "Times must be RFC3339 with timezone."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "entity_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": self.max_entities,
                        },
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "significant_changes_only": {"type": "boolean", "default": True},
                    },
                    "required": ["entity_ids", "start_time"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="ListStatistics",
                description=(
                    "List Home Assistant long-term statistic IDs and metadata. "
                    "Use this before GetStatistics when the statistic ID is uncertain. Read-only."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "statistic_type": {"type": "string", "enum": ["mean", "sum"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="GetStatistics",
                description=(
                    "Get Home Assistant long-term Recorder statistics for one or more statistic IDs. "
                    "Use for long-range temperature, energy, water, or other statistic-capable sensors. "
                    "Read-only. Choose a coarser period for long ranges."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "statistic_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": self.max_entities,
                        },
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "period": {"type": "string", "enum": list(_PERIOD_SECONDS)},
                        "types": {
                            "type": "array",
                            "items": {"type": "string", "enum": sorted(_ALLOWED_STAT_TYPES)},
                        },
                    },
                    "required": ["statistic_ids", "start_time", "period"],
                    "additionalProperties": False,
                },
            ),
        ]

    def handles(self, tool_name: str) -> bool:
        return tool_name in {"GetHistory", "ListStatistics", "GetStatistics"}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "GetHistory":
            result = await self.get_history(**arguments)
        elif tool_name == "ListStatistics":
            result = await self.list_statistics(**arguments)
        elif tool_name == "GetStatistics":
            result = await self.get_statistics(**arguments)
        else:
            raise ValueError(f"Unknown history tool: {tool_name}")
        return json.dumps(result, separators=(",", ":"), ensure_ascii=False)

    def _validate_entities(self, values: list[str], field: str) -> list[str]:
        if not values:
            raise ValueError(f"{field} must contain at least one ID")
        if len(values) > self.max_entities:
            raise ValueError(f"{field} exceeds configured limit of {self.max_entities}")
        clean = [item.strip() for item in values if item.strip()]
        if len(clean) != len(values):
            raise ValueError(f"{field} contains an empty ID")
        return clean

    def _validate_range(
        self, start_time: str, end_time: str | None, max_days: int
    ) -> tuple[datetime, datetime]:
        start = _parse_time(start_time, "start_time")
        end = _parse_time(end_time, "end_time") if end_time else datetime.now(UTC)
        if end <= start:
            raise ValueError("end_time must be later than start_time")
        if (end - start).total_seconds() > max_days * 86400:
            raise ValueError(f"requested range exceeds configured limit of {max_days} days")
        return start, end

    async def get_history(
        self,
        entity_ids: list[str],
        start_time: str,
        end_time: str | None = None,
        significant_changes_only: bool = True,
    ) -> dict[str, Any]:
        entity_ids = self._validate_entities(entity_ids, "entity_ids")
        start, end = self._validate_range(start_time, end_time, self.max_history_days)
        params: dict[str, str] = {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": _format_time(end),
            "minimal_response": "",
            "no_attributes": "",
        }
        if significant_changes_only:
            params["significant_changes_only"] = ""
        response = await self._http.get(
            f"{self.base_url}/api/history/period/{_format_time(start)}", params=params
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Home Assistant history API returned an unexpected payload")
        per_entity_limit = max(2, self.max_points // max(1, len(payload)))
        sampled: list[list[Any]] = []
        truncated = False
        total_source_points = 0
        for series in payload:
            rows = series if isinstance(series, list) else []
            total_source_points += len(rows)
            selected, was_truncated = _sample(rows, per_entity_limit)
            sampled.append(selected)
            truncated = truncated or was_truncated
        return {
            "source": "home_assistant_recorder",
            "start_time": _format_time(start),
            "end_time": _format_time(end),
            "entity_ids": entity_ids,
            "series": sampled,
            "source_points": total_source_points,
            "returned_points": sum(len(item) for item in sampled),
            "truncated": truncated,
        }

    async def _ws_command(self, message: dict[str, Any]) -> Any:
        async with connect(
            self.websocket_url, open_timeout=30, close_timeout=10, max_size=8 * 1024 * 1024
        ) as websocket:
            hello = json.loads(await websocket.recv())
            if hello.get("type") != "auth_required":
                raise RuntimeError("Unexpected Home Assistant WebSocket greeting")
            await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(await websocket.recv())
            if auth.get("type") != "auth_ok":
                raise PermissionError(f"Home Assistant WebSocket authentication failed: {auth}")
            await websocket.send(json.dumps({"id": 1, **message}))
            while True:
                result = json.loads(await websocket.recv())
                if result.get("id") != 1 or result.get("type") != "result":
                    continue
                if not result.get("success"):
                    error = result.get("error") or {}
                    raise RuntimeError(
                        f"Home Assistant WebSocket error: {error.get('code', 'unknown')}: "
                        f"{error.get('message', 'unknown error')}"
                    )
                return result.get("result")

    async def list_statistics(
        self, query: str | None = None, statistic_type: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        message: dict[str, Any] = {"type": "recorder/list_statistic_ids"}
        if statistic_type:
            if statistic_type not in {"mean", "sum"}:
                raise ValueError("statistic_type must be mean or sum")
            message["statistic_type"] = statistic_type
        result = await self._ws_command(message)
        rows = result if isinstance(result, list) else []
        if query:
            needle = query.lower().strip()
            rows = [
                row for row in rows
                if needle in str(row.get("statistic_id", "")).lower()
                or needle in str(row.get("name", "")).lower()
            ]
        total_matches = len(rows)
        return {
            "source": "home_assistant_long_term_statistics",
            "matches": rows[:limit],
            "total_matches": total_matches,
            "returned": min(total_matches, limit),
            "truncated": total_matches > limit,
        }

    async def get_statistics(
        self,
        statistic_ids: list[str],
        start_time: str,
        period: str,
        end_time: str | None = None,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        statistic_ids = self._validate_entities(statistic_ids, "statistic_ids")
        if period not in _PERIOD_SECONDS:
            raise ValueError(f"Unsupported period: {period}")
        start, end = self._validate_range(start_time, end_time, self.max_statistics_days)
        selected_types = set(types or ["change", "max", "mean", "min", "state", "sum"])
        unknown_types = selected_types - _ALLOWED_STAT_TYPES
        if unknown_types:
            raise ValueError(f"Unsupported statistic types: {sorted(unknown_types)}")
        estimated_rows = int((end - start).total_seconds() / _PERIOD_SECONDS[period]) + 2
        estimated_points = estimated_rows * len(statistic_ids)
        if estimated_points > self.max_points * 2:
            raise ValueError(
                "requested statistics range/period is too detailed; choose a coarser period "
                f"(estimated {estimated_points} points, limit {self.max_points * 2})"
            )
        result = await self._ws_command({
            "type": "recorder/statistics_during_period",
            "start_time": _format_time(start),
            "end_time": _format_time(end),
            "statistic_ids": statistic_ids,
            "period": period,
            "types": sorted(selected_types),
        })
        payload = result if isinstance(result, dict) else {}
        per_series_limit = max(2, self.max_points // max(1, len(statistic_ids)))
        sampled: dict[str, list[Any]] = {}
        truncated = False
        source_points = 0
        for statistic_id in statistic_ids:
            rows = payload.get(statistic_id, [])
            rows = rows if isinstance(rows, list) else []
            source_points += len(rows)
            selected, was_truncated = _sample(rows, per_series_limit)
            sampled[statistic_id] = selected
            truncated = truncated or was_truncated
        return {
            "source": "home_assistant_long_term_statistics",
            "start_time": _format_time(start),
            "end_time": _format_time(end),
            "period": period,
            "statistic_ids": statistic_ids,
            "types": sorted(selected_types),
            "series": sampled,
            "source_points": source_points,
            "returned_points": sum(len(item) for item in sampled.values()),
            "truncated": truncated,
        }
