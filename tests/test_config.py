from ha_agent.config import Settings


def base(**overrides):
    data = {"ha_mcp_url": "http://ha/api/mcp/assist", "ha_token": "token", "openai_api_key": "openai-key"}
    data.update(overrides)
    return Settings(**data)


def test_v01_openai_environment_remains_supported():
    settings = base(openai_model="gpt-test")
    assert settings.llm_provider == "openai"
    assert settings.provider_api_key == "openai-key"
    assert settings.provider_model == "gpt-test"
    assert settings.provider_api_style == "responses"


def test_openrouter_defaults_to_responses_endpoint():
    settings = base(llm_provider="openrouter", openrouter_api_key="or-key", llm_model="openai/gpt-5.2", openai_api_key=None)
    assert settings.provider_api_key == "or-key"
    assert settings.provider_base_url == "https://openrouter.ai/api/v1"
    assert settings.provider_api_style == "responses"


def test_generic_compatible_defaults_to_chat_completions():
    settings = base(llm_provider="openai-compatible", llm_api_key="local", llm_model="my-model", llm_base_url="http://localhost:8080/v1/")
    assert settings.provider_base_url == "http://localhost:8080/v1"
    assert settings.provider_api_style == "chat_completions"
