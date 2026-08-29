from ha_agent.config import Settings
from ha_agent.models import ToolDefinition
from ha_agent.policy import PermissionTier, PolicyAction, ToolPolicy


def settings(**overrides):
    base = {"ha_mcp_url": "http://ha/api/mcp/assist", "ha_token": "token", "openai_api_key": "test"}
    base.update(overrides)
    return Settings(**base)


def test_read_tools_are_visible_by_default():
    policy = ToolPolicy(settings())
    tools = [ToolDefinition("GetLiveContext", "read", {}), ToolDefinition("HassTurnOn", "write", {})]
    assert [tool.name for tool in policy.visible_tools(tools)] == ["GetLiveContext"]


def test_unknown_tool_is_denied():
    assert ToolPolicy(settings(ha_write_enabled=True)).authorize("DangerousThing", {}).action == PolicyAction.DENY


def test_safe_write_requires_enable_and_allowlist():
    decision = ToolPolicy(settings(ha_write_enabled=True, ha_safe_write_tools="HassTurnOn")).authorize("HassTurnOn", {"domain": "light", "name": "Kitchen"})
    assert decision.action == PolicyAction.ALLOW
    assert decision.tier == PermissionTier.SAFE_WRITE


def test_sensitive_domain_escalates_safe_tool_to_confirmation():
    decision = ToolPolicy(settings(ha_write_enabled=True, ha_safe_write_tools="HassTurnOn")).authorize("HassTurnOn", {"domain": "lock", "name": "Front"})
    assert decision.action == PolicyAction.CONFIRM
    assert decision.tier == PermissionTier.SENSITIVE_WRITE


def test_sensitive_name_term_escalates_to_confirmation():
    decision = ToolPolicy(settings(ha_write_enabled=True, ha_safe_write_tools="HassTurnOff")).authorize("HassTurnOff", {"name": "Garage door"})
    assert decision.action == PolicyAction.CONFIRM


def test_explicit_sensitive_tool_always_requires_confirmation():
    decision = ToolPolicy(settings(ha_write_enabled=True, ha_sensitive_write_tools="ArmAlarm")).authorize("ArmAlarm", {})
    assert decision.action == PolicyAction.CONFIRM
