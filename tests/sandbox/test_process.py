from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pytest

    pytestmark = pytest.mark.security
except ModuleNotFoundError:
    pytestmark = None

from src.sandbox import LocalSandboxProvider, SandboxPolicy
from src.shared.contracts import RepositorySpec, TaskSpec


def task_spec() -> TaskSpec:
    return TaskSpec(instruction="test", repository=RepositorySpec("file:///trusted"))


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def _session(self, policy: SandboxPolicy | None = None):
        provider = LocalSandboxProvider(
            Path(self.temp.name), allow_trusted_execution=True, policy=policy
        )
        return await provider.create("task_process", "attempt_process", task_spec())

    async def test_executes_argv_without_shell_and_sanitizes_environment(self) -> None:
        session = await self._session()
        try:
            result = await session.run_command(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('SHOULD_NOT_LEAK', 'clean'))",
                ],
                5,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stdout.strip(), "clean")
            self.assertFalse(result.timed_out)
        finally:
            await session.close()

    async def test_truncates_combined_output(self) -> None:
        session = await self._session(SandboxPolicy(max_output_bytes=64))
        try:
            result = await session.run_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('x'*100); print('y'*100,file=sys.stderr)",
                ],
                5,
            )
            self.assertTrue(result.truncated)
            self.assertLessEqual(len(result.stdout.encode()) + len(result.stderr.encode()), 64)
        finally:
            await session.close()

    async def test_timeout_terminates_command(self) -> None:
        session = await self._session()
        try:
            result = await session.run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"], 1
            )
            self.assertTrue(result.timed_out)
            self.assertLess(result.duration_ms, 5_000)
        finally:
            await session.close()

    async def test_timeout_terminates_child_process_tree(self) -> None:
        session = await self._session()
        marker = session.workspace / "child-survived.txt"
        child_code = f"import time; time.sleep(2); open({str(marker)!r}, 'w').write('bad')"
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
            "time.sleep(30)"
        )
        try:
            result = await session.run_command([sys.executable, "-c", parent_code], 1)
            self.assertTrue(result.timed_out)
            await asyncio.sleep(2)
            self.assertFalse(marker.exists(), "child process survived its timed-out parent")
        finally:
            await session.close()

    async def test_cancel_terminates_running_command(self) -> None:
        session = await self._session()
        command = asyncio.create_task(
            session.run_command([sys.executable, "-c", "import time; time.sleep(30)"], 10)
        )
        await asyncio.sleep(0.2)
        await session.cancel()
        result = await asyncio.wait_for(command, 5)
        self.assertFalse(result.timed_out)
        self.assertLess(result.duration_ms, 5_000)
        await session.close()


if __name__ == "__main__":
    unittest.main()
