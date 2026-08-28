from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_mcp_url: str
    ha_token: str
    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"
    max_tool_rounds: int = 8
