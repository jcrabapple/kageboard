"""Scheduled mirror refreshes.

Persists per-mirror refresh schedules in <out>/.kageboard-schedules.json and
runs due refreshes as normal clone jobs (kage clone --refresh) from a daemon
thread. Intervals are coarse on purpose — "daily" and "weekly" cover the
real use cases without turning the UI into cron.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from . import kage as kage_mod

INTERVALS = {
    "daily": 86400,
    "weekly": 604800,
}

DEFAULT_TICK = 60  # seconds between scheduler wake-ups

_lock = threading.Lock()
_started = False


def _state_file() -> Path:
    # Read DEFAULT_OUT at call time so tests can monkeypatch it.
    return kage_mod.DEFAULT_OUT / ".kageboard-schedules.json"


def load_schedules() -> dict:
    """Return {host: {interval, last_run, last_status, last_job_id}}."""
    try:
        data = json.loads(_state_file().read_text())
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_schedules(schedules: dict) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(schedules, indent=2))
    tmp.replace(path)  # atomic on POSIX


def get_schedule(host: str) -> dict | None:
    """Schedule info for one mirror, or None if not scheduled."""
    with _lock:
        return load_schedules().get(host)


def set_schedule(host: str, interval: str) -> dict | None:
    """Set a mirror's refresh interval. "off" removes the schedule.

    Returns the stored entry, or None when cleared.
    Raises ValueError for unknown intervals.
    """
    if interval == "off":
        with _lock:
            schedules = load_schedules()
            schedules.pop(host, None)
            save_schedules(schedules)
        return None
    if interval not in INTERVALS:
        raise ValueError(f"unknown interval: {interval!r} (use daily|weekly|off)")
    with _lock:
        schedules = load_schedules()
        entry = schedules.setdefault(host, {})
        entry["interval"] = interval
        entry.setdefault("last_run", None)
        entry.setdefault("last_status", None)
        entry.setdefault("last_job_id", None)
        save_schedules(schedules)
        return dict(entry)


def due_hosts(now: float | None = None) -> list[str]:
    """Hosts whose refresh is due (never run, or interval elapsed)."""
    now = now if now is not None else time.time()
    with _lock:
        schedules = load_schedules()
    due = []
    for host, entry in schedules.items():
        interval = INTERVALS.get(entry.get("interval"))
        if interval is None:
            continue
        last_run = entry.get("last_run")
        if last_run is None or now - last_run >= interval:
            due.append(host)
    return due


def _update_job_outcomes() -> None:
    """Persist the final status of jobs we started (jobs are in-memory,
    so this only works while the process that started them is alive)."""
    from .manager import get_job

    with _lock:
        schedules = load_schedules()
        changed = False
        for entry in schedules.values():
            job_id = entry.get("last_job_id")
            if not job_id:
                continue
            job = get_job(job_id)
            if job is None:
                # Process restarted — the in-memory job is gone, so the
                # outcome is unknowable. Clear the pointer or the UI shows
                # "running" forever.
                entry["last_job_id"] = None
                entry["last_status"] = entry.get("last_status") or "unknown"
                changed = True
            elif job.get("status") in ("done", "error"):
                entry["last_status"] = job["status"]
                entry["last_job_id"] = None
                changed = True
        if changed:
            save_schedules(schedules)


def run_due(now: float | None = None, starter=None) -> list[str]:
    """Start refreshes for all due mirrors. Returns hosts that were started.

    *starter* is injectable for tests; defaults to a real clone job.
    Skips mirrors that no longer exist on disk.
    """
    if starter is None:
        from .manager import start_clone

        def _default_starter(host):
            return start_clone(f"https://{host}", refresh=True)

        starter = _default_starter

    now = now if now is not None else time.time()
    started = []
    for host in due_hosts(now):
        if kage_mod.get_mirror(host) is None:
            continue  # mirror deleted; leave the schedule, it's harmless
        try:
            job_id = starter(host)
        except Exception:
            continue  # don't let one failure starve the others
        with _lock:
            schedules = load_schedules()
            if host in schedules:
                schedules[host]["last_run"] = now
                schedules[host]["last_job_id"] = job_id
                save_schedules(schedules)
        started.append(host)
    return started


def tick(now: float | None = None) -> list[str]:
    """One scheduler pass: record finished jobs, then start due ones."""
    _update_job_outcomes()
    return run_due(now)


def _loop(tick_seconds: int) -> None:
    while True:
        try:
            tick()
        except Exception:
            pass  # the scheduler must never take the app down
        time.sleep(tick_seconds)


def start(tick_seconds: int = DEFAULT_TICK) -> None:
    """Start the background scheduler thread (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, args=(tick_seconds,), daemon=True,
                         name="kageboard-scheduler")
    t.start()
