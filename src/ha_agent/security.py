from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


_COMMON_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)=([^&\s]+)"),
]


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def redact_text(value: str, secrets: list[str] | tuple[str, ...] | set[str] = ()) -> str:
    redacted = value
    for pattern in _COMMON_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def redact_data(value: Any, secrets: list[str] | tuple[str, ...] | set[str] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, dict):
        return {str(key): redact_data(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item, secrets) for item in value)
    return value


def wrap_untrusted_tool_output(tool_name: str, output: str) -> str:
    escaped = output.replace("]]>", "]]&gt;")
    return (
        f'<untrusted_tool_output tool="{tool_name}"><![CDATA[\n'
        f"{escaped}\n"
        "]]></untrusted_tool_output>"
    )


def append_audit_jsonl(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
