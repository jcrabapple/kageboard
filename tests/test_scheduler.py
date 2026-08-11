from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kageboard import scheduler
from kageboard.manager import _jobs, _job_lock


@pytest.fixture
def sched_dir(monkeypatch, tmp_path):
    """Point schedule state + mirror root at a temp dir."""
    monkeypatch.setattr("kageboard.kage.DEFAULT_OUT", tmp_path)
    yield tmp_path


def _mk_mirror(out: Path, host: str):
    d = out / host
    d.mkdir(exist_ok=True)
    (d / "index.html").write_text("<html></html>")


def test_set_and_get_schedule(sched_dir):
    _mk_mirror(sched_dir, "example.com")
    entry = scheduler.set_schedule("example.com", "daily")
    assert entry["interval"] == "daily"
    assert entry["last_run"] is None

    got = scheduler.get_schedule("example.com")
    assert got["interval"] == "daily"


def test_set_schedule_off_removes(sched_dir):
    scheduler.set_schedule("example.com", "weekly")
    assert scheduler.get_schedule("example.com") is not None
    result = scheduler.set_schedule("example.com", "off")
    assert result is None
    assert scheduler.get_schedule("example.com") is None


def test_set_schedule_rejects_bad_interval(sched_dir):
    with pytest.raises(ValueError):
        scheduler.set_schedule("example.com", "hourly")


def test_schedule_persists_to_disk(sched_dir):
    scheduler.set_schedule("example.com", "weekly")
    state = sched_dir / ".kageboard-schedules.json"
    assert state.exists()
    data = json.loads(state.read_text())
    assert data["example.com"]["interval"] == "weekly"


def test_load_schedules_corrupt_file(sched_dir):
    (sched_dir / ".kageboard-schedules.json").write_text("not json{{{")
    assert scheduler.load_schedules() == {}


def test_due_hosts_never_run(sched_dir):
    scheduler.set_schedule("example.com", "daily")
    assert "example.com" in scheduler.due_hosts()


def test_due_hosts_interval_elapsed(sched_dir):
    scheduler.set_schedule("example.com", "daily")
    schedules = scheduler.load_schedules()
    schedules["example.com"]["last_run"] = time.time() - 90000  # 25h ago
    scheduler.save_schedules(schedules)
    assert "example.com" in scheduler.due_hosts()


def test_due_hosts_not_yet_due(sched_dir):
    scheduler.set_schedule("example.com", "weekly")
    schedules = scheduler.load_schedules()
    schedules["example.com"]["last_run"] = time.time() - 3600  # 1h ago
    scheduler.save_schedules(schedules)
    assert scheduler.due_hosts() == []


def test_run_due_starts_refresh(sched_dir):
    _mk_mirror(sched_dir, "example.com")
    scheduler.set_schedule("example.com", "daily")

    calls = []
    started = scheduler.run_due(starter=lambda host: calls.append(host) or f"job-{host}")
    assert started == ["example.com"]
    assert calls == ["example.com"]

    entry = scheduler.get_schedule("example.com")
    assert entry["last_run"] is not None
    assert entry["last_job_id"] == "job-example.com"


def test_run_due_skips_missing_mirror(sched_dir):
    """Schedules for deleted mirrors don't fire (but are kept)."""
    scheduler.set_schedule("ghost.com", "daily")
    calls = []
    started = scheduler.run_due(starter=lambda host: calls.append(host) or "j")
    assert started == []
    assert calls == []
    assert scheduler.get_schedule("ghost.com") is not None


def test_run_due_not_due_twice(sched_dir):
    """A mirror that just ran isn't due again immediately."""
    _mk_mirror(sched_dir, "example.com")
    scheduler.set_schedule("example.com", "daily")
    scheduler.run_due(starter=lambda host: "job-1")
    assert scheduler.run_due(starter=lambda host: "job-2") == []


def test_run_due_starter_failure_isolated(sched_dir):
    _mk_mirror(sched_dir, "bad.com")
    _mk_mirror(sched_dir, "good.com")
    scheduler.set_schedule("bad.com", "daily")
    scheduler.set_schedule("good.com", "daily")

    def flaky(host):
        if host == "bad.com":
            raise RuntimeError("kage exploded")
        return f"job-{host}"

    started = scheduler.run_due(starter=flaky)
    assert started == ["good.com"]


@pytest.fixture(autouse=True)
def clean_jobs():
    with _job_lock:
        _jobs.clear()


def test_tick_records_finished_job_status(sched_dir):
    """tick() persists the outcome of a job the scheduler started."""
    _mk_mirror(sched_dir, "example.com")
    scheduler.set_schedule("example.com", "daily")

    scheduler.run_due(starter=lambda host: "job-finished")
    # Simulate the job finishing in the manager's registry
    with _job_lock:
        _jobs["job-finished"] = {
            "id": "job-finished", "status": "done", "proc": None,
            "lines": [], "pages": 5, "started_at": 0,
        }

    scheduler.tick()  # records outcome; not due again so nothing starts
    entry = scheduler.get_schedule("example.com")
    assert entry["last_status"] == "done"
    assert entry["last_job_id"] is None


def test_start_is_idempotent():
    scheduler.start(tick_seconds=3600)
    scheduler.start(tick_seconds=3600)  # no exception, single thread


def test_tick_reconciles_stale_job_after_restart(sched_dir):
    """A last_job_id pointing at a lost in-memory job is cleared, not
    left showing 'running' forever."""
    _mk_mirror(sched_dir, "example.com")
    scheduler.set_schedule("example.com", "daily")
    schedules = scheduler.load_schedules()
    schedules["example.com"]["last_run"] = time.time()
    schedules["example.com"]["last_job_id"] = "job-lost-in-restart"
    scheduler.save_schedules(schedules)

    scheduler.tick()
    entry = scheduler.get_schedule("example.com")
    assert entry["last_job_id"] is None
    assert entry["last_status"] == "unknown"


# ── manager hygiene ──


def test_host_from_url_variants():
    from kageboard.manager import _host_from_url
    assert _host_from_url("https://example.com/path") == "example.com"
    assert _host_from_url("HTTPS://EXAMPLE.com/") == "example.com"
    assert _host_from_url("example.com") == "example.com"
    assert _host_from_url("example.com/docs/") == "example.com"


def test_prune_jobs_evicts_old_finished():
    from kageboard.manager import _jobs, _job_lock, _prune_jobs
    with _job_lock:
        _jobs["old-done"] = {"id": "old-done", "status": "done",
                             "finished_at": time.time() - 7200, "proc": None, "lines": []}
        _jobs["fresh-done"] = {"id": "fresh-done", "status": "done",
                               "finished_at": time.time(), "proc": None, "lines": []}
        _jobs["still-running"] = {"id": "still-running", "status": "running",
                                  "proc": None, "lines": []}
    _prune_jobs()
    with _job_lock:
        assert "old-done" not in _jobs
        assert "fresh-done" in _jobs
        assert "still-running" in _jobs
    with _job_lock:
        del _jobs["fresh-done"]
        del _jobs["still-running"]
