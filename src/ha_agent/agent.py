import json

from openai import AsyncOpenAI

from .config import Settings
from .ha_mcp import HomeAssistantMCP, mcp_result_to_text, mcp_tools_to_openai


SYSTEM_PROMPT = """You are a private Home Assistant analyst running for one household.
Use Home Assistant tools whenever live state is needed. Do not invent entity states.
For v0.1 you are read-only: report and analyze; do not claim to have changed anything.
Prefer concise answers, call out anomalies, and include relevant measurements and timestamps when available.
"""


async def ask_home(settings: Settings, question: str) -> str:
    llm = AsyncOpenAI(api_key=settings.openai_api_key)
    ha = HomeAssistantMCP(settings.ha_mcp_url, settings.ha_token)

    async with ha.connect() as mcp:
        tool_result = await mcp.list_tools()
        tools = mcp_tools_to_openai(tool_result.tools)

        response = await llm.responses.create(
            model=settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=question,
            tools=tools,
        )

        for _ in range(settings.max_tool_rounds):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return response.output_text

            outputs: list[dict[str, str]] = []
            for call in calls:
                try:
                    arguments = json.loads(call.arguments or "{}")
                    result = await mcp.call_tool(call.name, arguments)
                    text = mcp_result_to_text(result)
                except Exception as exc:
                    text = f"Tool error: {type(exc).__name__}: {exc}"

                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": text,
                    }
                )

            response = await llm.responses.create(
                model=settings.openai_model,
                instructions=SYSTEM_PROMPT,
                previous_response_id=response.id,
                input=outputs,
                tools=tools,
            )

        raise RuntimeError("Agent exceeded MAX_TOOL_ROUNDS")
