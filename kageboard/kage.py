from __future__ import annotations

import subprocess
import shutil
import json
import time
import re
from dataclasses import dataclass, field
from pathlib import Path


KAGE_BIN = shutil.which("kage") or "kage"
DEFAULT_OUT = Path.home() / "data" / "kage"


def _kage_available() -> bool:
    """Check that the kage binary is reachable."""
    return bool(shutil.which("kage"))


def _resolve_host_path(host: str, out: Path) -> Path | None:
    """Resolve a host name to a directory inside *out*, rejecting path traversal.

    Returns the resolved path if it stays within *out*, or None if the host
    contains ``..`` or absolute-path components that would escape the output dir.
    """
    path = (out / host).resolve()
    if not path.is_relative_to(out.resolve()):
        return None
    return path


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


def _build_mirror(path: Path) -> Mirror:
    """Construct a Mirror dataclass from a directory on disk."""
    host = path.name
    pages = len(list(path.rglob("*.html")))
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    cloned_at = ""

    state_file = path / "_kage" / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            cloned_at = state.get("started_at", "")
        except (json.JSONDecodeError, KeyError):
            pass

    zim = path.parent / f"{host}.zim"
    has_zim = zim.exists()

    return Mirror(
        host=host,
        path=path,
        page_count=pages,
        size_bytes=size,
        cloned_at=cloned_at,
        has_zim=has_zim,
        zim_path=str(zim) if has_zim else None,
    )


def list_mirrors(out_dir: Path | None = None) -> list[Mirror]:
    """Scan the output directory for cloned mirrors."""
    out = out_dir or DEFAULT_OUT
    if not out.exists():
        return []

    mirrors: list[Mirror] = []
    for entry in sorted(out.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        mirrors.append(_build_mirror(entry))

    return mirrors


def get_mirror(host: str, out_dir: Path | None = None) -> Mirror | None:
    """Return the mirror for *host*, or None if not found.

    O(1): checks the directory directly instead of scanning all mirrors.
    Rejects path-traversal attempts (``..``, absolute paths).
    """
    out = out_dir or DEFAULT_OUT
    path = _resolve_host_path(host, out)
    if path is None or not path.is_dir():
        return None
    return _build_mirror(path)


class KageNotFoundError(RuntimeError):
    """Raised when the kage binary is not on PATH."""


def _popen(cmd: list[str]) -> subprocess.Popen:
    """Start a kage subprocess, raising a clear error if the binary is missing."""
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        raise KageNotFoundError(
            "kage binary not found on PATH. Install it: "
            "go install github.com/tamnd/kage/cmd/kage@latest"
        )


def clone(url_or_host: str, **flags) -> subprocess.Popen:
    """Start a kage clone in the background. Returns the Popen handle.

    Flag values: True emits a bare --flag, a list/tuple repeats --flag per
    item (for kage's repeatable flags like --exclude), other truthy values
    emit --flag <value>. False/None are skipped.
    """
    cmd = [KAGE_BIN, "clone", url_or_host]
    for key, val in flags.items():
        flag = f"--{key.replace('_', '-')}"
        if val is True:
            cmd.append(flag)
        elif isinstance(val, (list, tuple)):
            for item in val:
                cmd.extend([flag, str(item)])
        elif val is not False and val is not None:
            cmd.extend([flag, str(val)])
    return _popen(cmd)


def serve(host_or_dir: str, addr: str = "127.0.0.1:8880") -> subprocess.Popen:
    """Start serving a mirror."""
    return _popen([KAGE_BIN, "serve", host_or_dir, "--addr", addr])


def pack(host: str, fmt: str = "zim", output: str | None = None) -> subprocess.Popen:
    """Pack a mirror into ZIM or binary."""
    cmd = [KAGE_BIN, "pack", host, "--format", fmt]
    if output:
        cmd.extend(["-o", output])
    return _popen(cmd)


def delete_mirror(host: str, out_dir: Path | None = None) -> bool:
    """Delete a mirror directory.

    Rejects path-traversal attempts — the resolved path must stay within *out*.
    """
    out = out_dir or DEFAULT_OUT
    path = _resolve_host_path(host, out)
    if path is None or not path.exists():
        return False
    shutil.rmtree(path)
    return True


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
