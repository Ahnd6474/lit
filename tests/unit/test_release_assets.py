from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_docs_cover_distribution_name_and_publish_flow() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_doc = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")

    assert "## [1.0.0] - 2026-04-03" in changelog
    assert "lit-local-vcs" in changelog
    assert "lit-local-vcs" in release_doc
    assert "python -m build" in release_doc
    assert "python -m twine check dist/*" in release_doc
    assert "trusted publishing" in release_doc.lower()
    assert "license" in release_doc.lower()


def test_github_workflows_cover_ci_and_release_artifacts() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "python -m pytest" in ci
    assert 'python -m pip install -e ".[dev]"' in ci
    assert "python -m build" in ci
    assert "python -m twine check dist/*" in ci
    assert 'tags:' in release
    assert '"v*.*.*"' in release
    assert "softprops/action-gh-release@v2" in release
    assert "pypa/gh-action-pypi-publish@release/v1" in release
