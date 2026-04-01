from __future__ import annotations

from pathlib import Path

from lit.repository import Repository


def test_changes_view_groups_paths_stages_directory_and_commits_valid_workflow(
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
    (docs_root / "story.txt").write_text("base\n", encoding="utf-8")
    (repo_root / "notes.txt").write_text("tracked\n", encoding="utf-8")
    repo.stage(["."])
    repo.commit("seed")

    (docs_root / "story.txt").write_text("base\nupdated\n", encoding="utf-8")
    (docs_root / "draft.txt").write_text("draft\n", encoding="utf-8")
    (repo_root / "notes.txt").unlink()

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.CHANGES)
    changes_view = window.view(contracts.NavigationTarget.CHANGES)

    assert changes_view.staged_group.title() == "Staged (0)"
    assert changes_view.modified_group.title() == "Modified (1)"
    assert changes_view.deleted_group.title() == "Deleted (1)"
    assert changes_view.untracked_group.title() == "Untracked (1)"
    assert changes_view.commit_button.isEnabled() is False

    _click_button(changes_view.change_buttons, "docs/story.txt")
    assert window.snapshot.changes.selected_path == "docs/story.txt"
    assert "--- a/docs/story.txt" in changes_view.diff_panel.body_label.text()

    changes_view.stage_path_input.setText("docs")
    changes_view.stage_path_button.clicked.emit()

    assert [(entry.path, entry.change_kind) for entry in window.snapshot.changes.staged] == [
        ("docs/draft.txt", "added"),
        ("docs/story.txt", "modified"),
    ]
    assert changes_view.staged_group.title() == "Staged (2)"
    assert changes_view.deleted_group.title() == "Deleted (1)"
    assert "staged 2 path(s)" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    changes_view.commit_message_input.setText("   ")
    assert changes_view.commit_button.isEnabled() is False

    changes_view.commit_message_input.setText("checkpoint docs")
    assert changes_view.commit_button.isEnabled() is True
    changes_view.commit_button.clicked.emit()

    assert window.snapshot.history.commits[0].message == "checkpoint docs"
    assert window.snapshot.repository is not None
    assert window.snapshot.repository.status_text == "1 unstaged path(s)."
    assert changes_view.commit_message_input.text() == ""
    assert changes_view.commit_button.isEnabled() is False


def test_history_view_lists_commit_metadata_changed_files_and_file_diff(
    gui_modules,
    tmp_path: Path,
) -> None:
    app_module = gui_modules.app
    contracts = gui_modules.contracts
    persistence_module = gui_modules.persistence
    session_module = gui_modules.session

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    (repo_root / "story.txt").write_text("base\n", encoding="utf-8")
    (repo_root / "notes.txt").write_text("hello\n", encoding="utf-8")
    repo.stage(["."])
    first_commit = repo.commit("seed")

    (repo_root / "story.txt").write_text("base\nupdated\n", encoding="utf-8")
    (repo_root / "notes.txt").unlink()
    (repo_root / "extra.txt").write_text("extra\n", encoding="utf-8")
    repo.stage(["story.txt", "notes.txt", "extra.txt"])
    second_commit = repo.commit("update story")

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.HISTORY)
    history_view = window.view(contracts.NavigationTarget.HISTORY)

    assert history_view.timeline_group.title() == "Timeline (2)"
    assert window.snapshot.history.selected_commit == second_commit
    assert "3 path(s)" in history_view.commit_buttons[0].text()

    visible_changed_files = [button.text() for button in history_view.changed_file_buttons if button.isVisible()]
    assert visible_changed_files == ["extra.txt", "notes.txt", "story.txt"]

    _click_button(history_view.changed_file_buttons, "story.txt")

    assert window.snapshot.history.selected_path == "story.txt"
    assert history_view.changed_files_group.title() == "Changed Files (3)"
    assert "--- a/story.txt" in history_view.diff_panel.body_label.text()
    assert "+updated" in history_view.diff_panel.body_label.text()
    assert f"Commit: {second_commit}" in history_view.diff_panel.metadata_label.text()
    assert f"Parents: {first_commit[:12]}" in history_view.diff_panel.metadata_label.text()
    assert "Changed paths: extra.txt, notes.txt, story.txt" in history_view.diff_panel.metadata_label.text()
    assert "--- a/story.txt" in window.detail_slots.slot_body(contracts.DetailSlotId.SELECTION)


def _click_button(buttons, text_fragment: str) -> None:
    for button in buttons:
        if button.isVisible() and text_fragment in button.text():
            button.clicked.emit()
            return
    raise AssertionError(f"button not found: {text_fragment}")
