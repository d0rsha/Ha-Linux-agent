import asyncio
import fcntl
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import httpx

from .agent import ask_home
from .config import Settings

LOGGER = logging.getLogger("ha_agent.report")
NO_ALERT_SENTINEL = "NO_ALERT"


class ReportAlreadyRunning(RuntimeError):
    pass


@dataclass(frozen=True)
class ReportResult:
    text: str
    delivered: bool
    suppressed: bool = False


@contextmanager
def exclusive_lock(path: str) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReportAlreadyRunning(f"another report run holds {path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_report_prompt(path: str, anomalies_only: bool = False) -> str:
    prompt = Path(path).read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"report prompt is empty: {path}")
    if anomalies_only:
        prompt += (
            "\n\nANOMALY-ONLY MODE: Send an alert only for a meaningful condition needing attention. "
            f"If no such condition exists, respond with exactly {NO_ALERT_SENTINEL}."
        )
    return prompt


async def _ask_with_retries(settings: Settings, prompt: str) -> str:
    # Scheduled reports are always read-only, independently of interactive/chat write settings.
    report_settings = settings.model_copy(update={"ha_write_enabled": False})
    attempts = settings.report_retries + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with asyncio.timeout(settings.report_timeout_seconds):
                return await ask_home(report_settings, prompt)
        except Exception as exc:  # scheduler boundary: retry transient provider/tool failures
            last_error = exc
            LOGGER.exception("report attempt %s/%s failed", attempt + 1, attempts)
            if attempt + 1 < attempts:
                await asyncio.sleep(min(2**attempt, 10))
    assert last_error is not None
    raise last_error


async def deliver_ha_notification(settings: Settings, message: str, title: str) -> bool:
    service = settings.report_notify_service.strip()
    if not service:
        return False
    service = service.removeprefix("notify.")
    url = f"{settings.resolved_ha_base_url}/api/services/notify/{service}"
    headers = {"Authorization": f"Bearer {settings.ha_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json={"title": title, "message": message})
        response.raise_for_status()
    return True


async def run_report(settings: Settings, anomalies_only: bool = False) -> ReportResult:
    prompt = load_report_prompt(settings.report_prompt_path, anomalies_only=anomalies_only)
    with exclusive_lock(settings.report_lock_path):
        text = (await _ask_with_retries(settings, prompt)).strip()
        if not text:
            raise RuntimeError("agent returned an empty report")
        if anomalies_only and text == NO_ALERT_SENTINEL:
            LOGGER.info("anomaly report suppressed: no alert condition")
            return ReportResult(text=text, delivered=False, suppressed=True)
        title = settings.report_anomaly_title if anomalies_only else settings.report_title
        delivered = await deliver_ha_notification(settings, text, title)
        return ReportResult(text=text, delivered=delivered)
