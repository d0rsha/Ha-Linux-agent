import json
import logging
from collections.abc import Callable

from .config import Settings
from .ha_mcp import HomeAssistantMCP, mcp_result_to_text, mcp_tools_to_definitions
from .models import ToolCall, ToolResult
from .policy import PolicyAction, PolicyDecision, ToolPolicy
from .providers import build_provider


LOGGER = logging.getLogger("ha_agent.audit")

SYSTEM_PROMPT = """You are a private Home Assistant agent running for one household.
Use Home Assistant tools whenever live state is needed. Do not invent entity states.
Only use tools that are presented to you. Tool availability is an authorization boundary.
If a tool call is denied, explain that the action is outside the configured policy rather than claiming it succeeded.
Prefer concise answers, call out anomalies, and include relevant measurements and timestamps when available.
"""

ConfirmSensitive = Callable[[ToolCall, PolicyDecision], bool]


def _audit(event: str, call: ToolCall, decision: PolicyDecision, **extra: object) -> None:
    payload = {"event": event, "tool": call.name, "tier": decision.tier.value, "decision": decision.action.value, "argument_keys": sorted(call.arguments.keys()), **extra}
    LOGGER.info(json.dumps(payload, sort_keys=True))


async def ask_home(settings: Settings, question: str, confirm_sensitive: ConfirmSensitive | None = None) -> str:
    provider = build_provider(settings)
    ha = HomeAssistantMCP(settings.ha_mcp_url, settings.ha_token)
    policy = ToolPolicy(settings)

    async with ha.connect() as mcp:
        tool_result = await mcp.list_tools()
        all_tools = mcp_tools_to_definitions(tool_result.tools)
        tools = policy.visible_tools(all_tools)
        response = await provider.start(SYSTEM_PROMPT, question, tools)

        for _ in range(settings.max_tool_rounds):
            if not response.tool_calls:
                return response.text
            outputs: list[ToolResult] = []
            for call in response.tool_calls:
                decision = policy.authorize(call.name, call.arguments)
                _audit("tool_requested", call, decision, reason=decision.reason)
                if decision.action == PolicyAction.DENY:
                    text = f"Tool denied by policy: {decision.reason}."
                    _audit("tool_denied", call, decision, reason=decision.reason)
                elif decision.action == PolicyAction.CONFIRM:
                    approved = bool(confirm_sensitive and confirm_sensitive(call, decision))
                    if not approved:
                        text = "Sensitive tool call was not approved by the user."
                        _audit("tool_denied", call, decision, reason="user did not approve")
                    else:
                        _audit("tool_approved", call, decision)
                        try:
                            result = await mcp.call_tool(call.name, call.arguments)
                            text = mcp_result_to_text(result)
                            _audit("tool_executed", call, decision, success=True)
                        except Exception as exc:
                            text = f"Tool error: {type(exc).__name__}: {exc}"
                            _audit("tool_executed", call, decision, success=False)
                else:
                    try:
                        result = await mcp.call_tool(call.name, call.arguments)
                        text = mcp_result_to_text(result)
                        _audit("tool_executed", call, decision, success=True)
                    except Exception as exc:
                        text = f"Tool error: {type(exc).__name__}: {exc}"
                        _audit("tool_executed", call, decision, success=False)
                outputs.append(ToolResult(call_id=call.call_id, output=text))
            response = await provider.continue_with_tool_results(response, outputs, SYSTEM_PROMPT, tools)

        raise RuntimeError("Agent exceeded MAX_TOOL_ROUNDS")
