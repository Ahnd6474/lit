from __future__ import annotations

import importlib

import pytest


def test_module_entrypoint_supports_help() -> None:
    entrypoint = importlib.import_module("lit.__main__")

    with pytest.raises(SystemExit) as excinfo:
        entrypoint.main(["--help"])

    assert excinfo.value.code == 0


def test_gui_entrypoint_prompts_for_gui_extra(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    entrypoint = importlib.import_module("lit.__main__")

    def _missing_pyside6(_: str):
        raise ModuleNotFoundError("PySide6")

    monkeypatch.setattr(importlib, "import_module", _missing_pyside6)

    assert entrypoint.gui_main([]) == 1
    assert 'pip install "lit-local-vcs[gui]"' in capsys.readouterr().err
