from __future__ import annotations

from lit_gui.contracts import NavigationTarget, SessionSnapshot, VIEW_ORDER
from lit_gui.views.branches import BranchesView
from lit_gui.views.changes import ChangesView
from lit_gui.views.files import FilesView
from lit_gui.views.history import HistoryView
from lit_gui.views.home import HomeView


def build_shell_views(
    snapshot: SessionSnapshot,
    *,
    on_open_requested,
    on_initialize_requested,
    on_recent_requested,
    on_select_change,
    on_stage_paths_requested,
    on_commit_requested,
    on_select_commit,
    on_select_commit_path,
    on_select_file,
    on_select_branch,
    on_create_branch_requested,
    on_checkout_requested,
    on_restore_paths_requested,
    on_merge_requested,
    on_abort_merge_requested,
    on_rebase_requested,
    on_abort_rebase_requested,
    on_refresh_requested,
) -> dict[NavigationTarget, object]:
    views = {
        NavigationTarget.HOME: HomeView(
            snapshot.home,
            on_open_requested=on_open_requested,
            on_initialize_requested=on_initialize_requested,
            on_recent_requested=on_recent_requested,
        ),
        NavigationTarget.CHANGES: ChangesView(
            snapshot.changes,
            on_select_change=on_select_change,
            on_stage_paths_requested=on_stage_paths_requested,
            on_commit_requested=on_commit_requested,
            on_refresh_requested=on_refresh_requested,
        ),
        NavigationTarget.HISTORY: HistoryView(
            snapshot.history,
            on_select_commit=on_select_commit,
            on_select_commit_path=on_select_commit_path,
            on_refresh_requested=on_refresh_requested,
        ),
        NavigationTarget.BRANCHES: BranchesView(
            snapshot.branches,
            on_select_branch=on_select_branch,
            on_create_branch_requested=on_create_branch_requested,
            on_checkout_requested=on_checkout_requested,
            on_restore_paths_requested=on_restore_paths_requested,
            on_merge_requested=on_merge_requested,
            on_abort_merge_requested=on_abort_merge_requested,
            on_rebase_requested=on_rebase_requested,
            on_abort_rebase_requested=on_abort_rebase_requested,
            on_refresh_requested=on_refresh_requested,
        ),
        NavigationTarget.FILES: FilesView(
            snapshot.files,
            on_select_file=on_select_file,
            on_refresh_requested=on_refresh_requested,
        ),
    }
    return {target: views[target] for target in VIEW_ORDER}


__all__ = [
    "BranchesView",
    "ChangesView",
    "FilesView",
    "HistoryView",
    "HomeView",
    "build_shell_views",
]
