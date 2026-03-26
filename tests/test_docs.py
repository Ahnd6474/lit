from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_current_bootstrap_scope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "local-only" in readme
    assert "offline-only" in readme
    assert "`lit init` works" in readme
    assert "reserved but not implemented yet." in readme
    assert "No `push`, `pull`, `fetch`, or `clone`." in readme
    assert "python -m pytest" in readme


def test_static_website_exists_and_matches_current_cli_status() -> None:
    index = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "website" / "styles.css").read_text(encoding="utf-8")

    assert "<title>lit | local git</title>" in index
    assert 'href="./styles.css"' in index
    assert "offline-only" in index
    assert "Current verified behavior" in index
    assert "<code>lit init</code> is operational." in index
    assert "Roadmap" not in styles
