"""Windows start gate used to close the Job Object assignment race."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        return 125
    gate = Path(sys.argv[1])
    deadline = time.monotonic() + 10
    while not gate.is_file():
        if time.monotonic() >= deadline:
            return 125
        time.sleep(0.01)
    try:
        argv = json.loads(base64.urlsafe_b64decode(sys.argv[2].encode()))
    except (ValueError, TypeError, json.JSONDecodeError):
        return 125
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        return 125
    return subprocess.call(argv)


if __name__ == "__main__":
    raise SystemExit(main())
