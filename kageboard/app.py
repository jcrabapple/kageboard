from __future__ import annotations

import time
import json
from pathlib import Path

import mimetypes

from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for

from .kage import DEFAULT_OUT, list_mirrors, get_mirror, delete_mirror, kage_version, KageNotFoundError
from .manager import start_clone, get_job, get_job_raw, get_jobs, start_pack
from .auth import (
    init_auth,
    get_credentials,
    check_credentials,
    require_auth,
    is_authenticated,
    generate_password,
)

app = Flask(__name__)
app.secret_key = generate_password()

# We'll import sock after app creation to avoid circular imports if needed
# Flask-Sock doesn't use the app object for route registration in the same way,
# but we keep it simple since we already have the app.
from flask_sock import Sock
sock = Sock(app)


# ═══════════════════════════════════════
# Public routes (no auth required)
# ═══════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login_page():
    next_url = request.args.get("next", "/")

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if check_credentials(username, password):
            session["kageboard_authenticated"] = True
            session.permanent = True
            return redirect(next_url)
        return render_template("login.html", error="Invalid credentials", next=next_url)

    # Already logged in
    if is_authenticated():
        return redirect(next_url)

    return render_template("login.html", error=None, next=next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/auth/check")
def api_auth_check():
    """Check if the current request is authenticated."""
    if is_authenticated():
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False, "auth_required": True}), 401


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Login for programmatic clients — returns session cookie + Basic creds hint."""
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    # Also check Basic Auth header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
        except Exception:
            pass

    cfg_user, _ = get_credentials()
    if check_credentials(username, password):
        session["kageboard_authenticated"] = True
        session.permanent = True
        return jsonify({"authenticated": True, "username": cfg_user})

    return jsonify({"error": "invalid credentials"}), 401


@app.route("/")
def index():
    mirrors = list_mirrors()
    version = kage_version()
    authed = is_authenticated()
    return render_template("index.html", mirrors=mirrors, version=version, authed=authed)


@app.route("/mirrors")
def mirrors_list():
    mirrors = list_mirrors()
    return render_template("_mirrors.html", mirrors=mirrors)


@app.route("/mirrors/<host>")
def mirror_detail(host: str):
    mirror = get_mirror(host)
    if not mirror:
        return "Not found", 404

    pages = []
    if mirror.path.exists():
        for f in sorted(mirror.path.rglob("*.html")):
            rel = str(f.relative_to(mirror.path))
            pages.append({
                "path": rel,
                "title": _extract_title(f),
                "size": f.stat().st_size,
            })

    return render_template("detail.html", mirror=mirror, pages=pages, authed=is_authenticated())


@app.route("/mirrors/<host>/browse")
@app.route("/mirrors/<host>/browse/<path:subpath>")
def mirror_browse(host: str, subpath: str = ""):
    mirror = get_mirror(host)
    if not mirror:
        return "Not found", 404

    # Resolve and validate path stays within the mirror directory
    file_path = (mirror.path / subpath).resolve() if subpath else (mirror.path / "index.html").resolve()
    if not file_path.is_relative_to(mirror.path.resolve()):
        return "Forbidden", 403
    if not file_path.exists():
        return "Not found", 404

    mimetype, _ = mimetypes.guess_type(str(file_path))
    if mimetype is None:
        mimetype = "application/octet-stream"

    return Response(
        file_path.read_bytes(),
        mimetype=mimetype,
        headers={"X-Kageboard-Host": host},
    )


# ═══════════════════════════════════════
# API routes — read endpoints public, write endpoints require auth
# ═══════════════════════════════════════

@app.route("/api/clone", methods=["POST"])
@require_auth
def api_clone():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400

    flags = {}
    for f in ["max_pages", "max_depth", "scope_prefix", "scroll", "subdomains"]:
        if f in data and data[f]:
            flags[f] = data[f]

    try:
        job_id = start_clone(url, **flags)
    except KageNotFoundError as e:
        return jsonify({"error": str(e)}), 500
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
@require_auth
def api_delete_mirror(host: str):
    ok = delete_mirror(host)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404


@app.route("/api/mirrors/<host>/pack", methods=["POST"])
@require_auth
def api_pack(host: str):
    data = request.get_json() or {}
    fmt = data.get("format", "zim")
    try:
        job_id = start_pack(host, fmt)
    except KageNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"job_id": job_id})


@app.route("/api/mirrors/<host>/refresh", methods=["POST"])
@require_auth
def api_refresh(host: str):
    """Re-render an existing mirror in place (kage clone --refresh)."""
    mirror = get_mirror(host)
    if mirror is None:
        return jsonify({"error": "not found"}), 404
    try:
        job_id = start_clone(f"https://{host}", refresh=True)
    except KageNotFoundError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"job_id": job_id})


# ═══════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════

@sock.route("/ws/clone/<job_id>")
def ws_clone_progress(ws, job_id: str):
    last_idx = 0
    while True:
        job = get_job_raw(job_id)
        if not job:
            ws.send(json.dumps({"error": "job not found"}))
            break

        lines = job.get("lines", [])
        if last_idx < len(lines):
            for line in lines[last_idx:]:
                ws.send(json.dumps({"type": "output", "line": line}))
            last_idx = len(lines)

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

        time.sleep(0.5)


# ═══════════════════════════════════════
# Helpers
# ═══════════════════════════════════════

def _extract_title(path: Path) -> str:
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
    parser.add_argument("--username", default=None, help="Basic auth username")
    parser.add_argument("--password", default=None, help="Basic auth password (or set KAGEBOARD_PASSWORD)")
    args = parser.parse_args()

    init_auth(username=args.username, password=args.password)
    user, pwd = get_credentials()

    if not args.username and not args.password:
        print(f"🔐 Generated credentials — username: {user}  password: {pwd}")
        print("   Set KAGEBOARD_USERNAME / KAGEBOARD_PASSWORD env vars to override.")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()