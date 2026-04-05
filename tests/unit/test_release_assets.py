from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_docs_cover_distribution_name_and_publish_flow() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_doc = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")

    assert "## [1.0.0] - 2026-04-03" in changelog
    assert "distribution name `jakal-lit`" in changelog
    assert "ships to PyPI as `jakal-lit`." in release_doc
    assert "Python 3.11, 3.12, and 3.13" in release_doc
    assert "python -m tox" in release_doc
    assert "python -m tox -e pkg" in release_doc
    assert "TestPyPI" in release_doc
    assert "trusted publishing" in release_doc.lower()
    assert "license" in release_doc.lower()


def test_github_workflows_cover_ci_and_release_artifacts() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    testpypi = (ROOT / ".github" / "workflows" / "testpypi.yml").read_text(encoding="utf-8")
    tox = (ROOT / "tox.ini").read_text(encoding="utf-8")

    assert '"3.11"' in ci
    assert '"3.12"' in ci
    assert '"3.13"' in ci
    assert 'python -m pip install "tox>=4.24"' in ci
    assert "python -m tox -e py" in ci
    assert "python -m tox -e pkg" in ci
    assert 'tags:' in release
    assert '"v*.*.*"' in release
    assert '"3.11"' in release
    assert 'python -m pip install "tox>=4.24"' in release
    assert "python -m tox -e pkg" in release
    assert "softprops/action-gh-release@v2" in release
    assert "pypa/gh-action-pypi-publish@release/v1" in release
    assert "workflow_dispatch:" in testpypi
    assert "https://test.pypi.org/legacy/" in testpypi
    assert "name: testpypi" in testpypi
    assert "envlist = py311, py312, py313, pkg" in tox
    assert "skip_missing_interpreters = true" in tox
