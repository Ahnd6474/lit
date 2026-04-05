from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_exposes_installable_package_metadata() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["name"] == "jakal-lit"
    assert project["readme"] == "README.md"
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"]["lit"] == "lit.__main__:main"
    assert project["scripts"]["lit-gui"] == "lit.__main__:gui_main"
    assert project["optional-dependencies"]["gui"] == ["PySide6>=6.8"]
    assert project["optional-dependencies"]["dev"] == [
        "build>=1.2",
        "pytest>=8",
        "tox>=4.24",
        "twine>=5.1",
    ]
    assert "Programming Language :: Python :: 3.11" in project["classifiers"]
    assert "Programming Language :: Python :: 3.12" in project["classifiers"]
    assert "Programming Language :: Python :: 3.13" in project["classifiers"]
    assert project["urls"]["Homepage"] == "https://github.com/Ahnd6474/lit"
    assert project["urls"]["Changelog"] == "https://github.com/Ahnd6474/lit/blob/main/CHANGELOG.md"


def test_manifest_includes_distribution_docs_and_tests() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include README.md" in manifest
    assert "include CHANGELOG.md" in manifest
    assert "recursive-include docs *.md" in manifest
    assert "recursive-include tests *.py" in manifest
    assert "recursive-include website *.html *.css" in manifest
