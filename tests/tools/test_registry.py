from __future__ import annotations

import unittest

from src.agent_runtime.errors import ToolCallRejected
from src.agent_runtime.provider import ToolCall
from src.tools.builtin import create_default_registry
from src.tools.registry import ToolContext
from tests.agent_runtime.test_loop import FakeSandbox


class ToolRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_rejects_missing_and_unknown_arguments(self) -> None:
        registry = create_default_registry()
        context = ToolContext(FakeSandbox(), 1, 100)
        for arguments in ({}, {"relative_path": "a", "extra": True}):
            with self.subTest(arguments=arguments), self.assertRaises(ToolCallRejected):
                await registry.execute(ToolCall("1", "read_file", arguments), context)

    async def test_write_requires_explicit_policy_opt_in(self) -> None:
        registry = create_default_registry()
        with self.assertRaises(ToolCallRejected):
            await registry.execute(
                ToolCall("1", "write_file", {"relative_path": "x", "content": "value"}),
                ToolContext(FakeSandbox(), 1, 100),
            )

    async def test_policy_rejects_path_traversal_before_sandbox(self) -> None:
        registry = create_default_registry()
        for path in ("../secret", "a/../../secret", "C:\\Windows\\system.ini", "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(ToolCallRejected):
                await registry.execute(
                    ToolCall("1", "read_file", {"relative_path": path}),
                    ToolContext(FakeSandbox(), 1, 100),
                )

    async def test_command_is_delegated_to_sandbox_as_argv(self) -> None:
        sandbox = FakeSandbox()
        registry = create_default_registry()
        result = await registry.execute(
            ToolCall("1", "run_command", {"argv": ["python", "-V"]}),
            ToolContext(sandbox, 7, 1000),
        )
        self.assertEqual([(["python", "-V"], 7)], sandbox.commands)
        self.assertEqual(0, result.exit_code)
        summary = registry.summarize_arguments(
            ToolCall("2", "run_command", {"argv": ["client", "--token", "very-secret"]})
        )
        self.assertNotIn("very-secret", str(summary))
        self.assertEqual("client", summary["argv"]["executable"])

    async def test_command_can_be_disabled_for_trusted_local_mode(self) -> None:
        registry = create_default_registry(allow_execute=False)
        with self.assertRaises(ToolCallRejected):
            await registry.execute(
                ToolCall("1", "run_command", {"argv": ["python", "-V"]}),
                ToolContext(FakeSandbox(), 1, 1000),
            )

    async def test_output_is_utf8_safely_truncated_and_secret_redacted(self) -> None:
        registry = create_default_registry()
        result = await registry.execute(
            ToolCall("1", "read_file", {"relative_path": "README.md"}),
            ToolContext(FakeSandbox(), 1, 9),
        )
        self.assertTrue(result.truncated)
        self.assertLessEqual(result.output_bytes, 9)

        class SecretSandbox(FakeSandbox):
            async def read_file(self, relative_path: str) -> str:
                return "api_key=supersecretvalue"

        secret = await registry.execute(
            ToolCall("2", "read_file", {"relative_path": "README.md"}),
            ToolContext(SecretSandbox(), 1, 100),
        )
        self.assertEqual("api_key=[REDACTED]", secret.output)

    async def test_write_content_is_hashed_in_event_summary(self) -> None:
        registry = create_default_registry(allow_write=True)
        call = ToolCall("1", "write_file", {"relative_path": "x", "content": "secret text"})
        summary = registry.summarize_arguments(call)
        self.assertNotIn("secret text", str(summary))
        self.assertEqual(11, summary["content"]["sizeBytes"])


if __name__ == "__main__":
    unittest.main()
