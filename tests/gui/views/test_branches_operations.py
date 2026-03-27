from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from lit.refs import branch_ref
from lit.repository import Repository
from tests.test_lit_gui_bootstrap import _clear_lit_gui_modules, _install_fake_pyside6


def test_branches_view_handles_non_repository_state(monkeypatch, tmp_path: Path) -> None:
    app_module, contracts, persistence_module, session_module = _import_gui_modules(monkeypatch)

    plain_root = tmp_path / "plain"
    plain_root.mkdir()
    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(plain_root, recent_store=store)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)

    assert branches_view.branch_list_group.title() == "Branch List (0)"
    assert branches_view.manual_state_group.title() == "Repository State (0)"
    assert branches_view.create_button.isEnabled() is False
    assert branches_view.checkout_selected_button.isEnabled() is False
    assert "No .lit metadata detected yet." in branches_view.attention_label.text()
    assert "Initialize this folder" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)


def test_branches_view_creates_branch_restores_dirty_file_and_checks_out_selected_branch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_module, contracts, persistence_module, session_module = _import_gui_modules(monkeypatch)

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    story = repo_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    repo.stage(["story.txt"])
    repo.commit("seed")

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)

    branches_view.create_name_input.setText("feature")
    branches_view.create_button.clicked.emit()

    assert [branch.name for branch in window.snapshot.branches.branches] == ["feature", "main"]
    assert window.snapshot.branches.selected_branch == "feature"
    assert "feature ->" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    story.write_text("dirty change\n", encoding="utf-8")
    branches_view.refresh_button.clicked.emit()

    assert window.snapshot.branches.can_checkout is False
    assert branches_view.checkout_selected_button.isEnabled() is False
    assert "Checkout blocked" in window.sidebar._attention_label.text()
    assert "Commit them or use Restore" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    branches_view.restore_panel.path_input.setText("story.txt")
    branches_view.restore_panel.restore_button.clicked.emit()

    assert story.read_text(encoding="utf-8") == "base\n"
    assert window.snapshot.branches.can_checkout is True
    assert branches_view.checkout_selected_button.isEnabled() is True
    assert "restored 1 path(s) from HEAD" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    branches_view.checkout_selected_button.clicked.emit()

    assert window.snapshot.repository is not None
    assert window.snapshot.repository.current_branch == "feature"
    assert window.snapshot.branches.selected_branch == "feature"
    assert "switched to branch feature" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)


def test_branches_view_reports_target_specific_checkout_block_and_supports_detached_head(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_module, contracts, persistence_module, session_module = _import_gui_modules(monkeypatch)

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    docs = repo_root / "docs"
    docs.mkdir()
    story = docs / "guide.txt"
    story.write_text("base\n", encoding="utf-8")
    repo.stage(["docs"])
    base_commit = repo.commit("base")
    repo.create_branch("feature", start_point=base_commit)

    story.write_text("main\n", encoding="utf-8")
    main_only = docs / "main-only.txt"
    main_only.write_text("present\n", encoding="utf-8")
    repo.stage(["docs"])
    main_commit = repo.commit("main")
    repo.checkout("feature")

    main_only.write_text("scratch\n", encoding="utf-8")

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)

    assert window.snapshot.branches.can_checkout is True
    assert "untracked files can still block a specific target" in window.sidebar._attention_label.text().lower()

    branches_view.checkout_panel.revision_input.setText("main")
    branches_view.checkout_panel.primary_button.clicked.emit()

    assert window.snapshot.repository is not None
    assert window.snapshot.repository.current_branch == "feature"
    assert "overwrite untracked paths" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    main_only.unlink()
    branches_view.refresh_button.clicked.emit()
    branches_view.checkout_panel.revision_input.setText(main_commit)
    branches_view.checkout_panel.primary_button.clicked.emit()

    assert window.snapshot.repository is not None
    assert window.snapshot.repository.current_branch is None
    assert window.snapshot.repository.head_commit == main_commit
    assert window.snapshot.branches.selected_branch == "feature"
    assert "detached HEAD at" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)


