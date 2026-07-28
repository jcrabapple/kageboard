from __future__ import annotations

import json
import pytest
from pathlib import Path

from kageboard.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Kageboard" in r.data


def test_mirrors_partial(client):
    r = client.get("/mirrors")
    assert r.status_code == 200
    assert b"mirror-grid" in r.data


def test_api_jobs_empty(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert json.loads(r.data) == []


def test_api_clone_no_url(client):
    r = client.post("/api/clone", json={})
    assert r.status_code == 400
    assert b"URL required" in r.data


def test_static_css(client):
    r = client.get("/static/css/style.css")
    assert r.status_code == 200
    assert b"Kageboard" in r.data  # CSS has the name in a comment


def test_mirror_detail_404(client):
    r = client.get("/mirrors/doesnotexist.com")
    assert r.status_code == 404


def test_api_delete_404(client):
    r = client.delete("/api/mirrors/doesnotexist.com")
    assert r.status_code == 404


def test_api_job_status_404(client):
    r = client.get("/api/jobs/nonexistent")
    assert r.status_code == 404


def test_api_mirrors_empty(client):
    r = client.get("/api/mirrors")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data == []