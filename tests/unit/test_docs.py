from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_current_local_scope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "local-only" in readme
    assert "offline-first" in readme
    assert "What lit does today" in readme
    assert "checkpoint" in readme
    assert "verify" in readme
    assert "lineage" in readme
    assert "artifact" in readme
    assert "lit-gui" in readme
    assert "lit-local-vcs" in readme
    assert "export" in readme
    assert "python -m pytest" in readme
    assert "Python `3.11+`" in readme
    assert "python -m tox" in readme
    assert "docs/releasing.md" in readme


def test_static_website_exists_and_matches_current_cli_status() -> None:
    index = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "website" / "styles.css").read_text(encoding="utf-8")

    assert "<title>lit | local git</title>" in index
    assert 'href="./styles.css"' in index
    assert "offline-only" in index
    assert "Current verified behavior" in index
    assert "<code>lit init</code> is operational." in index
    assert "Roadmap" not in styles
