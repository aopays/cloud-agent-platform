"""Container-side argv runner that removes daemonized descendants."""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import time


def _cleanup(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> int:
    if len(sys.argv) != 2 or len(sys.argv[1]) > 1_000_000:
        return 125
    try:
        decoded = base64.urlsafe_b64decode(sys.argv[1].encode())
        argv = json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        return 125
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        return 125
    process = subprocess.Popen(argv, start_new_session=True)
    exit_code = process.wait()
    _cleanup(process)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
