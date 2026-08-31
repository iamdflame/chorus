"""Structured logs to stdout, correlated with the trace.

The README argues that the causal DAG *is* the trace, and for the reasoning path that is a
good argument: every model call, tool call and delegation is a content-addressed effect
with its parents recorded, which is more than a span carries. But it says nothing about the
operational path — a container that fails to start, a Firestore permission denial, a
snapshot that will not parse, a quota error that survived its retries. None of those are
effects, because none of them are the fleet reasoning. They are the process having a bad
time, and when an operator opens Cloud Logging they should not find an empty stream.

Cloud Run ingests stdout as structured entries when each line is a JSON object, so this
needs no agent and no exporter. Two fields make it worth having:

    severity                   Cloud Logging's own level field, so filtering works
    logging.googleapis.com/trace   correlates a log line with its Cloud Trace span, so a
                               log and the causal DAG point at each other

Everything else is context, and context is passed as keywords rather than formatted into
the message — a message that has been string-formatted is a message you cannot query.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

SERVICE = os.environ.get("K_SERVICE", "chorus")
_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")


def _trace_field(trace_id: str | None) -> dict[str, str]:
    """Cloud Logging wants the fully-qualified resource name, not a bare hex id."""
    if not trace_id or not _PROJECT:
        return {}
    return {"logging.googleapis.com/trace": f"projects/{_PROJECT}/traces/{trace_id}"}


def log(
    severity: str,
    message: str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    **context: Any,
) -> None:
    """Emit one structured line. Never raises — a logger that can fail is a liability.

    Anything unserialisable is coerced rather than dropped, because a log line that
    vanishes because one field held an odd object is the log line you needed.
    """
    entry: dict[str, Any] = {
        "severity": severity,
        "message": message,
        "service": SERVICE,
        "time": time.time(),
        **_trace_field(trace_id),
    }
    if span_id:
        entry["logging.googleapis.com/spanId"] = span_id
    entry.update(context)
    try:
        line = json.dumps(entry, default=repr)
    except Exception:  # noqa: BLE001 - fall back to something rather than nothing
        line = json.dumps({"severity": severity, "message": message,
                           "service": SERVICE, "context": "unserialisable"})
    print(line, file=sys.stdout, flush=True)


def info(message: str, **context: Any) -> None:
    log("INFO", message, **context)


def warn(message: str, **context: Any) -> None:
    log("WARNING", message, **context)


def error(message: str, **context: Any) -> None:
    log("ERROR", message, **context)


def event(name: str, **context: Any) -> None:
    """A named operational event, for the things worth counting in a dashboard."""
    log("NOTICE", name, event=name, **context)
