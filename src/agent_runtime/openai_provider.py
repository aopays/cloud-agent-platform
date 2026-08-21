"""OpenAI Responses API adapter using the project's vendor-neutral contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from src.agent_runtime.provider import (
    Message,
    ModelResponse,
    ModelUsage,
    ProviderResponseError,
    ToolCall,
    TransientProviderError,
)


class OpenAIResponsesProvider:
    """Call `/v1/responses` without coupling the runtime to an OpenAI SDK."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not model.strip():
            raise ValueError("model must not be empty")
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        parsed_base_url = urlparse(base_url)
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username
            or parsed_base_url.password
        ):
            raise ValueError("base_url must be an HTTPS URL without embedded credentials")
        self._api_key = api_key
        self.model = model
        normalized_base_url = base_url.rstrip("/")
        suffix = "/responses" if normalized_base_url.endswith("/v1") else "/v1/responses"
        self._endpoint = f"{normalized_base_url}{suffix}"
        self._client = client

    async def complete(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]
    ) -> ModelResponse:
        payload = {
            "model": self.model,
            "input": [self._message_input(message) for message in messages],
            "tools": [self._function_tool(tool) for tool in tools],
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient() as client:
                    response = await client.post(self._endpoint, headers=headers, json=payload)
            else:
                response = await self._client.post(self._endpoint, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise TransientProviderError("OpenAI request failed due to a network error") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientProviderError(
                f"OpenAI request returned retryable HTTP {response.status_code}"
            )
        if not 200 <= response.status_code < 300:
            raise ProviderResponseError(
                f"OpenAI request was rejected with HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("OpenAI returned a non-JSON response") from exc
        return self._parse_response(data)

    @staticmethod
    def _message_input(message: Message) -> dict[str, Any]:
        if message.role == "tool":
            if not message.tool_call_id:
                raise ProviderResponseError("tool observation is missing call_id")
            return {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": message.content,
            }
        if message.role == "assistant" and message.tool_call_id:
            if not message.tool_name:
                raise ProviderResponseError("function call history is missing tool name")
            return {
                "type": "function_call",
                "call_id": message.tool_call_id,
                "name": message.tool_name,
                "arguments": message.content,
            }
        return {"role": message.role, "content": message.content}

    @staticmethod
    def _function_tool(tool: dict[str, Any]) -> dict[str, Any]:
        try:
            name = tool["name"]
            description = tool["description"]
            parameters = tool["parameters"]
        except KeyError as exc:
            raise ProviderResponseError("registered tool schema is incomplete") from exc
        if not isinstance(name, str) or not isinstance(description, str):
            raise ProviderResponseError("registered tool name and description must be strings")
        if not isinstance(parameters, dict):
            raise ProviderResponseError("registered tool parameters must be an object")
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": parameters,
        }

    @classmethod
    def _parse_response(cls, data: Any) -> ModelResponse:
        if not isinstance(data, dict):
            raise ProviderResponseError("OpenAI response must be an object")
        status = data.get("status")
        if status in {"failed", "cancelled", "incomplete"}:
            raise ProviderResponseError(f"OpenAI response ended with status '{status}'")

        usage_data = data.get("usage") or {}
        if not isinstance(usage_data, dict):
            raise ProviderResponseError("OpenAI usage must be an object")
        usage = ModelUsage(
            input_tokens=cls._nonnegative_int(usage_data.get("input_tokens", 0), "input_tokens"),
            output_tokens=cls._nonnegative_int(usage_data.get("output_tokens", 0), "output_tokens"),
        )

        output = data.get("output") or []
        if not isinstance(output, list):
            raise ProviderResponseError("OpenAI output must be an array")
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                tool_calls.append(cls._parse_tool_call(item))
            elif item.get("type") == "message":
                text_parts.extend(cls._message_text(item))

        top_level_text = data.get("output_text")
        if not text_parts and isinstance(top_level_text, str) and top_level_text.strip():
            text_parts.append(top_level_text)
        text = "\n".join(part for part in text_parts if part.strip()).strip()
        if tool_calls:
            return ModelResponse(
                tool_calls=tuple(tool_calls),
                action_summary=text or None,
                usage=usage,
            )
        if text:
            return ModelResponse(final_answer=text, usage=usage)
        raise ProviderResponseError("OpenAI response contained no text or function call")

    @staticmethod
    def _parse_tool_call(item: dict[str, Any]) -> ToolCall:
        call_id = item.get("call_id")
        name = item.get("name")
        arguments_json = item.get("arguments")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ProviderResponseError("OpenAI function call is missing call_id")
        if not isinstance(name, str) or not name.strip():
            raise ProviderResponseError("OpenAI function call is missing name")
        if not isinstance(arguments_json, str):
            raise ProviderResponseError("OpenAI function arguments must be JSON text")
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError("OpenAI function arguments were invalid JSON") from exc
        if not isinstance(arguments, dict):
            raise ProviderResponseError("OpenAI function arguments must decode to an object")
        return ToolCall(call_id=call_id, name=name, arguments=arguments)

    @staticmethod
    def _message_text(item: dict[str, Any]) -> list[str]:
        content = item.get("content") or []
        if not isinstance(content, list):
            return []
        return [
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        ]

    @staticmethod
    def _nonnegative_int(value: Any, field: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProviderResponseError(f"OpenAI usage field '{field}' must be non-negative")
        return value
