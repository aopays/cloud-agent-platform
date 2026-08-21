from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pytest

    pytestmark = pytest.mark.security
except ModuleNotFoundError:  # unittest remains usable in dependency-constrained environments.
    pytestmark = None

from src.sandbox import (
    LocalSandboxProvider,
    SandboxPathError,
    SandboxPolicy,
    SandboxPolicyError,
)
from src.shared.contracts import RepositorySpec, TaskSpec


def task_spec() -> TaskSpec:
    return TaskSpec(instruction="find TODO", repository=RepositorySpec("file:///trusted"))


class WorkspaceFileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.provider = LocalSandboxProvider(Path(self.temp.name), allow_trusted_execution=True)
        self.session = await self.provider.create("task_1", "attempt_1", task_spec())

    async def asyncTearDown(self) -> None:
        await self.session.close()
        self.temp.cleanup()

    async def test_list_read_search_write_and_collect(self) -> None:
        await self.session.write_file("report.md", "TODO one\nfinished\nTODO two\n")
        self.assertEqual(await self.session.list_files(), ["report.md"])
        self.assertIn("TODO one", await self.session.read_file("report.md"))
        matches = await self.session.search_text(r"TODO")
        self.assertEqual(len(matches), 2)
        artifacts = await self.session.collect_artifacts(["report.md"])
        self.assertEqual(artifacts, [self.session.workspace / "report.md"])

    async def test_rejects_traversal_and_absolute_paths(self) -> None:
        for path in ("../secret", "a/../../secret", "/etc/passwd", r"C:\Windows\win.ini"):
            with self.subTest(path=path), self.assertRaises(SandboxPathError):
                await self.session.read_file(path)

    async def test_search_treats_regex_metacharacters_as_literals(self) -> None:
        await self.session.write_file("data.txt", "a" * 20_000 + "!\n")
        matches = await asyncio.wait_for(self.session.search_text("(a+)+$"), timeout=0.2)
        self.assertEqual(matches, [])

    async def test_rejects_symlink_escape(self) -> None:
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.session.workspace / "escape.txt"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(SandboxPathError):
            await self.session.read_file("escape.txt")
        self.assertNotIn("escape.txt", await self.session.list_files())

    async def test_enforces_read_write_and_artifact_limits(self) -> None:
        provider = LocalSandboxProvider(
            Path(self.temp.name) / "limits",
            allow_trusted_execution=True,
            policy=SandboxPolicy(max_file_bytes=4, max_write_bytes=4, max_artifact_bytes=3),
        )
        session = await provider.create("task_2", "attempt_2", task_spec())
        try:
            with self.assertRaises(SandboxPolicyError):
                await session.write_file("large.txt", "12345")
            await session.write_file("small.txt", "1234")
            with self.assertRaises(SandboxPolicyError):
                await session.collect_artifacts(["small.txt"])
        finally:
            await session.close()

    async def test_write_policy_can_deny_mutation(self) -> None:
        provider = LocalSandboxProvider(
            Path(self.temp.name) / "readonly",
            allow_trusted_execution=True,
            policy=SandboxPolicy(allow_writes=False),
        )
        session = await provider.create("task_3", "attempt_3", task_spec())
        try:
            with self.assertRaises(SandboxPolicyError):
                await session.write_file("denied.txt", "no")
        finally:
            await session.close()

    async def test_local_provider_requires_explicit_trust(self) -> None:
        provider = LocalSandboxProvider(Path(self.temp.name) / "unsafe-default")
        with self.assertRaises(SandboxPolicyError):
            await provider.create("task_4", "attempt_4", task_spec())

    async def test_close_removes_attempt_directory(self) -> None:
        workspace = self.session.workspace
        await self.session.close()
        self.assertFalse(workspace.exists())

    async def test_close_retries_transient_cleanup_failure(self) -> None:
        session_root = self.session.workspace.parent
        real_rmtree = __import__("shutil").rmtree
        calls = 0

        def flaky_rmtree(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise PermissionError("file handle is still closing")
            real_rmtree(path)

        with patch("src.sandbox.session.shutil.rmtree", side_effect=flaky_rmtree):
            await self.session.close()

        self.assertEqual(calls, 3)
        self.assertFalse(session_root.exists())


if __name__ == "__main__":
    unittest.main()
