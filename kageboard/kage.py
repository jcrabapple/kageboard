from __future__ import annotations

import subprocess
import shutil
import json
import os
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


KAGE_BIN = shutil.which("kage") or "kage"
DEFAULT_OUT = Path.home() / "data" / "kage"


@dataclass
class CloneProgress:
    host: str
    url: str
    status: str  # "running" | "done" | "error"
    pages: int = 0
    assets: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    message: str = ""

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at


@dataclass
class Mirror:
    host: str
    path: Path
    page_count: int = 0
    size_bytes: int = 0
    cloned_at: str = ""  # ISO timestamp
    has_zim: bool = False
    zim_path: str | None = None


def list_mirrors(out_dir: Path | None = None) -> list[Mirror]:
    """Scan the output directory for cloned mirrors."""
    out = out_dir or DEFAULT_OUT
    mirrors: list[Mirror] = []
    if not out.exists():
        return mirrors

    for entry in sorted(out.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        host = entry.name
        pages = len(list(entry.rglob("*.html")))
        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        cloned_at = ""
        zim_path = None
        has_zim = False

        # Check for state file
        state_file = entry / "_kage" / "state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                cloned_at = state.get("started_at", "")
            except (json.JSONDecodeError, KeyError):
                pass

        # Check for ZIM
        zim = out.parent / f"{host}.zim" if out.parent != out else out.with_name(out.name + "_zims") / f"{host}.zim"
        if zim.exists():
            has_zim = True
            zim_path = str(zim)

        mirrors.append(Mirror(
            host=host,
            path=entry,
            page_count=pages,
            size_bytes=size,
            cloned_at=cloned_at,
            has_zim=has_zim,
            zim_path=zim_path,
        ))

    return mirrors


def get_mirror(host: str, out_dir: Path | None = None) -> Mirror | None:
    mirrors = list_mirrors(out_dir)
    for m in mirrors:
        if m.host == host:
            return m
    return None


def clone(url_or_host: str, **flags) -> subprocess.Popen:
    """Start a kage clone in the background. Returns the Popen handle."""
    cmd = [KAGE_BIN, "clone", url_or_host]
    for key, val in flags.items():
        if val is True:
            cmd.append(f"--{key.replace('_', '-')}")
        elif val is not False and val is not None:
            cmd.append(f"--{key.replace('_', '-')}")
            cmd.append(str(val))
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def serve(host_or_dir: str, addr: str = "127.0.0.1:8880") -> subprocess.Popen:
    """Start serving a mirror."""
    return subprocess.Popen(
        [KAGE_BIN, "serve", host_or_dir, "--addr", addr],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def pack(host: str, fmt: str = "zim", output: str | None = None) -> subprocess.Popen:
    """Pack a mirror into ZIM or binary."""
    cmd = [KAGE_BIN, "pack", host, "--format", fmt]
    if output:
        cmd.extend(["-o", output])
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def delete_mirror(host: str, out_dir: Path | None = None) -> bool:
    """Delete a mirror directory."""
    out = out_dir or DEFAULT_OUT
    path = out / host
    if path.exists():
        shutil.rmtree(path)
        return True
    return False


def parse_clone_output(line: str) -> dict | None:
    """Parse a line of kage clone output into structured progress."""
    # kage outputs lines like: "  [1/10] GET /page → 200 (2.3s)"
    # and: "  ✗ /page: timeout"
    # and: "Done. 42 pages, 156 assets, 3 errors in 12.4s"
    line = line.strip()
    if not line:
        return None

    m = re.match(r".*\[(\d+)/(\d+)\]", line)
    if m:
        return {"type": "page", "current": int(m.group(1)), "total": int(m.group(2))}

    m = re.match(r"Done\.\s+(\d+)\s+pages?,\s+(\d+)\s+assets?,?\s+(\d+)?\s*errors?", line)
    if m:
        return {
            "type": "done",
            "pages": int(m.group(1)),
            "assets": int(m.group(2)),
            "errors": int(m.group(3) or 0),
        }

    if "✗" in line or "error" in line.lower() or "timeout" in line.lower():
        return {"type": "error", "message": line}

    return None


def kage_version() -> str:
    try:
        r = subprocess.run([KAGE_BIN, "--version"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return "unknown"