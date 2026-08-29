from pathlib import Path

import pytest

from ha_agent.reporting import ReportAlreadyRunning, exclusive_lock, load_report_prompt


def test_report_prompt_anomaly_mode_adds_no_alert_contract(tmp_path: Path):
    prompt = tmp_path / "report.md"
    prompt.write_text("Check the house.", encoding="utf-8")
    text = load_report_prompt(str(prompt), anomalies_only=True)
    assert "Check the house." in text
    assert "NO_ALERT" in text


def test_report_prompt_must_not_be_empty(tmp_path: Path):
    prompt = tmp_path / "report.md"
    prompt.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_report_prompt(str(prompt))


def test_report_lock_prevents_overlap(tmp_path: Path):
    lock = str(tmp_path / "report.lock")
    with exclusive_lock(lock):
        with pytest.raises(ReportAlreadyRunning):
            with exclusive_lock(lock):
                pass
