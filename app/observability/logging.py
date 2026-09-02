"""Logging. One configuration, structured output, isolated per run.

Three problems this module exists to solve, each of which was real before it:

1. **Four configurations.** `main.py`, `api/server.py`, `behaviour/main.py`
   and two ad-hoc handler attachments each set logging up their own way, so
   the same event looked different depending on which entry point ran it,
   and changing the format meant changing four files.

2. **Cross-contamination between concurrent runs.** The API attached a
   per-run `FileHandler` to the ROOT logger. Both run managers allow two
   concurrent runs, so run A's lines landed in run B's file and vice versa.
   A per-run log that contains another run's lines is worse than no per-run
   log, because it is believed. The fix is a filter keyed on a `contextvar`:
   a handler accepts a record only if the record was emitted inside its own
   run, which is correct however many runs overlap.

3. **Logs as a redaction bypass.** Evidence is redacted at capture, but a URL
   with a session token in the query string reaches a log through a
   completely different path — an f-string in a warning. Redaction therefore
   has to live on the log path too, not only on the evidence path.

Output is JSON on the file sink, one object per line, so it can be queried
rather than grepped. The console stays human-readable, because a developer
reading a terminal is not a log aggregator.
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from app.safety import redaction

#: Libraries that are informative at DEBUG and noise at INFO.
_NOISY = ("httpx", "httpcore", "urllib3", "asyncio", "websockets",
          "playwright", "openpyxl", "PIL", "uvicorn.access", "watchfiles")

#: Fields already on a LogRecord that must not be duplicated into the JSON
#: payload as "extra" data.
_STANDARD = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


# ── run context ───────────────────────────────────────────────────────────

@dataclass
class RunContext:
    """What every record emitted inside one run should carry."""

    run_id: str
    kind: str = "assessment"            # "assessment" | "behaviour"
    target: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_CURRENT: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "agentqa_run", default=None)


def current_run() -> RunContext | None:
    return _CURRENT.get()


@contextmanager
def bind_run(ctx: RunContext) -> Iterator[RunContext]:
    """Attach a run to this task and everything it awaits.

    `contextvars` is what makes this correct under asyncio: a value set here
    is visible to every coroutine this task spawns and invisible to a
    sibling run's task, which is exactly the isolation a per-run log needs.
    """
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


# ── filters ───────────────────────────────────────────────────────────────

class RunContextFilter(logging.Filter):
    """Stamp every record with the run it came from. Never rejects."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _CURRENT.get()
        record.run_id = ctx.run_id if ctx else None
        record.run_kind = ctx.kind if ctx else None
        record.target = ctx.target if ctx else None
        return True


class OnlyThisRun(logging.Filter):
    """Accept a record only if it was emitted inside one specific run.

    This is what replaces attaching a FileHandler to the root logger. The
    handler is still on the root logger — it has to be, to catch every
    module — but it writes only its own run's records.
    """

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "run_id", None) == self.run_id


class RedactingFilter(logging.Filter):
    """Strip secrets from the rendered message before it is written.

    Runs on the formatted message rather than the format arguments, because a
    token can arrive either way and only the rendered text sees both.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:                                       # noqa: BLE001
            return True
        cleaned = redaction.redact_secrets_in_text(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


# ── formatters ────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """One JSON object per line. Machine-queryable, stable field names."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S",
                                time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("run_id", "run_kind", "target"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)[:4000]
        # Anything passed via extra= lands here, which is what makes an event
        # queryable: `event="model_timeout"` beats grepping for prose.
        for key, value in record.__dict__.items():
            if key not in _STANDARD and key not in payload:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)[:200]
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """What a person reads. The run id is abbreviated, not dropped."""

    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s %(name)-26s %(message)s",
                         datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        run_id = getattr(record, "run_id", None)
        return f"{line}  [{run_id[:8]}]" if run_id else line


# ── configuration ─────────────────────────────────────────────────────────

_CONFIGURED = False


def configure(*, level: str = "INFO", console: bool = True,
              json_path: str | Path | None = None,
              max_bytes: int = 32 * 1024 * 1024, backups: int = 5,
              force: bool = False) -> None:
    """Configure logging once, for every entry point.

    `json_path` is the process-wide log. A per-run log is added separately by
    `run_scope`, which is the only thing that knows a run id.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    resolved = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(resolved)
    # NOTE: the stamping filter goes on every HANDLER, never on the root
    # logger. A logger's filters run only for records logged directly to it;
    # records propagated up from `app.behaviour.brain` and friends skip them
    # entirely, which would leave every record unstamped and every per-run
    # log empty. Handler filters run for everything a handler receives.

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(ConsoleFormatter())
        stream.addFilter(RunContextFilter())
        stream.addFilter(RedactingFilter())
        root.addHandler(stream)

    if json_path:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Rotation is not optional on a long-lived server: an unbounded log
        # is a disk-full outage with a delay fuse.
        rotating = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        rotating.setFormatter(JsonFormatter())
        rotating.addFilter(RunContextFilter())
        rotating.addFilter(RedactingFilter())
        root.addHandler(rotating)

    for noisy in _NOISY:
        logging.getLogger(noisy).setLevel(
            max(resolved, logging.WARNING))

    _CONFIGURED = True


@contextmanager
def run_scope(run_id: str, *, kind: str = "assessment",
              target: str | None = None,
              log_path: str | Path | None = None) -> Iterator[RunContext]:
    """Bind a run and give it its own JSON log, isolated from other runs.

    The handler goes on the root logger so it sees every module, but its
    `OnlyThisRun` filter means it writes nothing that did not happen inside
    this run — correct even when another run is executing concurrently.
    """
    ctx = RunContext(run_id=run_id, kind=kind, target=target)
    handler: logging.Handler | None = None
    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        # Order matters: stamp first, then admit only this run's records.
        handler.addFilter(RunContextFilter())
        handler.addFilter(OnlyThisRun(run_id))
        handler.addFilter(RedactingFilter())
        logging.getLogger().addHandler(handler)
    try:
        with bind_run(ctx):
            yield ctx
    finally:
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()


def event(logger: logging.Logger, name: str, message: str = "",
          level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured, queryable event.

    `event(log, "model_timeout", deadline_s=45, fallback="heuristic")` is
    answerable with a query. The same fact in prose is answerable only by
    someone who already knows the wording.
    """
    logger.log(level, message or name, extra={"event": name, **fields})


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


def level_from_env(default: str = "INFO") -> str:
    return os.environ.get("AGENTQA_LOG_LEVEL", default)
