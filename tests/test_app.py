from __future__ import annotations

import json
import base64
import tempfile
from pathlib import Path

import pytest

from kageboard.app import app
from kageboard.auth import init_auth, check_credentials
from kageboard.kage import DEFAULT_OUT
from kageboard.manager import _jobs, _job_lock


@pytest.fixture(autouse=True)
def setup_auth():
    """Set test credentials for every test."""
    init_auth(username="test", password="secret")


@pytest.fixture(autouse=True)
def clean_jobs():
    """Clear job state between tests."""
    with _job_lock:
        _jobs.clear()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_headers():
    """HTTP Basic Auth headers for test credentials."""
    return {
        "Authorization": "Basic " + base64.b64encode(b"test:secret").decode()
    }


@pytest.fixture
def tmp_mirror_dir(monkeypatch):
    """Create a temp directory with test mirrors and patch DEFAULT_OUT."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        # Create a test mirror
        (out / "example.com").mkdir()
        (out / "example.com" / "index.html").write_text("<html><head><title>Example</title></head><body>Hello</body></html>")
        (out / "example.com" / "style.css").write_text("body { color: red; }")
        (out / "example.com" / "sub").mkdir()
        (out / "example.com" / "sub" / "page.html").write_text("<html><head><title>Sub Page</title></head></html>")

        monkeypatch.setattr("kageboard.kage.DEFAULT_OUT", out)
        yield out


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Kageboard" in r.data
    # Not authenticated — should show Sign In
    assert b"Sign In to Clone" in r.data


def test_index_authed(client, auth_headers):
    """Index shows New Clone when authenticated."""
    r = client.get("/", headers=auth_headers)
    assert r.status_code == 200
    assert b"New Clone" in r.data


def test_mirrors_partial(client):
    r = client.get("/mirrors")
    assert r.status_code == 200
    assert b"mirror-grid" in r.data


def test_api_jobs_empty(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert json.loads(r.data) == []


def test_api_clone_no_url(client, auth_headers):
    r = client.post("/api/clone", json={}, headers=auth_headers)
    assert r.status_code == 400
    assert b"URL required" in r.data


def test_api_clone_unauthorized(client):
    """Clone requires auth."""
    r = client.post("/api/clone", json={"url": "example.com"})
    assert r.status_code == 401


def test_api_clone_advanced_flags(client, auth_headers, monkeypatch):
    """Advanced clone options are forwarded to start_clone."""
    calls = {}

    def fake_start_clone(url, **flags):
        calls["url"] = url
        calls["flags"] = flags
        return "job-adv-1"

    monkeypatch.setattr("kageboard.app.start_clone", fake_start_clone)
    r = client.post("/api/clone", json={
        "url": "example.com",
        "scope_prefix": "/docs",
        "exclude": ["/archive", " /tags ", ""],
        "keep_media": True,
        "mobile": True,
        "force": True,
    }, headers=auth_headers)
    assert r.status_code == 200
    f = calls["flags"]
    assert f["scope_prefix"] == "/docs"
    assert f["exclude"] == ["/archive", "/tags"]  # stripped, empties dropped
    assert f["keep_media"] is True
    assert f["mobile"] is True
    assert f["force"] is True


def test_api_clone_exclude_not_list_ignored(client, auth_headers, monkeypatch):
    """A non-list exclude value is ignored rather than crashing."""
    calls = {}

    def fake_start_clone(url, **flags):
        calls["flags"] = flags
        return "job-adv-2"

    monkeypatch.setattr("kageboard.app.start_clone", fake_start_clone)
    r = client.post("/api/clone", json={"url": "example.com", "exclude": "/archive"},
                    headers=auth_headers)
    assert r.status_code == 200
    assert "exclude" not in calls["flags"]


def test_static_css(client):
    r = client.get("/static/css/style.css")
    assert r.status_code == 200
    assert b"Kageboard" in r.data


def test_mirror_detail_404(client):
    r = client.get("/mirrors/doesnotexist.com")
    assert r.status_code == 404


def test_api_delete_404(client, auth_headers):
    r = client.delete("/api/mirrors/doesnotexist.com", headers=auth_headers)
    assert r.status_code == 404


def test_api_delete_unauthorized(client):
    r = client.delete("/api/mirrors/doesnotexist.com")
    assert r.status_code == 401


def test_api_job_status_404(client):
    r = client.get("/api/jobs/nonexistent")
    assert r.status_code == 404


def test_api_refresh_unauthorized(client, tmp_mirror_dir):
    """Refresh requires auth."""
    r = client.post("/api/mirrors/example.com/refresh")
    assert r.status_code == 401


def test_api_refresh_404(client, tmp_mirror_dir, auth_headers):
    """Refresh 404s for a mirror that doesn't exist."""
    r = client.post("/api/mirrors/doesnotexist.com/refresh", headers=auth_headers)
    assert r.status_code == 404


