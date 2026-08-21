"""Controlled local import and public HTTPS Git checkout before execution."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import stat
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from src.sandbox.process import terminate_process_tree
from src.shared.contracts import RepositorySpec


class RepositoryPreparationError(RuntimeError):
    pass


class LocalRepositoryPreparer:
    """Prepare local allowlisted paths or public Git repositories without credentials."""

    def __init__(
        self,
        *,
        allowed_root: Path,
        allowed_git_hosts: tuple[str, ...] = ("github.com", "gitlab.com"),
        max_files: int = 20_000,
        max_directories: int = 5_000,
        max_bytes: int = 100_000_000,
        clone_timeout_seconds: int = 120,
    ) -> None:
        self._allowed_root = allowed_root.resolve(strict=True)
        self._allowed_git_hosts = frozenset(host.lower() for host in allowed_git_hosts)
        self._max_files = max_files
        self._max_directories = max_directories
        self._max_bytes = max_bytes
        self._clone_timeout_seconds = clone_timeout_seconds

    async def prepare(self, repository: RepositorySpec, workspace: Path) -> None:
        parsed = urlparse(repository.url)
        if parsed.scheme == "file":
            source = self._file_url_to_path(repository.url)
            await asyncio.to_thread(self._copy_bounded, source, workspace)
            return
        if parsed.scheme == "https":
            await self._clone_public_git(repository, workspace)
            return
        raise RepositoryPreparationError("repository URL must use file:// or https://")

    def _file_url_to_path(self, value: str) -> Path:
        parsed = urlparse(value)
        if parsed.netloc not in {"", "localhost"}:
            raise RepositoryPreparationError("remote file URLs are forbidden")
        path = Path(url2pathname(unquote(parsed.path)))
        if os.name == "nt" and path.as_posix().startswith("/"):
            path = Path(path.as_posix()[1:])
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RepositoryPreparationError("repository path does not exist") from exc
        if not resolved.is_dir() or not resolved.is_relative_to(self._allowed_root):
            raise RepositoryPreparationError("repository path is outside the import root")
        return resolved

    async def _clone_public_git(self, repository: RepositorySpec, workspace: Path) -> None:
        parsed = urlparse(repository.url)
        if (
            not parsed.hostname
            or parsed.hostname.lower() not in self._allowed_git_hosts
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise RepositoryPreparationError("Git repository host or credentials are forbidden")
        if repository.ref is not None and (
            repository.ref.startswith("-")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", repository.ref)
            or ".." in repository.ref.split("/")
        ):
            raise RepositoryPreparationError("Git ref is invalid")
        argv = [
            "git",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "http.followRedirects=false",
            "clone",
            "--depth",
            "1",
            "--no-tags",
        ]
        if repository.ref:
            argv.extend(["--branch", repository.ref])
        argv.extend([repository.url, "."])
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        process: asyncio.subprocess.Process | None = None
        monitor: asyncio.Task[None] | None = None
        checkout_limit_exceeded = asyncio.Event()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=workspace,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=(
                    int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                    if os.name == "nt"
                    else 0
                ),
                start_new_session=os.name != "nt",
            )
            monitor = asyncio.create_task(
                self._monitor_checkout_size(
                    process,
                    workspace,
                    checkout_limit_exceeded,
                )
            )
            output, _ = await asyncio.wait_for(
                process.communicate(), timeout=self._clone_timeout_seconds
            )
        except (OSError, asyncio.TimeoutError) as exc:
            if process is not None:
                await terminate_process_tree(process)
            raise RepositoryPreparationError("controlled Git checkout failed") from exc
        finally:
            if monitor is not None:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
        if checkout_limit_exceeded.is_set():
            raise RepositoryPreparationError("repository exceeded clone byte limit")
        assert process is not None
        if process.returncode != 0:
            safe_detail = output[:1000].decode("utf-8", errors="replace")
            raise RepositoryPreparationError(f"controlled Git checkout failed: {safe_detail}")
        await asyncio.to_thread(self._validate_checkout, workspace)

    async def _monitor_checkout_size(
        self,
        process: asyncio.subprocess.Process,
        workspace: Path,
        exceeded: asyncio.Event,
    ) -> None:
        while process.returncode is None:
            if await asyncio.to_thread(self._checkout_exceeds_byte_limit, workspace):
                exceeded.set()
                await terminate_process_tree(process)
                return
            await asyncio.sleep(0.05)

    def _checkout_exceeds_byte_limit(self, workspace: Path) -> bool:
        total = 0
        for current, directory_names, file_names in os.walk(workspace, followlinks=False):
            current_path = Path(current)
            directory_names[:] = [
                name for name in directory_names if not (current_path / name).is_symlink()
            ]
            for name in file_names:
                path = current_path / name
                try:
                    total += path.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if total > self._max_bytes:
                    return True
        return False

    @staticmethod
    def _sensitive(relative: Path) -> bool:
        lowered = [part.lower() for part in relative.parts]
        name = relative.name.lower()
        exact_sensitive_names = {
            ".dockerconfigjson",
            ".npmrc",
            ".netrc",
            ".pypirc",
            "credentials",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
            "id_rsa",
            "kubeconfig",
            "secret",
            "secret.txt",
        }
        return (
            ".git" in lowered
            or ".aws" in lowered
            or ".azure" in lowered
            or ".docker" in lowered
            or ".config/gcloud" in relative.as_posix().lower()
            or ".kube" in lowered
            or name == ".env"
            or name.startswith(".env.")
            or name in exact_sensitive_names
            or relative.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}
            or any(word in name for word in ("credential", "secrets", "service-account"))
        )

    def _validate_checkout(self, workspace: Path) -> None:
        files = 0
        directories = 0
        total = 0
        for current, directory_names, file_names in os.walk(workspace, followlinks=False):
            current_path = Path(current)
            directory_names[:] = [
                name
                for name in directory_names
                if not (current_path / name).is_symlink() and name != ".git"
            ]
            directories += len(directory_names)
            if directories > self._max_directories:
                raise RepositoryPreparationError("repository has too many directories")
            for name in file_names:
                path = current_path / name
                relative = path.relative_to(workspace)
                if path.is_symlink() or self._sensitive(relative):
                    path.unlink(missing_ok=True)
                    continue
                files += 1
                total += path.stat().st_size
                if files > self._max_files or total > self._max_bytes:
                    raise RepositoryPreparationError("repository exceeds checkout limits")
        git_metadata = workspace / ".git"
        if git_metadata.exists():
            import shutil

            shutil.rmtree(git_metadata)

    def _copy_bounded(self, source: Path, destination: Path) -> None:
        copied_files = 0
        copied_directories = 0
        copied_bytes = 0
        for current, directories, files in os.walk(source, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name
                for name in directories
                if not (current_path / name).is_symlink() and name != ".git"
            ]
            copied_directories += len(directories)
            if copied_directories > self._max_directories:
                raise RepositoryPreparationError("repository has too many directories")
            relative_dir = current_path.relative_to(source)
            target_dir = destination / relative_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                candidate = current_path / name
                relative = candidate.relative_to(source)
                if candidate.is_symlink() or self._sensitive(relative):
                    continue
                copied_files += 1
                if copied_files > self._max_files:
                    raise RepositoryPreparationError("repository has too many files")
                source_stat = candidate.stat(follow_symlinks=False)
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(candidate, flags)
                try:
                    opened_stat = os.fstat(descriptor)
                    if not stat.S_ISREG(opened_stat.st_mode) or (
                        source_stat.st_dev,
                        source_stat.st_ino,
                    ) != (opened_stat.st_dev, opened_stat.st_ino):
                        raise RepositoryPreparationError("repository changed during import")
                    destination_path = target_dir / name
                    with destination_path.open("xb") as output:
                        while True:
                            chunk = os.read(descriptor, 64 * 1024)
                            if not chunk:
                                break
                            copied_bytes += len(chunk)
                            if copied_bytes > self._max_bytes:
                                raise RepositoryPreparationError(
                                    "repository exceeds import byte limit"
                                )
                            output.write(chunk)
                finally:
                    os.close(descriptor)
