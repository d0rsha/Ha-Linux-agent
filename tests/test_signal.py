import pytest

from ha_agent.config import Settings
from ha_agent.signal import SignalBot


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ha_mcp_url": "http://homeassistant.local:8123/api/mcp/assist",
        "ha_token": "test-token",
    }
    values.update(overrides)
    return Settings(**values)


def test_signal_configuration_is_optional_for_base_settings() -> None:
    settings = _settings()

    assert settings.signal_api_url is None
    assert settings.signal_number is None
    assert settings.signal_allowed_sender_set == frozenset()


def test_signal_transport_requires_api_url() -> None:
    settings = _settings(
        signal_number="+46000000000",
        signal_allowed_senders="+46000000001",
    )

    with pytest.raises(ValueError, match="SIGNAL_API_URL"):
        SignalBot(settings)


def test_signal_transport_requires_number() -> None:
    settings = _settings(
        signal_api_url="http://signal-api:8080",
        signal_allowed_senders="+46000000001",
    )

    with pytest.raises(ValueError, match="SIGNAL_NUMBER"):
        SignalBot(settings)


def test_signal_transport_requires_explicit_sender_allowlist() -> None:
    settings = _settings(
        signal_api_url="http://signal-api:8080",
        signal_number="+46000000000",
    )

    with pytest.raises(ValueError, match="SIGNAL_ALLOWED_SENDERS"):
        SignalBot(settings)


def test_extract_signal_message() -> None:
    assert SignalBot._extract_message(
        {
            "sourceNumber": "+46000000001",
            "dataMessage": {"message": "hello"},
        }
    ) == ("+46000000001", "hello")