def test_branches_view_surfaces_merge_conflicts_and_abort_controls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_module, contracts, persistence_module, session_module = _import_gui_modules(monkeypatch)

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    _prepare_merge_conflict(repo, repo_root)

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)

    branches_view.merge_panel.revision_input.setText("feature")
    branches_view.merge_panel.primary_button.clicked.emit()

    visible_conflicts = [button.text() for button in branches_view.conflict_buttons if button.isVisible()]
    assert visible_conflicts == ["story.txt"]
    assert branches_view.manual_state_group.title() == "Manual Resolution (1)"
    assert branches_view.restore_panel.path_input.text() == "story.txt"
    assert branches_view.merge_panel.secondary_button.isEnabled() is True
    assert "Manual resolution required." in window.sidebar._attention_label.text()
    assert window.detail_slots.slot_title(contracts.DetailSlotId.SELECTION) == "Manual resolution"
    assert "Conflicts: story.txt" in window.detail_slots.slot_body(contracts.DetailSlotId.METADATA)
    assert "Abort Merge" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    branches_view.merge_panel.secondary_button.clicked.emit()

    assert window.snapshot.repository is not None
    assert window.snapshot.repository.operation is None
    assert (repo_root / "story.txt").read_text(encoding="utf-8") == "main change\n"
    assert "Merge state cleared." in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)


def test_branches_view_surfaces_rebase_conflicts_and_abort_controls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_module, contracts, persistence_module, session_module = _import_gui_modules(monkeypatch)

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    _prepare_rebase_conflict(repo, repo_root)

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)
    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)

    branches_view.rebase_panel.revision_input.setText("main")
    branches_view.rebase_panel.primary_button.clicked.emit()

    visible_conflicts = [button.text() for button in branches_view.conflict_buttons if button.isVisible()]
    assert visible_conflicts == ["story.txt"]
    assert branches_view.manual_state_group.title() == "Manual Resolution (1)"
    assert branches_view.restore_panel.path_input.text() == "story.txt"
    assert branches_view.rebase_panel.secondary_button.isEnabled() is True
    assert "Manual resolution required." in window.sidebar._attention_label.text()
    assert window.detail_slots.slot_title(contracts.DetailSlotId.SELECTION) == "Manual resolution"
    assert "Conflicts: story.txt" in window.detail_slots.slot_body(contracts.DetailSlotId.METADATA)
    assert "Abort Rebase" in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)

    branches_view.rebase_panel.secondary_button.clicked.emit()

    assert window.snapshot.repository is not None
    assert window.snapshot.repository.operation is None
    assert window.snapshot.repository.current_branch == "feature"
    assert (repo_root / "story.txt").read_text(encoding="utf-8") == "feature change\n"
    assert "Rebase state cleared." in window.detail_slots.slot_body(contracts.DetailSlotId.GUIDANCE)


def _import_gui_modules(monkeypatch):
    _clear_lit_gui_modules()
    _install_fake_pyside6(monkeypatch)
    app_module = importlib.import_module("lit_gui.app")
    contracts = importlib.import_module("lit_gui.contracts")
    persistence_module = importlib.import_module("lit_gui.persistence")
    session_module = importlib.import_module("lit_gui.session")
    return app_module, contracts, persistence_module, session_module


def _prepare_merge_conflict(repository: Repository, root: Path) -> None:
    story = root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    repository.stage(["story.txt"])
    base_commit = repository.commit("base")
    repository.create_branch("feature", start_point=base_commit)

    story.write_text("main change\n", encoding="utf-8")
    repository.stage(["story.txt"])
    main_commit = repository.commit("main")

    repository.set_head_ref(branch_ref("feature"))
    repository.apply_commit(base_commit, baseline_commit=main_commit)
    story.write_text("feature change\n", encoding="utf-8")
    repository.stage(["story.txt"])
    feature_commit = repository.commit("feature")

    repository.set_head_ref(branch_ref("main"))
    repository.apply_commit(main_commit, baseline_commit=feature_commit)


def _prepare_rebase_conflict(repository: Repository, root: Path) -> None:
    story = root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    repository.stage(["story.txt"])
    base_commit = repository.commit("base")
    repository.create_branch("feature", start_point=base_commit)

    story.write_text("main change\n", encoding="utf-8")
    repository.stage(["story.txt"])
    main_commit = repository.commit("main")

    repository.set_head_ref(branch_ref("feature"))
    repository.apply_commit(base_commit, baseline_commit=main_commit)
    story.write_text("feature change\n", encoding="utf-8")
    repository.stage(["story.txt"])
    repository.commit("feature")
