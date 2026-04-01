from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_describes_verified_bootstrap_state() -> None:
    readme = ROOT / "README.md"

    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")

    assert "local-only" in content
    assert "offline-only" in content
    assert "pip install -e ." in content
    assert "python -m lit init" in content
    assert "`lit init` is the only implemented end-to-end command today." in content
    assert ".lit/" in content
    for command in (
        "add",
        "commit",
        "log",
        "status",
        "diff",
        "restore",
        "checkout",
        "branch",
        "merge",
        "rebase",
    ):
        assert f"`lit {command}`" in content
    assert "Git similarities and differences" in content
    assert "Limitations and non-goals" in content


def test_static_docs_site_is_self_contained_and_honest() -> None:
    website_dir = ROOT / "website"
    index_html = website_dir / "index.html"
    styles_css = website_dir / "styles.css"

    assert website_dir.is_dir()
    assert index_html.is_file()
    assert styles_css.is_file()

    content = index_html.read_text(encoding="utf-8")

    assert 'href="styles.css"' in content
    assert "Open this file directly in your browser" in content
    assert "local-only" in content
    assert "offline-only" in content
    assert "Only `lit init` works today." in content
    assert "Planned command workflow" in content
    assert "Git: same ideas, smaller scope" in content
    assert "Limitations and non-goals" in content
