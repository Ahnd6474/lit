from __future__ import annotations

from pathlib import Path

from lit.repository import Repository
from lit_gui.contracts import NavigationTarget
from lit_gui.session import LitRepositorySession


def test_initialize_repository_returns_unborn_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    session = LitRepositorySession(root)

    snapshot = session.initialize_repository(root)

    assert snapshot.default_view == NavigationTarget.CHANGES
    assert snapshot.repository is not None
    assert snapshot.repository.is_lit_repository is True
    assert snapshot.repository.current_branch == "main"
    assert snapshot.repository.head_commit is None
    assert snapshot.repository.status_text == "No commits yet."
    assert snapshot.branches.branches[0].name == "main"
    assert snapshot.branches.branches[0].commit_id is None
    assert snapshot.files.tree == ()
    assert "Initialized empty lit repository" in snapshot.home.detail.guidance.body


def test_open_repository_normalizes_clean_history_branches_and_files(
    tmp_path: Path,
    commit_all,
) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    head_commit = commit_all(repo, "base commit")

    session = LitRepositorySession(tmp_path)
    snapshot = session.open_repository(tmp_path)

    assert snapshot.default_view == NavigationTarget.CHANGES
    assert snapshot.repository is not None
    assert snapshot.repository.status_text == "Working tree clean."
    assert snapshot.history.commits[0].commit_id == head_commit
    assert snapshot.history.commits[0].changed_paths == ("story.txt",)
    assert snapshot.branches.branches[0].name == "main"
    assert snapshot.branches.branches[0].is_current is True
    assert snapshot.files.selected_path == "story.txt"

    snapshot = session.select_file("story.txt")
    assert "base" in snapshot.files.detail.selection.body

    snapshot = session.select_commit(head_commit)
    assert f"Commit: {head_commit}" in snapshot.history.detail.metadata.body
    assert "Changed paths: story.txt" in snapshot.history.detail.metadata.body

    snapshot = session.create_branch("feature")
    assert [branch.name for branch in snapshot.branches.branches] == ["feature", "main"]
    assert snapshot.branches.selected_branch == "feature"

    snapshot = session.checkout("feature")
    assert snapshot.repository.current_branch == "feature"
    assert snapshot.branches.selected_branch == "feature"
    assert "switched to branch feature" in snapshot.branches.detail.guidance.body


def test_session_refreshes_dirty_state_and_preserves_selection_across_mutations(
    tmp_path: Path,
    commit_all,
) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)

    story.write_text("base\nupdated\n", encoding="utf-8")
    notes = tmp_path / "notes.txt"
    notes.write_text("draft\n", encoding="utf-8")

    snapshot = session.refresh()
    assert snapshot.repository is not None
    assert "unstaged" in snapshot.repository.status_text
    assert [(entry.path, entry.change_kind) for entry in snapshot.changes.unstaged] == [
        ("story.txt", "modified"),
        ("notes.txt", "untracked"),
    ]
    assert snapshot.changes.selected_path == "story.txt"

    snapshot = session.select_change("story.txt")
    assert "--- a/story.txt" in snapshot.changes.detail.selection.body

    snapshot = session.select_file("story.txt")
    assert "updated" in snapshot.files.detail.selection.body

    snapshot = session.stage_paths(("story.txt", "notes.txt"))
    assert [(entry.path, entry.change_kind) for entry in snapshot.changes.staged] == [
        ("notes.txt", "added"),
        ("story.txt", "modified"),
    ]
    assert snapshot.changes.selected_path == "story.txt"
    assert snapshot.files.selected_path == "story.txt"
    assert snapshot.changes.can_commit is True
    assert "staged 2 path(s)" in snapshot.changes.detail.guidance.body

    snapshot = session.commit("update working tree")
    assert snapshot.repository is not None
    assert snapshot.repository.status_text == "Working tree clean."
    assert snapshot.history.commits[0].message == "update working tree"
    assert snapshot.files.selected_path == "story.txt"
    assert "[main " in snapshot.changes.detail.guidance.body

    story.write_text("base\nupdated again\n", encoding="utf-8")
    session.refresh()
    snapshot = session.restore_paths(("story.txt",))
    assert story.read_text(encoding="utf-8") == "base\nupdated\n"
    assert snapshot.repository.status_text == "Working tree clean."
    assert "restored 1 path(s) from HEAD" in snapshot.changes.detail.guidance.body


