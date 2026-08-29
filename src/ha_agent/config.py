from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_mcp_url: str
    ha_token: str
    ha_base_url: str | None = None

    llm_provider: Literal["openai", "openrouter", "openai-compatible"] = "openai"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_style: Literal["responses", "chat_completions"] | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    openrouter_api_key: str | None = None

    max_tool_rounds: int = 8

    ha_history_enabled: bool = True
    ha_history_max_entities: int = 5
    ha_history_max_days: int = 14
    ha_statistics_max_days: int = 3650
    ha_history_max_points: int = 2000

    ha_write_enabled: bool = False
    ha_safe_write_tools: str = ""
    ha_sensitive_write_tools: str = ""
    ha_admin_tools: str = ""
    ha_read_tool_prefixes: str = "Get,List,Read,Search,Query,Fetch,Check"
    ha_read_tools: str = "HassTimerStatus"
    ha_sensitive_domains: str = "lock,alarm_control_panel"
    ha_sensitive_name_terms: str = "lock,alarm,garage,front door,back door"

    @staticmethod
    def _csv(value: str) -> frozenset[str]:
        return frozenset(item.strip() for item in value.split(",") if item.strip())

    @property
    def resolved_ha_base_url(self) -> str:
        if self.ha_base_url:
            return self.ha_base_url.rstrip("/")
        parsed = urlsplit(self.ha_mcp_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("HA_MCP_URL must be an absolute http(s) URL")
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")

    @property
    def provider_api_key(self) -> str:
        if self.llm_api_key:
            return self.llm_api_key
        if self.llm_provider == "openrouter" and self.openrouter_api_key:
            return self.openrouter_api_key
        if self.openai_api_key:
            return self.openai_api_key
        raise ValueError(f"No API key configured for LLM_PROVIDER={self.llm_provider}")

    @property
    def provider_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        if self.llm_provider == "openai":
            return self.openai_model or "gpt-5.4-mini"
        raise ValueError(f"LLM_MODEL is required for LLM_PROVIDER={self.llm_provider}")

    @property
    def provider_base_url(self) -> str | None:
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        if self.llm_provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return None

    @property
    def provider_api_style(self) -> Literal["responses", "chat_completions"]:
        if self.llm_api_style:
            return self.llm_api_style
        if self.llm_provider in {"openai", "openrouter"}:
            return "responses"
        return "chat_completions"

    @property
    def safe_write_tools(self) -> frozenset[str]:
        return self._csv(self.ha_safe_write_tools)

    @property
    def sensitive_write_tools(self) -> frozenset[str]:
        return self._csv(self.ha_sensitive_write_tools)

    @property
    def admin_tools(self) -> frozenset[str]:
        return self._csv(self.ha_admin_tools)

    @property
    def read_tools(self) -> frozenset[str]:
        return self._csv(self.ha_read_tools)

    @property
    def read_tool_prefixes(self) -> tuple[str, ...]:
        return tuple(self._csv(self.ha_read_tool_prefixes))

    @property
    def sensitive_domains(self) -> frozenset[str]:
        return frozenset(item.lower() for item in self._csv(self.ha_sensitive_domains))

    @property
    def sensitive_name_terms(self) -> frozenset[str]:
        return frozenset(item.lower() for item in self._csv(self.ha_sensitive_name_terms))
