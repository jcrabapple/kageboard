from __future__ import annotations

import tempfile
from pathlib import Path

from kageboard.kage import (
    list_mirrors,
    get_mirror,
    delete_mirror,
    DEFAULT_OUT,
    Mirror,
    parse_clone_output,
    _resolve_host_path,
    _build_mirror,
)


def test_list_mirrors_empty():
    """Empty output dir returns empty list."""
    with tempfile.TemporaryDirectory() as td:
        mirrors = list_mirrors(Path(td))
        assert mirrors == []


def test_list_mirrors_with_dirs():
    """Directories in output dir become mirrors."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "example.com").mkdir()
        (out / "example.com" / "index.html").write_text("<html></html>")
        (out / "other.org").mkdir()
        (out / "other.org" / "page.html").write_text("<html></html>")

        mirrors = list_mirrors(out)
        assert len(mirrors) == 2
        hosts = {m.host for m in mirrors}
        assert hosts == {"example.com", "other.org"}


def test_list_mirrors_counts_pages():
    """Mirror page count matches HTML files."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        host = out / "testsite.com"
        host.mkdir()
        (host / "index.html").write_text("a")
        (host / "about.html").write_text("b")
        (host / "deep").mkdir()
        (host / "deep" / "nested.html").write_text("c")
        (host / "not-html.txt").write_text("d")

        mirrors = list_mirrors(out)
        assert len(mirrors) == 1
        assert mirrors[0].page_count == 3
        assert mirrors[0].host == "testsite.com"


def test_get_mirror_found():
    """get_mirror returns the right mirror."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "foo.com").mkdir()
        (out / "bar.com").mkdir()

        m = get_mirror("foo.com", out)
        assert m is not None
        assert m.host == "foo.com"


def test_get_mirror_not_found():
    """get_mirror returns None for unknown host."""
    with tempfile.TemporaryDirectory() as td:
        m = get_mirror("nope.com", Path(td))
        assert m is None


def test_get_mirror_path_traversal():
    """get_mirror rejects path traversal attempts."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "safe.com").mkdir()
        (out / "safe.com" / "index.html").write_text("<html></html>")

        # These should all return None — not escape the output dir
        assert get_mirror("..", out) is None
        assert get_mirror("../etc", out) is None
        assert get_mirror("../../tmp", out) is None
        # But a legitimate host should still work
        assert get_mirror("safe.com", out) is not None


def test_delete_mirror():
    """delete_mirror removes the directory."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "gone.com").mkdir()
        (out / "gone.com" / "x.html").write_text("x")

        assert delete_mirror("gone.com", out)
        assert not (out / "gone.com").exists()


def test_delete_mirror_missing():
    """delete_mirror returns False for nonexistent host."""
    with tempfile.TemporaryDirectory() as td:
        assert not delete_mirror("nope.com", Path(td))


def test_delete_mirror_path_traversal():
    """delete_mirror rejects path traversal — can't delete outside output dir."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        # Create a directory outside the output dir
        outside = Path(td) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        # Try to delete using path traversal
        assert not delete_mirror("..", out)
        assert not delete_mirror("../outside", out)
        # The outside directory should still exist
        assert outside.exists()
        assert (outside / "secret.txt").exists()


def test_resolve_host_path_traversal():
    """_resolve_host_path rejects traversal and allows legitimate hosts."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "legit.com").mkdir()

        assert _resolve_host_path("legit.com", out) is not None
        assert _resolve_host_path("..", out) is None
        assert _resolve_host_path("../etc", out) is None
        assert _resolve_host_path("/etc", out) is None


# ── parse_clone_output tests ──


def test_parse_clone_output_progress():
    """Parses progress lines like [1/10]."""
    result = parse_clone_output("  [3/15] GET /page → 200 (2.3s)")
    assert result == {"type": "page", "current": 3, "total": 15}


def test_parse_clone_output_done():
    """Parses done summary lines."""
    result = parse_clone_output("Done. 42 pages, 156 assets, 3 errors in 12.4s")
    assert result == {"type": "done", "pages": 42, "assets": 156, "errors": 3}


def test_parse_clone_output_done_no_errors():
    """Parses done summary with 0 errors."""
    result = parse_clone_output("Done. 10 pages, 20 assets, 0 errors in 5.0s")
    assert result == {"type": "done", "pages": 10, "assets": 20, "errors": 0}


def test_parse_clone_output_error():
    """Parses error lines (leading whitespace stripped by parser)."""
    result = parse_clone_output("  ✗ /page: timeout")
    assert result == {"type": "error", "message": "✗ /page: timeout"}


def test_parse_clone_output_error_timeout():
    """Parses timeout error lines."""
    result = parse_clone_output("Error: connection timeout")
    assert result == {"type": "error", "message": "Error: connection timeout"}


def test_parse_clone_output_empty():
    """Empty lines return None."""
    assert parse_clone_output("") is None
    assert parse_clone_output("   ") is None


def test_parse_clone_output_unknown():
    """Unrecognized lines return None."""
    assert parse_clone_output("Some random log message") is None


def test_parse_clone_output_singular_page():
    """Done line with singular 'page' should still parse."""
    result = parse_clone_output("Done. 1 page, 5 assets, 0 errors")
    assert result == {"type": "done", "pages": 1, "assets": 5, "errors": 0}


# ── _build_mirror tests ──


def test_build_mirror_with_state():
    """_build_mirror reads cloned_at from state.json."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "site.com"
        path.mkdir()
        (path / "index.html").write_text("<html></html>")
        (path / "_kage").mkdir()
        (path / "_kage" / "state.json").write_text('{"started_at": "2026-01-01T00:00:00Z"}')

        m = _build_mirror(path)
        assert m.host == "site.com"
        assert m.cloned_at == "2026-01-01T00:00:00Z"
        assert m.page_count == 1


def test_build_mirror_without_state():
    """_build_mirror works without state.json."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "site.com"
        path.mkdir()
        (path / "index.html").write_text("<html></html>")

        m = _build_mirror(path)
        assert m.host == "site.com"
        assert m.cloned_at == ""
        assert m.page_count == 1


def test_build_mirror_corrupt_state():
    """_build_mirror handles corrupt state.json gracefully."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "site.com"
        path.mkdir()
        (path / "index.html").write_text("<html></html>")
        (path / "_kage").mkdir()
        (path / "_kage" / "state.json").write_text("not valid json")

        m = _build_mirror(path)
        assert m.host == "site.com"
        assert m.cloned_at == ""
