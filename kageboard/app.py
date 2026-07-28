from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response
from flask_sock import Sock

from .kage import DEFAULT_OUT, list_mirrors, get_mirror, delete_mirror, kage_version
from .manager import start_clone, get_job, get_jobs, start_pack

app = Flask(__name__)
sock = Sock(app)


@app.route("/")
def index():
    mirrors = list_mirrors()
    version = kage_version()
    return render_template("index.html", mirrors=mirrors, version=version)


@app.route("/mirrors")
def mirrors_list():
    """HTMX partial — mirror grid."""
    mirrors = list_mirrors()
    return render_template("_mirrors.html", mirrors=mirrors)


@app.route("/mirrors/<host>")
def mirror_detail(host: str):
    mirror = get_mirror(host)
    if not mirror:
        return "Not found", 404

    # Build page listing
    pages = []
    if mirror.path.exists():
        for f in sorted(mirror.path.rglob("*.html")):
            rel = str(f.relative_to(mirror.path))
            pages.append({
                "path": rel,
                "title": _extract_title(f),
                "size": f.stat().st_size,
            })

    return render_template("detail.html", mirror=mirror, pages=pages)


@app.route("/mirrors/<host>/browse")
@app.route("/mirrors/<host>/browse/<path:subpath>")
def mirror_browse(host: str, subpath: str = ""):
    """Serve mirrored content through the app."""
    mirror = get_mirror(host)
    if not mirror:
        return "Not found", 404

    file_path = mirror.path / subpath if subpath else mirror.path / "index.html"
    if not file_path.exists():
        return "Not found", 404

    return Response(
        file_path.read_bytes(),
        mimetype="text/html",
        headers={"X-Kageboard-Host": host},
    )


@app.route("/api/clone", methods=["POST"])
def api_clone():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400

    flags = {}
    for f in ["max_pages", "max_depth", "scope_prefix", "scroll", "subdomains"]:
        if f in data and data[f]:
            flags[f] = data[f]

    job_id = start_clone(url, **flags)
    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        k: v for k, v in job.items()
        if k not in ("proc", "lines")
    })


@app.route("/api/jobs")
def api_jobs():
    return jsonify(get_jobs())


@app.route("/api/mirrors")
def api_mirrors():
    """JSON list of mirrors for the extension."""
    mirrors = list_mirrors()
    return jsonify([
        {
            "host": m.host,
            "page_count": m.page_count,
            "size_bytes": m.size_bytes,
            "has_zim": m.has_zim,
            "cloned_at": m.cloned_at,
        }
        for m in mirrors
    ])

@app.route("/api/mirrors/<host>", methods=["DELETE"])
def api_delete_mirror(host: str):
    ok = delete_mirror(host)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/mirrors/<host>/pack", methods=["POST"])
def api_pack(host: str):
    data = request.get_json() or {}
    fmt = data.get("format", "zim")
    job_id = start_pack(host, fmt)
    return jsonify({"job_id": job_id})


@sock.route("/ws/clone/<job_id>")
def ws_clone_progress(ws, job_id: str):
    """WebSocket for live clone progress."""
    last_idx = 0
    while True:
        job = get_job(job_id)
        if not job:
            ws.send(json.dumps({"error": "job not found"}))
            break

        # Send new output lines
        lines = job.get("lines", [])
        if last_idx < len(lines):
            for line in lines[last_idx:]:
                ws.send(json.dumps({"type": "output", "line": line}))
            last_idx = len(lines)

        # Send status update
        status = {
            "type": "status",
            "status": job["status"],
            "pages": job.get("pages", 0),
            "assets": job.get("assets", 0),
            "errors": job.get("errors", 0),
        }
        ws.send(json.dumps(status))

        if job["status"] in ("done", "error"):
            break

        time.sleep(0.5)  # Poll every 500ms


def _extract_title(path: Path) -> str:
    """Extract <title> from an HTML file, fast."""
    try:
        text = path.read_text(errors="ignore")
        import re
        m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
        return m.group(1).strip() if m else path.stem
    except Exception:
        return path.stem


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Kageboard — web UI for Kage")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=5000, help="Bind port")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()