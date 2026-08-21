"""Bounded subprocess execution with process-tree cleanup."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from src.shared.interfaces import CommandResult

from .errors import SandboxPolicyError


class _OutputBudget:
    def __init__(self, limit: int) -> None:
        self.remaining = limit
        self.truncated = False

    def take(self, chunk: bytes) -> bytes:
        kept = chunk[: self.remaining]
        self.remaining -= len(kept)
        if len(kept) != len(chunk):
            self.truncated = True
        return kept


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsJob:
    """Kill every assigned descendant when the handle is closed."""

    _KILL_ON_CLOSE = 0x00002000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100

    def __init__(self, process_id: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self._handle = handle
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_CLOSE
        configured = kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        process_handle = kernel32.OpenProcess(
            self._PROCESS_TERMINATE | self._PROCESS_SET_QUOTA, False, process_id
        )
        try:
            if not configured or not process_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel32.AssignProcessToJobObject(handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close()
            raise
        finally:
            if process_handle:
                kernel32.CloseHandle(process_handle)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def terminate(self) -> None:
        if self._handle and not self._kernel32.TerminateJobObject(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())


async def _read_stream(reader: asyncio.StreamReader, budget: _OutputBudget) -> bytes:
    output = bytearray()
    while chunk := await reader.read(8192):
        output.extend(budget.take(chunk))
    return bytes(output)


def validate_argv(argv: Sequence[str], *, max_items: int, max_argument_bytes: int) -> None:
    if not argv or len(argv) > max_items:
        raise SandboxPolicyError("argv must be non-empty and within the item limit")
    for argument in argv:
        if not isinstance(argument, str) or not argument or "\x00" in argument:
            raise SandboxPolicyError("each argv item must be a non-empty NUL-free string")
        if len(argument.encode("utf-8")) > max_argument_bytes:
            raise SandboxPolicyError("argv item exceeds the byte limit")


async def terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        if process.returncode is not None:
            # Windows has no safe stdlib process-group handle after the parent exits.
            return
        taskkill = str(
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
        )
        with contextlib.suppress(OSError):
            killer = await asyncio.create_subprocess_exec(
                taskkill,
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
    else:
        kill_process_group = getattr(os, "killpg", None)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if kill_process_group is not None:
                kill_process_group(process.pid, signal.SIGTERM)
        if process.returncode is None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=0.5)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if kill_process_group is not None:
                    kill_process_group(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=2)


async def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    output_bytes: int,
    cancel_event: asyncio.Event,
    environment: Mapping[str, str] | None = None,
    on_started: Callable[[asyncio.subprocess.Process], None] | None = None,
) -> CommandResult:
    """Execute argv directly; shell parsing is deliberately unavailable."""

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    started = time.monotonic()
    gate: Path | None = None
    launched_argv = list(argv)
    if os.name == "nt":
        # asyncio cannot create a process suspended. A trusted gate runner prevents the
        # child from spawning descendants before it has been assigned to the Job Object.
        gate = cwd / f".cap-start-{uuid.uuid4().hex}"
        encoded = base64.urlsafe_b64encode(json.dumps(launched_argv).encode()).decode()
        launched_argv = [
            getattr(sys, "_base_executable", sys.executable),
            str(Path(__file__).with_name("windows_runner.py")),
            str(gate),
            encoded,
        ]
    process = await asyncio.create_subprocess_exec(
        *launched_argv,
        cwd=cwd,
        env=dict(environment) if environment is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    windows_job: _WindowsJob | None = None
    if os.name == "nt":
        assert gate is not None
        try:
            windows_job = _WindowsJob(process.pid)
        except OSError as exc:
            await terminate_process_tree(process)
            raise SandboxPolicyError("could not establish a Windows process job") from exc
        gate.touch(mode=0o600, exist_ok=False)
    if on_started is not None:
        on_started(process)
    assert process.stdout is not None
    assert process.stderr is not None
    budget = _OutputBudget(output_bytes)
    stdout_task = asyncio.create_task(_read_stream(process.stdout, budget))
    stderr_task = asyncio.create_task(_read_stream(process.stderr, budget))
    wait_task = asyncio.create_task(process.wait())
    cancel_task = asyncio.create_task(cancel_event.wait())
    timed_out = False
    try:
        done, _ = await asyncio.wait(
            {wait_task, cancel_task},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wait_task not in done:
            timed_out = not cancel_event.is_set()
            if windows_job is not None:
                windows_job.terminate()
            else:
                await terminate_process_tree(process)
        await wait_task
        # A command may daemonize children and exit successfully. Reap its process group too.
        if windows_job is not None:
            windows_job.terminate()
        else:
            await terminate_process_tree(process)
    except asyncio.CancelledError:
        if windows_job is not None:
            windows_job.terminate()
        else:
            await terminate_process_tree(process)
        raise
    finally:
        if windows_job is not None:
            windows_job.close()
        if gate is not None:
            with contextlib.suppress(OSError):
                gate.unlink()
        cancel_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cancel_task
    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    stdout_encoded = stdout_text.encode("utf-8")
    if len(stdout_encoded) > output_bytes:
        budget.truncated = True
        stdout_text = stdout_encoded[:output_bytes].decode("utf-8", errors="ignore")
        stderr_text = ""
    else:
        remaining = output_bytes - len(stdout_encoded)
        stderr_encoded = stderr_text.encode("utf-8")
        if len(stderr_encoded) > remaining:
            budget.truncated = True
            stderr_text = stderr_encoded[:remaining].decode("utf-8", errors="ignore")
    return CommandResult(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=budget.truncated,
        timed_out=timed_out,
    )
