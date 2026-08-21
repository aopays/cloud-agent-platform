"""Resource and tool policy values shared by sandbox adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Bound every host-side primitive exposed by a sandbox session."""

    allow_writes: bool = True
    max_file_bytes: int = 1_048_576
    max_write_bytes: int = 1_048_576
    max_search_files: int = 10_000
    max_search_matches: int = 2_000
    max_artifact_bytes: int = 10_485_760
    max_output_bytes: int = 65_536
    max_command_seconds: int = 30
    max_argv_items: int = 128
    max_argument_bytes: int = 16_384

    def __post_init__(self) -> None:
        for name in (
            "max_file_bytes",
            "max_write_bytes",
            "max_search_files",
            "max_search_matches",
            "max_artifact_bytes",
            "max_output_bytes",
            "max_command_seconds",
            "max_argv_items",
            "max_argument_bytes",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class DockerResourceLimits:
    """Limits translated to Docker CLI flags.

    ``workspace_bytes`` limits adapter-mediated writes and documents the desired
    filesystem quota. A bind-mounted host directory still requires a host
    filesystem/project quota for a hard command-level disk limit.
    """

    cpus: float = 1.0
    memory_bytes: int = 536_870_912
    pids: int = 128
    tmpfs_bytes: int = 67_108_864
    workspace_bytes: int = 536_870_912

    def __post_init__(self) -> None:
        if self.cpus <= 0:
            raise ValueError("cpus must be positive")
        for name in ("memory_bytes", "pids", "tmpfs_bytes", "workspace_bytes"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
