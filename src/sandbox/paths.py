"""Workspace-confined file primitives.

The local adapter is intentionally limited to trusted workloads. These checks
also reduce accidental escape and defend against ordinary symlink attacks, but
they are not a replacement for a kernel-enforced sandbox when paths can race.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePath, PureWindowsPath

from src.sandbox.errors import SandboxPathError

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class WorkspacePaths:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve(strict=True)

    @staticmethod
    def _parts(relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path:
            raise SandboxPathError("path must be a non-empty string")
        if "\x00" in relative_path:
            raise SandboxPathError("path contains a NUL byte")
        windows_path = PureWindowsPath(relative_path)
        if (
            PurePath(relative_path).is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or _WINDOWS_ABSOLUTE.match(relative_path)
        ):
            raise SandboxPathError("absolute paths are forbidden")
        normalized = relative_path.replace("\\", "/")
        parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
        if any(part == ".." for part in parts):
            raise SandboxPathError("parent traversal is forbidden")
        return parts

    def existing(self, relative_path: str, *, directory: bool | None = None) -> Path:
        parts = self._parts(relative_path)
        candidate = self.workspace.joinpath(*parts)
        self._reject_symlink_components(candidate)
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            raise SandboxPathError("path does not exist inside the workspace") from exc
        self._ensure_inside(resolved)
        if directory is True and not resolved.is_dir():
            raise SandboxPathError("path is not a directory")
        if directory is False and not resolved.is_file():
            raise SandboxPathError("path is not a regular file")
        return resolved

    def writable_file(self, relative_path: str) -> Path:
        parts = self._parts(relative_path)
        if not parts:
            raise SandboxPathError("workspace root cannot be written as a file")
        candidate = self.workspace.joinpath(*parts)
        self._reject_symlink_components(candidate)
        parent = candidate.parent.resolve(strict=True)
        self._ensure_inside(parent)
        if candidate.exists() and not candidate.is_file():
            raise SandboxPathError("destination is not a regular file")
        return candidate

    def _reject_symlink_components(self, candidate: Path) -> None:
        current = self.workspace
        for part in candidate.relative_to(self.workspace).parts:
            current = current / part
            if current.is_symlink():
                raise SandboxPathError("symbolic links are forbidden")
            if not current.exists():
                break

    def _ensure_inside(self, candidate: Path) -> None:
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise SandboxPathError("path escapes the workspace") from exc


def open_for_write(path: Path) -> int:
    """Open a checked destination without following a final symlink where supported."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600)