def test_merge_conflict_snapshot_reports_operation_and_supports_abort(
    tmp_path: Path,
    prepare_merge_conflict,
) -> None:
    repo = Repository.create(tmp_path)
    prepare_merge_conflict(repo, tmp_path)

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)
    snapshot = session.merge("feature")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is not None
    assert snapshot.repository.operation.kind == "merge"
    assert snapshot.repository.operation.conflicts == ("story.txt",)
    assert "Merge in progress from feature" in snapshot.repository.status_text
    assert snapshot.changes.selected_path == "story.txt"
    assert "<<<<<<< current" in snapshot.changes.detail.selection.body
    assert "Merge stopped with conflicts." in snapshot.changes.detail.guidance.body

    snapshot = session.abort_merge()
    assert snapshot.repository is not None
    assert snapshot.repository.operation is None
    assert snapshot.repository.status_text == "Working tree clean."
    assert (tmp_path / "story.txt").read_text(encoding="utf-8") == "main change\n"
    assert "Merge state cleared." in snapshot.changes.detail.guidance.body


def test_merge_action_resumes_conflicted_merge_through_backend_boundary(
    tmp_path: Path,
    prepare_merge_conflict,
) -> None:
    repo = Repository.create(tmp_path)
    prepare_merge_conflict(repo, tmp_path)

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)
    snapshot = session.merge("feature")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is not None
    assert snapshot.repository.operation.kind == "merge"

    (tmp_path / "story.txt").write_text("resolved merge\n", encoding="utf-8")
    snapshot = session.merge("feature")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is None
    assert snapshot.repository.status_text == "Working tree clean."
    assert "Merge commit created" in snapshot.changes.detail.guidance.body


def test_rebase_conflict_snapshot_reports_operation_and_supports_abort(
    tmp_path: Path,
    prepare_rebase_conflict,
) -> None:
    repo = Repository.create(tmp_path)
    prepare_rebase_conflict(repo, tmp_path)

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)
    snapshot = session.rebase("main")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is not None
    assert snapshot.repository.operation.kind == "rebase"
    assert snapshot.repository.operation.conflicts == ("story.txt",)
    assert "Rebase in progress onto" in snapshot.repository.status_text
    assert snapshot.changes.selected_path == "story.txt"
    assert "<<<<<<< current" in snapshot.changes.detail.selection.body
    assert "Rebase stopped while replaying" in snapshot.changes.detail.guidance.body

    snapshot = session.abort_rebase()
    assert snapshot.repository is not None
    assert snapshot.repository.operation is None
    assert snapshot.repository.current_branch == "feature"
    assert snapshot.repository.status_text == "Working tree clean."
    assert (tmp_path / "story.txt").read_text(encoding="utf-8") == "feature change\n"
    assert "Rebase state cleared." in snapshot.changes.detail.guidance.body


def test_rebase_action_resumes_conflicted_rebase_through_backend_boundary(
    tmp_path: Path,
    prepare_rebase_conflict,
) -> None:
    repo = Repository.create(tmp_path)
    prepare_rebase_conflict(repo, tmp_path)

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)
    snapshot = session.rebase("main")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is not None
    assert snapshot.repository.operation.kind == "rebase"

    (tmp_path / "story.txt").write_text("resolved rebase\n", encoding="utf-8")
    snapshot = session.rebase("main")

    assert snapshot.repository is not None
    assert snapshot.repository.operation is None
    assert snapshot.repository.status_text == "Working tree clean."
    assert "Rebased onto" in snapshot.changes.detail.guidance.body


def test_session_release_surface_methods_refresh_checkpoint_verification_and_lineage_state(
    tmp_path: Path,
    commit_all,
    write_smoke_verification_command,
) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    head_commit = commit_all(repo, "base")
    write_smoke_verification_command(repo, command_identity="session-smoke")

    session = LitRepositorySession(tmp_path)
    session.open_repository(tmp_path)

    snapshot = session.create_checkpoint(name="safe-base")
    assert snapshot.repository is not None
    assert snapshot.repository.latest_safe_checkpoint_id is not None
    assert any(item.label == "Latest safe checkpoint" for item in snapshot.home.highlights)

    snapshot = session.verify_revision(definition_name="smoke")
    assert snapshot.repository is not None
    assert snapshot.repository.verification_status in {"passed", "cached_pass"}
    assert "verification" in snapshot.history.detail.metadata.body.lower()

    snapshot = session.create_lineage("feature-a", owned_paths=("src/lit",))
    assert any(lineage.lineage_id == "feature-a" for lineage in snapshot.branches.lineages)

    snapshot = session.preview_lineage_promotion("feature-a")
    assert "promotion preview" in snapshot.branches.detail.guidance.body.lower()

    snapshot = session.rollback_to_checkpoint(snapshot.repository.latest_safe_checkpoint_id)
    assert snapshot.history.selected_commit == head_commit
    assert "rolled back" in snapshot.history.detail.guidance.body.lower()
