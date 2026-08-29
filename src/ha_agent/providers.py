import json
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from .config import Settings
from .models import ProviderTurn, ToolCall, ToolDefinition, ToolResult


class LLMProvider(ABC):
    @abstractmethod
    async def start(self, instructions: str, prompt: str, tools: list[ToolDefinition]) -> ProviderTurn: ...

    @abstractmethod
    async def continue_with_tool_results(self, previous: ProviderTurn, results: list[ToolResult], instructions: str, tools: list[ToolDefinition]) -> ProviderTurn: ...


def _responses_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [{"type": "function", "name": tool.name, "description": tool.description, "parameters": tool.parameters, "strict": False} for tool in tools]


def _chat_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}} for tool in tools]


class ResponsesProvider(LLMProvider):
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    @staticmethod
    def _parse(response: Any) -> ProviderTurn:
        calls: list[ToolCall] = []
        for item in response.output:
            if getattr(item, "type", None) != "function_call":
                continue
            try:
                arguments = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(call_id=item.call_id, name=item.name, arguments=arguments))
        return ProviderTurn(text=response.output_text or "", tool_calls=calls, state=response.id)

    async def start(self, instructions: str, prompt: str, tools: list[ToolDefinition]) -> ProviderTurn:
        response = await self.client.responses.create(model=self.model, instructions=instructions, input=prompt, tools=_responses_tools(tools))
        return self._parse(response)

    async def continue_with_tool_results(self, previous: ProviderTurn, results: list[ToolResult], instructions: str, tools: list[ToolDefinition]) -> ProviderTurn:
        response = await self.client.responses.create(
            model=self.model,
            instructions=instructions,
            previous_response_id=previous.state,
            input=[{"type": "function_call_output", "call_id": result.call_id, "output": result.output} for result in results],
            tools=_responses_tools(tools),
        )
        return self._parse(response)


class ChatCompletionsProvider(LLMProvider):
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    @staticmethod
    def _tool_call_dict(call: Any) -> dict[str, Any]:
        return {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"}}

    def _parse(self, response: Any, messages: list[dict[str, Any]]) -> ProviderTurn:
        message = response.choices[0].message
        calls: list[ToolCall] = []
        raw_calls: list[dict[str, Any]] = []
        for call in message.tool_calls or []:
            raw_calls.append(self._tool_call_dict(call))
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(call_id=call.id, name=call.function.name, arguments=arguments))
        assistant_message: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if raw_calls:
            assistant_message["tool_calls"] = raw_calls
        messages.append(assistant_message)
        return ProviderTurn(text=message.content or "", tool_calls=calls, state=messages)

    async def _complete(self, messages: list[dict[str, Any]], tools: list[ToolDefinition]) -> ProviderTurn:
        response = await self.client.chat.completions.create(model=self.model, messages=messages, tools=_chat_tools(tools))
        return self._parse(response, messages)

    async def start(self, instructions: str, prompt: str, tools: list[ToolDefinition]) -> ProviderTurn:
        messages: list[dict[str, Any]] = [{"role": "system", "content": instructions}, {"role": "user", "content": prompt}]
        return await self._complete(messages, tools)

    async def continue_with_tool_results(self, previous: ProviderTurn, results: list[ToolResult], instructions: str, tools: list[ToolDefinition]) -> ProviderTurn:
        messages = list(previous.state)
        for result in results:
            messages.append({"role": "tool", "tool_call_id": result.call_id, "content": result.output})
        return await self._complete(messages, tools)


def build_provider(settings: Settings) -> LLMProvider:
    client = AsyncOpenAI(api_key=settings.provider_api_key, base_url=settings.provider_base_url)
    if settings.provider_api_style == "responses":
        return ResponsesProvider(client, settings.provider_model)
    return ChatCompletionsProvider(client, settings.provider_model)
