from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import pytest

    pytestmark = pytest.mark.security
except ModuleNotFoundError:
    pytestmark = None

from src.sandbox import DockerResourceLimits, SandboxPolicyError, build_create_argv
from src.sandbox.docker import container_name


class DockerPolicyTests(unittest.TestCase):
    def test_create_command_has_isolation_and_resource_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            argv = build_create_argv(
                docker_binary="docker",
                image="cloud-agent-sandbox:local",
                name=container_name("task_1", "attempt_1"),
                workspace=workspace,
                limits=DockerResourceLimits(),
            )
        joined = " ".join(argv)
        self.assertIn("--network none", joined)
        self.assertIn("--read-only", argv)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("no-new-privileges=true", argv)
        self.assertIn("--pids-limit", argv)
        self.assertIn("--memory", argv)
        self.assertIn("--memory-swap", argv)
        self.assertIn("--cpus", argv)
        self.assertIn("--user 65532:65532", joined)
        self.assertIn("/tmp:rw,noexec,nosuid,nodev,size=", joined)
        self.assertNotIn("--privileged", argv)
        self.assertFalse(any("docker.sock" in argument for argument in argv))

    def test_rejects_root_user_and_option_like_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            kwargs = {
                "docker_binary": "docker",
                "name": container_name("task_1", "attempt_1"),
                "workspace": workspace,
                "limits": DockerResourceLimits(),
            }
            with self.assertRaises(SandboxPolicyError):
                build_create_argv(image="--privileged", user="65532:65532", **kwargs)
            with self.assertRaises(SandboxPolicyError):
                build_create_argv(image="safe:latest", user="0:0", **kwargs)

    def test_container_name_does_not_expose_identifiers(self) -> None:
        name = container_name("tenant-secret-task", "attempt-secret")
        self.assertRegex(name, r"^cap-[a-f0-9]{24}$")
        self.assertNotIn("secret", name)


if __name__ == "__main__":
    unittest.main()
