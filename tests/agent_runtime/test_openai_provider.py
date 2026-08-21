from __future__ import annotations

import json
import unittest
from typing import Any

import httpx

from src.agent_runtime import (
    Message,
    OpenAIResponsesProvider,
    ProviderResponseError,
    TransientProviderError,
)

TOOL_SCHEMA = {
    "name": "search_text",
    "description": "Search workspace text.",
    "parameters": {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
        "additionalProperties": False,
    },
}


def response_json(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": "completed",
        "output": [],
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    data.update(overrides)
    return data


class OpenAIResponsesProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_responses_payload_and_parses_output_text(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=response_json(output_text="final answer"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(
                api_key="test-key",
                model="test-model",
                base_url="https://example.test",
                client=client,
            )
            result = await provider.complete(
                [Message("system", "safe"), Message("user", "find TODO")], [TOOL_SCHEMA]
            )

        request = captured["request"]
        body = captured["body"]
        self.assertEqual("https://example.test/v1/responses", str(request.url))
        self.assertEqual("Bearer test-key", request.headers["Authorization"])
        self.assertEqual("test-model", body["model"])
        self.assertFalse(body["store"])
        self.assertEqual("function", body["tools"][0]["type"])
        self.assertEqual(TOOL_SCHEMA["parameters"], body["tools"][0]["parameters"])
        self.assertEqual("final answer", result.final_answer)
        self.assertEqual(11, result.usage.input_tokens)
        self.assertEqual(7, result.usage.output_tokens)

    async def test_base_url_may_already_include_v1(self) -> None:
        captured_url = ""

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=response_json(output_text="ok"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(
                api_key="key", model="model", base_url="https://example.test/v1", client=client
            )
            await provider.complete([], [])
        self.assertEqual("https://example.test/v1/responses", captured_url)

    async def test_maps_function_history_and_parses_multiple_function_calls(self) -> None:
        captured_body: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_body.update(json.loads(request.content))
            return httpx.Response(
                200,
                json=response_json(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": "call-2",
                            "name": "search_text",
                            "arguments": '{"pattern":"FIXME"}',
                        },
                        {
                            "type": "function_call",
                            "call_id": "call-3",
                            "name": "search_text",
                            "arguments": '{"pattern":"TODO"}',
                        },
                    ]
                ),
            )

        messages = [
            Message("user", "find markers"),
            Message(
                "assistant",
                '{"pattern":"TODO"}',
                tool_call_id="call-1",
                tool_name="search_text",
            ),
            Message("tool", "matches", tool_call_id="call-1", tool_name="search_text"),
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(api_key="key", model="model", client=client)
            result = await provider.complete(messages, [TOOL_SCHEMA])

        self.assertEqual("function_call", captured_body["input"][1]["type"])
        self.assertEqual("function_call_output", captured_body["input"][2]["type"])
        self.assertEqual("call-1", captured_body["input"][2]["call_id"])
        self.assertEqual(2, len(result.tool_calls))
        self.assertEqual({"pattern": "FIXME"}, result.tool_calls[0].arguments)

    async def test_parses_output_text_from_message_content(self) -> None:
        payload = response_json(
            output=[
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "nested answer"}],
                }
            ]
        )
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            result = await OpenAIResponsesProvider(
                api_key="key", model="model", client=client
            ).complete([Message("user", "hello")], [])
        self.assertEqual("nested answer", result.final_answer)

    async def test_429_5xx_and_network_errors_are_transient(self) -> None:
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                transport = httpx.MockTransport(
                    lambda request, status=status_code: httpx.Response(status)
                )
                async with httpx.AsyncClient(transport=transport) as client:
                    provider = OpenAIResponsesProvider(api_key="key", model="model", client=client)
                    with self.assertRaises(TransientProviderError):
                        await provider.complete([], [])

        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            provider = OpenAIResponsesProvider(api_key="key", model="model", client=client)
            with self.assertRaises(TransientProviderError):
                await provider.complete([], [])

    async def test_nonretryable_http_error_does_not_leak_body_or_key(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                400, json={"error": {"message": "secret-key request was invalid"}}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAIResponsesProvider(api_key="secret-key", model="model", client=client)
            with self.assertRaises(ProviderResponseError) as raised:
                await provider.complete([], [])
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertIn("HTTP 400", str(raised.exception))

    async def test_invalid_json_arguments_and_empty_output_fail_safely(self) -> None:
        payloads = [
            response_json(
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "search_text",
                        "arguments": "not-json",
                    }
                ]
            ),
            response_json(),
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                transport = httpx.MockTransport(
                    lambda request, response_payload=payload: httpx.Response(
                        200, json=response_payload
                    )
                )
                async with httpx.AsyncClient(transport=transport) as client:
                    provider = OpenAIResponsesProvider(api_key="key", model="model", client=client)
                    with self.assertRaises(ProviderResponseError):
                        await provider.complete([], [TOOL_SCHEMA])

    def test_unsafe_base_urls_are_rejected(self) -> None:
        for base_url in (
            "http://api.openai.com",
            "https://user:secret@example.test",
            "not-a-url",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaisesRegex(ValueError, "HTTPS URL"):
                    OpenAIResponsesProvider(
                        api_key="key",
                        model="model",
                        base_url=base_url,
                    )


if __name__ == "__main__":
    unittest.main()
