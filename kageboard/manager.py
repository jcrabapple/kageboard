from __future__ import annotations

import time
import json
import subprocess
import threading
from pathlib import Path

from .kage import (
    DEFAULT_OUT,
    Mirror,
    list_mirrors,
    get_mirror,
    clone,
    serve,
    pack,
    delete_mirror,
    kage_version,
    KageNotFoundError,
)


# In-memory job tracking (simple; resets on restart)
_jobs: dict[str, dict] = {}
_job_lock = threading.Lock()


def start_clone(url: str, **flags) -> str:
    """Start a clone job, return job ID.

    Raises KageNotFoundError if the kage binary is missing.
    """
    host = url.replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
    job_id = f"clone-{host}-{int(time.time())}"

    proc = clone(url, **flags)  # may raise KageNotFoundError
    job = {
        "id": job_id,
        "host": host,
        "url": url,
        "status": "running",
        "proc": proc,
        "pages": 0,
        "assets": 0,
        "errors": 0,
        "lines": [],
        "started_at": time.time(),
    }
    with _job_lock:
        _jobs[job_id] = job

    # Spin up reader thread
    t = threading.Thread(target=_read_output, args=(job_id, proc), daemon=True)
    t.start()

    return job_id


def _read_output(job_id: str, proc):
    job = _jobs.get(job_id)
    if not job:
        return

    for line in proc.stdout:
        with _job_lock:
            job["lines"].append(line)
        # Parse progress
        from .kage import parse_clone_output
        parsed = parse_clone_output(line)
        if parsed:
            if parsed["type"] == "page":
                with _job_lock:
                    job["pages"] = parsed["current"]
            elif parsed["type"] == "done":
                with _job_lock:
                    job["pages"] = parsed["pages"]
                    job["assets"] = parsed["assets"]
                    job["errors"] = parsed["errors"]

    proc.wait()
    with _job_lock:
        job["status"] = "done" if proc.returncode == 0 else "error"
        job["exit_code"] = proc.returncode
        job["finished_at"] = time.time()


def get_job(job_id: str) -> dict | None:
    """Return a job snapshot for API consumers (excludes proc/lines)."""
    with _job_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        # Return a snapshot without proc/lines for API consumers
        return {k: v for k, v in job.items() if k not in ("proc", "lines")}


def get_job_raw(job_id: str) -> dict | None:
    """Return the raw job dict including lines (for WebSocket streaming).

    Caller should hold no assumptions about thread safety — the dict is
    returned by reference and may be mutated by the reader thread. Use
    _job_lock if you need a consistent snapshot.
    """
    with _job_lock:
        return _jobs.get(job_id)


def get_jobs() -> list[dict]:
    with _job_lock:
        return [
            {k: v for k, v in j.items() if k not in ("proc", "lines")}
            for j in _jobs.values()
        ]


def start_serve(host: str, addr: str = "127.0.0.1:8890") -> subprocess.Popen:
    return serve(host, addr)


def start_pack(host: str, fmt: str = "zim") -> str:
    """Start a pack job, return job ID.

    Raises KageNotFoundError if the kage binary is missing.
    """
    job_id = f"pack-{host}-{int(time.time())}"

    proc = pack(host, fmt)  # may raise KageNotFoundError
    job = {
        "id": job_id,
        "host": host,
        "format": fmt,
        "status": "running",
        "proc": proc,
        "lines": [],
        "started_at": time.time(),
    }
    with _job_lock:
        _jobs[job_id] = job

    t = threading.Thread(target=_read_simple_output, args=(job_id, proc), daemon=True)
    t.start()
    return job_id


def _read_simple_output(job_id: str, proc):
    job = _jobs.get(job_id)
    if not job:
        return
    for line in proc.stdout:
        job["lines"].append(line)
    proc.wait()
    job["status"] = "done" if proc.returncode == 0 else "error"
    job["exit_code"] = proc.returncode
    job["finished_at"] = time.time()