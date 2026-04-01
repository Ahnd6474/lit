from __future__ import annotations

from pathlib import Path

from lit.repository import Repository


def test_home_view_handles_missing_and_non_repository_folders_and_persists_recents(
    gui_modules,
    tmp_path: Path,
) -> None:
    app_module = gui_modules.app
    contracts = gui_modules.contracts
    persistence_module = gui_modules.persistence
    session_module = gui_modules.session

    launch_root = tmp_path / "launch"
    launch_root.mkdir()
    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(launch_root, recent_store=store)
    window = app_module.build_window(session=session)
    home_view = window.view(contracts.NavigationTarget.HOME)

    assert window.active_view == contracts.NavigationTarget.HOME
    assert "No .lit metadata detected yet." in home_view.path_status_label.text()

    missing_root = tmp_path / "missing"
    home_view.path_input.setText(str(missing_root))
    home_view.open_button.clicked.emit()

    assert window.active_view == contracts.NavigationTarget.HOME
    assert window.snapshot.repository is not None
    assert window.snapshot.repository.status_text == "Folder does not exist yet."
    assert "Folder not found" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    project_root = tmp_path / "project"
    project_root.mkdir()
    home_view.path_input.setText(str(project_root))
    home_view.open_button.clicked.emit()

    assert window.active_view == contracts.NavigationTarget.HOME
    assert window.snapshot.repository is not None
    assert window.snapshot.repository.is_lit_repository is False
    assert window.snapshot.repository.status_text == "No .lit metadata detected yet."
    assert "Initialize this folder" in home_view.call_to_action_label.text()

    home_view.initialize_button.clicked.emit()

    assert window.active_view == contracts.NavigationTarget.CHANGES
    assert window.snapshot.repository is not None
    assert window.snapshot.repository.is_lit_repository is True
    assert (project_root / ".lit").is_dir()
    assert store.storage_path.is_file()
    assert store.load()[0] == project_root.resolve()
    assert not (project_root / "recent_repositories.json").exists()

    second_session = session_module.LitRepositorySession(
        tmp_path / "fresh-launch",
        recent_store=store,
    )
    recent_roots = tuple(entry.root for entry in second_session.snapshot().home.recent_repositories)
    assert project_root.resolve() in recent_roots

    second_window = app_module.build_window(session=second_session)
    second_home = second_window.view(contracts.NavigationTarget.HOME)
    _click_button(second_home.recent_buttons, str(project_root.resolve()))
    assert second_window.active_view == contracts.NavigationTarget.CHANGES
    assert second_window.snapshot.repository is not None
    assert second_window.snapshot.repository.root == project_root.resolve()


def test_files_view_browses_repository_tree_and_previews_selected_nodes(
    gui_modules,
    tmp_path: Path,
) -> None:
    app_module = gui_modules.app
    contracts = gui_modules.contracts
    persistence_module = gui_modules.persistence
    session_module = gui_modules.session

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    docs_root = repo_root / "docs"
    docs_root.mkdir()
    (docs_root / "readme.txt").write_text("lit keeps history local.\n", encoding="utf-8")
    (docs_root / "todo.md").write_text("- build gui\n", encoding="utf-8")
    (repo_root / "image.bin").write_bytes(b"\x00\x01\x02")
    repo.stage(["."])
    repo.commit("seed files")

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.FILES)
    files_view = window.view(contracts.NavigationTarget.FILES)

    visible_tree = [button.text() for button in files_view.node_buttons if button.isVisible()]
    assert any("[dir] docs" in label for label in visible_tree)
    assert any("[file] readme.txt" in label for label in visible_tree)
    assert all(".lit" not in label for label in visible_tree)

    _click_button(files_view.node_buttons, "[dir] docs")
    assert window.snapshot.files.selected_path == "docs"
    assert "readme.txt" in files_view.preview_body_label.text()
    assert "todo.md" in files_view.preview_body_label.text()

    _click_button(files_view.node_buttons, "[file] readme.txt")
    assert window.snapshot.files.selected_path == "docs/readme.txt"
    assert "lit keeps history local." in files_view.preview_body_label.text()
    assert "docs/readme.txt" in files_view.metadata_label.text()
    assert "lit keeps history local." in window.detail_slots.slot_body(contracts.DetailSlotId.SELECTION)

    _click_button(files_view.node_buttons, "[file] image.bin")
    assert window.snapshot.files.selected_path == "image.bin"
    assert files_view.preview_body_label.text() == "Binary preview unavailable."


def _click_button(buttons, text_fragment: str) -> None:
    for button in buttons:
        if button.isVisible() and text_fragment in button.text():
            button.clicked.emit()
            return
    raise AssertionError(f"button not found: {text_fragment}")
