from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .config import Settings
from .models import ToolDefinition


class PermissionTier(StrEnum):
    READ = "READ"
    SAFE_WRITE = "SAFE_WRITE"
    SENSITIVE_WRITE = "SENSITIVE_WRITE"
    ADMIN = "ADMIN"


class PolicyAction(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    tier: PermissionTier
    reason: str


class ToolPolicy:
    def __init__(self, settings: Settings) -> None:
        self.write_enabled = settings.ha_write_enabled
        self.safe_write_tools = settings.safe_write_tools
        self.sensitive_write_tools = settings.sensitive_write_tools
        self.admin_tools = settings.admin_tools
        self.read_tools = settings.read_tools
        self.read_prefixes = settings.read_tool_prefixes
        self.sensitive_domains = settings.sensitive_domains
        self.sensitive_name_terms = settings.sensitive_name_terms

    def _is_read_tool(self, tool_name: str) -> bool:
        return tool_name in self.read_tools or tool_name.startswith(self.read_prefixes)

    def visible_tools(self, tools: list[ToolDefinition]) -> list[ToolDefinition]:
        visible: list[ToolDefinition] = []
        for tool in tools:
            if self._is_read_tool(tool.name):
                visible.append(tool)
            elif self.write_enabled and (tool.name in self.safe_write_tools or tool.name in self.sensitive_write_tools):
                visible.append(tool)
        return visible

    def _flatten_strings(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            strings: list[str] = []
            for item in value.values():
                strings.extend(self._flatten_strings(item))
            return strings
        if isinstance(value, (list, tuple, set)):
            strings: list[str] = []
            for item in value:
                strings.extend(self._flatten_strings(item))
            return strings
        return []

    def _targets_sensitive_resource(self, arguments: dict[str, Any]) -> bool:
        for value in self._flatten_strings(arguments):
            normalized = value.lower().strip()
            if "." in normalized and normalized.split(".", 1)[0] in self.sensitive_domains:
                return True
            if normalized in self.sensitive_domains:
                return True
            if any(term in normalized for term in self.sensitive_name_terms):
                return True
        return False

    def authorize(self, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        if tool_name in self.admin_tools:
            return PolicyDecision(PolicyAction.DENY, PermissionTier.ADMIN, "administrative tools are prohibited")
        if self._is_read_tool(tool_name):
            return PolicyDecision(PolicyAction.ALLOW, PermissionTier.READ, "read tool")
        if tool_name in self.sensitive_write_tools:
            if not self.write_enabled:
                return PolicyDecision(PolicyAction.DENY, PermissionTier.SENSITIVE_WRITE, "writes are disabled")
            return PolicyDecision(PolicyAction.CONFIRM, PermissionTier.SENSITIVE_WRITE, "tool is explicitly classified as sensitive")
        if tool_name in self.safe_write_tools:
            if not self.write_enabled:
                return PolicyDecision(PolicyAction.DENY, PermissionTier.SAFE_WRITE, "writes are disabled")
            if self._targets_sensitive_resource(arguments):
                return PolicyDecision(PolicyAction.CONFIRM, PermissionTier.SENSITIVE_WRITE, "target matches a sensitive domain/name")
            return PolicyDecision(PolicyAction.ALLOW, PermissionTier.SAFE_WRITE, "tool is allow-listed for safe writes")
        return PolicyDecision(PolicyAction.DENY, PermissionTier.ADMIN, "tool is not on the read or write allow-list")
