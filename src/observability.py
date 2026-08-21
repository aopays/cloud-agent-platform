"""Minimal JSON logging without task instructions, tool output, or secrets."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for name in (
            "task_id",
            "attempt_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
        ):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exceptionType"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_cap_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._cap_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)
