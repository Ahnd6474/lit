from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from lit.cli import build_parser


def list_subcommands() -> set[str]:
    parser = build_parser()
    subparser_action = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )
    return set(subparser_action.choices)


def test_readme_describes_verified_scope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "local-only" in readme
    assert "offline-only" in readme
    assert "python -m lit init" in readme
    assert "not implemented yet" in readme
    assert "current limitations" in readme.lower()

    for command_name in list_subcommands():
        assert f"`lit {command_name}`" in readme


def test_static_website_exists_and_matches_current_cli_scope() -> None:
    website_root = ROOT / "website"
    index_html = (website_root / "index.html").read_text(encoding="utf-8")
    styles_css = (website_root / "styles.css").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="styles.css"' in index_html
    assert "local-only" in index_html
    assert "offline-only" in index_html
    assert "python -m lit init" in index_html
    assert "not implemented yet" in index_html
    assert "Git" in index_html
    assert "limitations" in index_html.lower()
    assert ":root" in styles_css

    for command_name in list_subcommands():
        assert f"lit {command_name}" in index_html
