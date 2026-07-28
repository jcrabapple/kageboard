from __future__ import annotations

import tempfile
from pathlib import Path

from kageboard.kage import list_mirrors, get_mirror, delete_mirror, DEFAULT_OUT, Mirror


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