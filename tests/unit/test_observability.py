"""Logging: one configuration, structured output, isolated per run.

The property that matters most here is isolation. Two runs may execute
concurrently — both managers use `Semaphore(2)` — and a per-run log that
contains another run's lines is worse than no per-run log at all, because a
reader believes it.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app import observability
from app.observability.logging import (JsonFormatter, RedactingFilter,
                                       RunContextFilter)


@pytest.fixture(autouse=True)
def _clean_logging():
    root = logging.getLogger()
    before = list(root.handlers), root.level, list(root.filters)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    root.handlers, root.level, root.filters = (
        before[0], before[1], list(before[2]))


def _read(path):
    return [json.loads(line) for line in
            path.read_text().splitlines() if line.strip()]


# ── isolation ────────────────────────────────────────────────────────────

def test_two_concurrent_runs_do_not_write_into_each_others_logs(tmp_path):
    """The bug this module was written to remove.

    Previously each run attached an unfiltered FileHandler to the root
    logger, so with two runs in flight every line landed in both files.
    """
    observability.configure(level="INFO", console=False, force=True)
    log = logging.getLogger("app.test")

    a_path, b_path = tmp_path / "a.jsonl", tmp_path / "b.jsonl"

    async def run(run_id: str, path, message: str):
        with observability.run_scope(run_id, target="https://x", log_path=path):
            for _ in range(5):
                log.info(message)
                await asyncio.sleep(0)      # interleave with the other run

    async def both():
        await asyncio.gather(run("aaaa1111", a_path, "FROM-A"),
                             run("bbbb2222", b_path, "FROM-B"))

    asyncio.run(both())

    a_lines, b_lines = _read(a_path), _read(b_path)
    assert a_lines and b_lines
    assert all(r["msg"] == "FROM-A" for r in a_lines), "run B leaked into A"
    assert all(r["msg"] == "FROM-B" for r in b_lines), "run A leaked into B"
    assert all(r["run_id"] == "aaaa1111" for r in a_lines)


def test_a_record_outside_any_run_reaches_no_per_run_log(tmp_path):
    observability.configure(level="INFO", console=False, force=True)
    log = logging.getLogger("app.test")
    path = tmp_path / "run.jsonl"
    with observability.run_scope("cccc3333", log_path=path):
        log.info("inside")
    log.info("outside")           # after the scope has exited
    lines = _read(path)
    assert [r["msg"] for r in lines] == ["inside"]


# ── structure ────────────────────────────────────────────────────────────

def test_the_file_sink_is_one_json_object_per_line(tmp_path):
    path = tmp_path / "out.jsonl"
    observability.configure(level="INFO", console=False, json_path=path,
                            force=True)
    logging.getLogger("app.test").info("hello")
    record = _read(path)[0]
    assert record["level"] == "INFO"
    assert record["logger"] == "app.test"
    assert record["msg"] == "hello"
    assert record["ts"].endswith("Z")


def test_structured_events_are_queryable_fields_not_prose(tmp_path):
    path = tmp_path / "out.jsonl"
    observability.configure(level="INFO", console=False, json_path=path,
                            force=True)
    observability.event(logging.getLogger("app.test"), "model_timeout",
                        "model did not answer", deadline_s=45,
                        fallback="heuristic")
    record = _read(path)[0]
    assert record["event"] == "model_timeout"
    assert record["deadline_s"] == 45
    assert record["fallback"] == "heuristic"


def test_a_run_stamps_its_id_and_target_onto_every_record(tmp_path):
    path = tmp_path / "out.jsonl"
    observability.configure(level="INFO", console=False, json_path=path,
                            force=True)
    with observability.run_scope("dddd4444", kind="behaviour",
                                 target="https://example.com"):
        logging.getLogger("app.test").warning("something")
    record = _read(path)[0]
    assert record["run_id"] == "dddd4444"
    assert record["run_kind"] == "behaviour"
    assert record["target"] == "https://example.com"


def test_an_unserialisable_extra_does_not_lose_the_record(tmp_path):
    path = tmp_path / "out.jsonl"
    observability.configure(level="INFO", console=False, json_path=path,
                            force=True)
    observability.event(logging.getLogger("app.test"), "odd",
                        thing=object())
    record = _read(path)[0]
    assert record["event"] == "odd"
    assert isinstance(record["thing"], str)


# ── redaction on the log path ────────────────────────────────────────────

def test_a_secret_in_a_log_message_is_redacted_before_it_is_written(tmp_path):
    """Evidence is redacted at capture; logs are a different path entirely."""
    path = tmp_path / "out.jsonl"
    observability.configure(level="INFO", console=False, json_path=path,
                            force=True)
    jwt = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
           "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    logging.getLogger("app.test").warning("call failed with token %s", jwt)
    written = path.read_text()
    assert jwt not in written, "a JWT reached the log verbatim"


# ── configuration ────────────────────────────────────────────────────────

def test_configure_is_idempotent_unless_forced(tmp_path):
    observability.configure(level="INFO", console=False,
                            json_path=tmp_path / "a.jsonl", force=True)
    count = len(logging.getLogger().handlers)
    observability.configure(level="DEBUG", console=True)     # not forced
    assert len(logging.getLogger().handlers) == count


def test_noisy_libraries_are_quietened(tmp_path):
    observability.configure(level="INFO", console=False, force=True)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("playwright").level >= logging.WARNING
