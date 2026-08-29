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

    report_prompt_path: str = "prompts/house_health.md"
    report_lock_path: str = "/data/report.lock"
    report_timeout_seconds: int = 180
    report_retries: int = 1
    report_notify_service: str = ""
    report_title: str = "Morning house health"
    report_anomaly_title: str = "House anomaly"

    telegram_bot_token: str | None = None
    telegram_allowed_users: str = ""
    chat_session_dir: str = "/data/chat"
    chat_context_messages: int = 12
    chat_min_interval_seconds: float = 2.0
    chat_sensitive_approval_ttl_seconds: int = 120

    state_enabled: bool = True
    state_db_path: str = "/data/ha-agent.db"
    conversation_retention_days: int = 30
    audit_retention_days: int = 90
    memory_context_items: int = 20

    host_diagnostics_enabled: bool = True
    host_mcp_urls: str = ""
    host_mcp_token: str | None = None
    host_mcp_bind: str = "127.0.0.1"
    host_mcp_port: int = 8750
    host_proc_root: str = "/proc"
    host_disk_paths: str = "/"
    host_service_allowlist: str = ""
    host_docker_socket: str = ""
    host_docker_allowlist: str = ""
    host_log_paths: str = ""
    host_journal_units: str = ""
    host_log_max_bytes: int = 65536
    host_log_max_age_seconds: int = 3600
    host_reachability_targets: str = ""
    host_reachability_timeout_seconds: float = 3.0

    audit_log_path: str = ""

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

    @property
    def telegram_allowed_user_ids(self) -> frozenset[int]:
        try:
            return frozenset(int(item) for item in self._csv(self.telegram_allowed_users))
        except ValueError as exc:
            raise ValueError("TELEGRAM_ALLOWED_USERS must contain numeric Telegram user IDs") from exc

    @property
    def host_mcp_endpoint_urls(self) -> tuple[str, ...]:
        return tuple(self._csv(self.host_mcp_urls))

    @property
    def host_disk_path_set(self) -> frozenset[str]:
        return self._csv(self.host_disk_paths or "/")

    @property
    def host_service_allowlist_set(self) -> frozenset[str]:
        return self._csv(self.host_service_allowlist)

    @property
    def host_docker_allowlist_set(self) -> frozenset[str]:
        return self._csv(self.host_docker_allowlist)

    @property
    def host_log_path_set(self) -> frozenset[str]:
        return self._csv(self.host_log_paths)

    @property
    def host_journal_unit_set(self) -> frozenset[str]:
        return self._csv(self.host_journal_units)

    @property
    def host_reachability_target_set(self) -> frozenset[str]:
        return self._csv(self.host_reachability_targets)

    @property
    def secrets_for_redaction(self) -> tuple[str, ...]:
        return tuple(
            item
            for item in (
                self.ha_token,
                self.llm_api_key,
                self.openai_api_key,
                self.openrouter_api_key,
                self.telegram_bot_token,
                self.host_mcp_token,
            )
            if item
        )
