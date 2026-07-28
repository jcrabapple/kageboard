from __future__ import annotations

import os
import base64
import secrets
from functools import wraps

from flask import request, jsonify, Response, session, redirect, url_for


# Default credentials — override via env or CLI
DEFAULT_USERNAME = "kageboard"
DEFAULT_PASSWORD = secrets.token_urlsafe(12)

_username: str | None = None
_password: str | None = None


def init_auth(username: str | None = None, password: str | None = None):
    """Configure auth credentials. Call once at startup."""
    global _username, _password
    _username = username or os.environ.get("KAGEBOARD_USERNAME", DEFAULT_USERNAME)
    _password = password or os.environ.get("KAGEBOARD_PASSWORD", DEFAULT_PASSWORD)


def get_credentials() -> tuple[str, str]:
    """Return current (username, password)."""
    return (_username or DEFAULT_USERNAME, _password or DEFAULT_PASSWORD)


def _check_basic() -> bool:
    """Check HTTP Basic Auth header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        user, _, pwd = decoded.partition(":")
        return user == _username and pwd == _password
    except Exception:
        return False


def _check_session() -> bool:
    """Check Flask session auth."""
    return session.get("kageboard_authenticated", False)


def is_authenticated() -> bool:
    """Check if the current request is authenticated (session or basic)."""
    return _check_session() or _check_basic()


def require_auth(f):
    """Decorator: require authentication for API endpoints.
    Returns 401 with WWW-Authenticate for API clients, redirects browser to login.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if is_authenticated():
            return f(*args, **kwargs)

        # API clients get a 401 challenge
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "unauthorized", "auth_required": True}), 401, {
                "WWW-Authenticate": 'Basic realm="Kageboard"'
            }

        # Browser clients get redirected to login
        return redirect(url_for("login_page", next=request.path))

    return wrapper


def require_auth_page(f):
    """Decorator: require auth for HTML pages. Redirects to login."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if is_authenticated():
            return f(*args, **kwargs)
        return redirect(url_for("login_page", next=request.path))
    return wrapper


def generate_password() -> str:
    """Generate a random password."""
    return secrets.token_urlsafe(12)