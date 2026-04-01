from __future__ import annotations

import importlib
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_lit_gui_entrypoint_and_optional_pyside6_extra() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["scripts"]["lit"] == "lit.cli:main"
    assert project["scripts"]["lit-gui"] == "lit_gui.app:main"
    assert project["optional-dependencies"]["gui"] == ["PySide6>=6.8"]
    assert project["dependencies"] == []


def test_gui_contracts_are_immutable_and_route_all_views() -> None:
    contracts = importlib.import_module("lit_gui.contracts")

    repository = contracts.RepositoryDescriptor(
        name="workspace",
        root=Path("C:/workspace"),
        is_lit_repository=False,
    )
    detail = contracts.DetailPaneState.placeholder(
        selection_title="Selection",
        selection_body="Placeholder selection",
        metadata_title="Metadata",
        metadata_body="Placeholder metadata",
        guidance_title="Guidance",
        guidance_body="Placeholder guidance",
    )
    home = contracts.HomeViewState(
        route=contracts.NavigationTarget.HOME,
        title="Home",
        subtitle="home",
        detail=detail,
        context=repository,
    )
    changes = contracts.ChangesViewState(
        route=contracts.NavigationTarget.CHANGES,
        title="Changes",
        subtitle="changes",
        detail=detail,
        context=repository,
    )
    history = contracts.HistoryViewState(
        route=contracts.NavigationTarget.HISTORY,
        title="History",
        subtitle="history",
        detail=detail,
        context=repository,
    )
    branches = contracts.BranchesViewState(
        route=contracts.NavigationTarget.BRANCHES,
        title="Branches",
        subtitle="branches",
        detail=detail,
        context=repository,
    )
    files = contracts.FilesViewState(
        route=contracts.NavigationTarget.FILES,
        title="Files",
        subtitle="files",
        detail=detail,
        context=repository,
    )

    snapshot = contracts.SessionSnapshot(
        repository=repository,
        home=home,
        changes=changes,
        history=history,
        branches=branches,
        files=files,
    )

    assert snapshot.default_view == contracts.NavigationTarget.HOME
    assert snapshot.for_view(contracts.NavigationTarget.HISTORY) is history
    assert detail.slots() == (detail.selection, detail.metadata, detail.guidance)

    with pytest.raises(FrozenInstanceError):
        repository.name = "changed"

    with pytest.raises(TypeError):
        contracts.RepositorySession()


def test_shell_builds_three_pane_placeholder_navigation(
    gui_modules,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    window = gui_modules.app.build_window()

    assert window.windowTitle() == "lit"
    assert window.splitter.count() == 3
    assert window.available_views == gui_modules.contracts.VIEW_ORDER
    assert window.active_view == gui_modules.contracts.NavigationTarget.HOME
    assert window.center_stack.currentWidget().route == gui_modules.contracts.NavigationTarget.HOME

    window.show_view(gui_modules.contracts.NavigationTarget.BRANCHES)

    assert window.active_view == gui_modules.contracts.NavigationTarget.BRANCHES
    assert window.center_stack.currentWidget().route == gui_modules.contracts.NavigationTarget.BRANCHES
    assert window.sidebar.is_active(gui_modules.contracts.NavigationTarget.BRANCHES) is True


def test_shell_updates_shared_detail_slots_when_view_changes(
    gui_modules,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    window = gui_modules.app.build_window()

    assert window.detail_slots.slot_ids == (
        gui_modules.contracts.DetailSlotId.SELECTION,
        gui_modules.contracts.DetailSlotId.METADATA,
        gui_modules.contracts.DetailSlotId.GUIDANCE,
    )
    assert window.detail_slots.slot_title(gui_modules.contracts.DetailSlotId.SELECTION) == (
        "Selected repository"
    )
    assert (
        "initialize this folder"
        in window.detail_slots.slot_body(gui_modules.contracts.DetailSlotId.GUIDANCE).lower()
    )

    window.show_view(gui_modules.contracts.NavigationTarget.HISTORY)

    assert window.detail_slots.slot_title(gui_modules.contracts.DetailSlotId.SELECTION) == (
        "Selected commit"
    )
    assert (
        "commit history appears here"
        in window.detail_slots.slot_body(gui_modules.contracts.DetailSlotId.METADATA).lower()
    )