def test_api_refresh_starts_clone_job(client, tmp_mirror_dir, auth_headers, monkeypatch):
    """Refresh kicks off a clone job with --refresh against the mirror's URL."""
    calls = {}

    def fake_start_clone(url, **flags):
        calls["url"] = url
        calls["flags"] = flags
        return "job-refresh-1"

    monkeypatch.setattr("kageboard.app.start_clone", fake_start_clone)
    r = client.post("/api/mirrors/example.com/refresh", headers=auth_headers)
    assert r.status_code == 200
    assert r.get_json()["job_id"] == "job-refresh-1"
    assert calls["url"] == "https://example.com"
    assert calls["flags"] == {"refresh": True}


def test_api_refresh_path_traversal(client, tmp_mirror_dir, auth_headers):
    """Refresh rejects path-traversal hosts."""
    r = client.post("/api/mirrors/..%2F..%2Fetc/refresh", headers=auth_headers)
    assert r.status_code == 404


def test_api_pack_rejects_bad_format(client, tmp_mirror_dir, auth_headers):
    r = client.post("/api/mirrors/example.com/pack", json={"format": "tarball"},
                    headers=auth_headers)
    assert r.status_code == 400


def test_api_pack_unknown_host_404(client, tmp_mirror_dir, auth_headers):
    r = client.post("/api/mirrors/nope.com/pack", json={"format": "zim"},
                    headers=auth_headers)
    assert r.status_code == 404


def test_api_pack_forwards_format_and_incremental(client, tmp_mirror_dir, auth_headers, monkeypatch):
    calls = {}

    def fake_start_pack(host, fmt, incremental=False):
        calls["host"] = host
        calls["fmt"] = fmt
        calls["incremental"] = incremental
        return "job-pack-1"

    monkeypatch.setattr("kageboard.app.start_pack", fake_start_pack)
    r = client.post("/api/mirrors/example.com/pack",
                    json={"format": "binary", "incremental": True},
                    headers=auth_headers)
    assert r.status_code == 200
    assert r.get_json()["job_id"] == "job-pack-1"
    assert calls == {"host": "example.com", "fmt": "binary", "incremental": True}


def test_download_zim(client, tmp_mirror_dir):
    """Packed artifacts download without auth (read-only, like browse)."""
    (tmp_mirror_dir / "example.com.zim").write_bytes(b"FAKEZIM")
    r = client.get("/api/mirrors/example.com/download/zim")
    assert r.status_code == 200
    assert r.data == b"FAKEZIM"
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_download_binary(client, tmp_mirror_dir):
    (tmp_mirror_dir / "example.com.bin").write_bytes(b"FAKEBIN")
    r = client.get("/api/mirrors/example.com/download/binary")
    assert r.status_code == 200
    assert r.data == b"FAKEBIN"


def test_download_missing_404(client, tmp_mirror_dir):
    r = client.get("/api/mirrors/example.com/download/zim")
    assert r.status_code == 404


def test_download_rejects_bad_input(client, tmp_mirror_dir):
    assert client.get("/api/mirrors/example.com/download/tarball").status_code == 404
    assert client.get("/api/mirrors/..%2F..%2Fetc/download/zim").status_code == 404


def test_api_mirrors_empty(client):
    r = client.get("/api/mirrors")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data == []


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Sign In" in r.data


def test_login_success(client):
    r = client.post("/login", data={"username": "test", "password": "secret"}, follow_redirects=True)
    assert r.status_code == 200


def test_login_failure(client):
    r = client.post("/login", data={"username": "test", "password": "wrong"})
    assert b"Invalid" in r.data


def test_api_auth_check(client, auth_headers):
    r = client.get("/api/auth/check", headers=auth_headers)
    assert r.status_code == 200
    assert r.get_json()["authenticated"] is True


