from __future__ import annotations

import json
import base64
import pytest
from pathlib import Path

from kageboard.app import app
from kageboard.auth import init_auth


@pytest.fixture(autouse=True)
def setup_auth():
    """Set test credentials for every test."""
    init_auth(username="test", password="secret")


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