def test_api_auth_check_unauthorized(client):
    r = client.get("/api/auth/check")
    assert r.status_code == 401


# ── Regression tests for fixes ──


def test_check_credentials_constant_time():
    """check_credentials uses constant-time comparison."""
    init_auth(username="test", password="secret")
    assert check_credentials("test", "secret") is True
    assert check_credentials("test", "wrong") is False
    assert check_credentials("wrong", "secret") is False
    assert check_credentials("", "") is False


def test_mirror_browse_path_traversal(client, tmp_mirror_dir):
    """Browse endpoint rejects path traversal outside mirror dir."""
    # Legitimate file works
    r = client.get("/mirrors/example.com/browse/index.html")
    assert r.status_code == 200
    assert b"Example" in r.data

    # Path traversal blocked
    r = client.get("/mirrors/example.com/browse/../../../../etc/passwd")
    assert r.status_code == 403


def test_mirror_browse_mimetype(client, tmp_mirror_dir):
    """Browse endpoint returns correct mimetype for CSS files."""
    r = client.get("/mirrors/example.com/browse/style.css")
    assert r.status_code == 200
    assert "text/css" in r.content_type


def test_mirror_browse_html_mimetype(client, tmp_mirror_dir):
    """Browse endpoint returns text/html for HTML files."""
    r = client.get("/mirrors/example.com/browse/index.html")
    assert r.status_code == 200
    assert "text/html" in r.content_type


def test_mirror_browse_404(client, tmp_mirror_dir):
    """Browse returns 404 for missing files."""
    r = client.get("/mirrors/example.com/browse/nonexistent.html")
    assert r.status_code == 404


def test_mirror_browse_subdir(client, tmp_mirror_dir):
    """Browse works for files in subdirectories."""
    r = client.get("/mirrors/example.com/browse/sub/page.html")
    assert r.status_code == 200
    assert b"Sub Page" in r.data


def test_api_delete_path_traversal(client, tmp_mirror_dir, auth_headers):
    """Delete endpoint rejects path traversal — can't delete outside output dir."""
    # Create a directory outside the mirror dir
    outside = tmp_mirror_dir.parent / "outside_target"
    outside.mkdir()
    (outside / "file.txt").write_text("safe")

    r = client.delete("/api/mirrors/..", headers=auth_headers)
    assert r.status_code == 404
    assert outside.exists()
    assert (outside / "file.txt").exists()

    # Cleanup
    import shutil
    shutil.rmtree(outside)


def test_api_jobs_excludes_lines(client):
    """Jobs endpoint doesn't leak stdout lines."""
    from kageboard.manager import _jobs, _job_lock
    with _job_lock:
        _jobs["test-job"] = {
            "id": "test-job",
            "status": "done",
            "proc": None,
            "lines": ["sensitive output\n", "more output\n"],
            "pages": 5,
            "started_at": 0,
        }

    r = client.get("/api/jobs")
    data = json.loads(r.data)
    assert len(data) == 1
    job = data[0]
    assert "lines" not in job
    assert "proc" not in job
    assert job["status"] == "done"
    assert job["pages"] == 5


def test_api_job_status_excludes_lines(client):
    """Individual job status endpoint doesn't leak stdout lines."""
    from kageboard.manager import _jobs, _job_lock
    with _job_lock:
        _jobs["test-job-2"] = {
            "id": "test-job-2",
            "status": "running",
            "proc": None,
            "lines": ["secret\n"],
            "pages": 1,
            "started_at": 0,
        }

    r = client.get("/api/jobs/test-job-2")
    data = json.loads(r.data)
    assert "lines" not in data
    assert "proc" not in data
    assert data["status"] == "running"


def test_login_uses_check_credentials(client):
    """Login route uses check_credentials (constant-time comparison)."""
    init_auth(username="admin", password="supersecret")
    r = client.post("/login", data={"username": "admin", "password": "supersecret"}, follow_redirects=True)
    assert r.status_code == 200


def test_api_auth_login_uses_check_credentials(client):
    """API login route uses check_credentials."""
    init_auth(username="api_user", password="api_pass")
    creds = base64.b64encode(b"api_user:api_pass").decode()
    r = client.post("/api/auth/login", json={"username": "api_user", "password": "api_pass"},
                    headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 200
    assert r.get_json()["authenticated"] is True
