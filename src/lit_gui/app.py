from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from PySide6 import QtWidgets

from lit_gui.contracts import (
    BranchSummary,
    BranchesViewState,
    ChangesViewState,
    CommitSummary,
    DetailPaneState,
    FileNode,
    FilesViewState,
    HistoryViewState,
    HomeViewState,
    NavigationTarget,
    RecentRepository,
    RepositoryDescriptor,
    RepositorySession,
    SessionSnapshot,
    SummaryItem,
)
from lit_gui.shell import LitShellWindow
from lit_gui.session import LitRepositorySession


class PreviewRepositorySession(RepositorySession):
    """Static session data used until the real backend adapter lands."""

    def __init__(self, root: Path | None = None) -> None:
        self._snapshot = self._build_snapshot(root or Path.cwd())

    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def open_repository(self, root: Path) -> SessionSnapshot:
        self._snapshot = self._build_snapshot(root)
        return self._snapshot

    def initialize_repository(self, root: Path) -> SessionSnapshot:
        self._snapshot = self._build_snapshot(root, initialized=True)
        return self._snapshot

    def refresh(self) -> SessionSnapshot:
        root = self._snapshot.repository.root if self._snapshot.repository is not None else Path.cwd()
        self._snapshot = self._build_snapshot(root)
        return self._snapshot

    def stage_paths(self, paths: tuple[str, ...]) -> SessionSnapshot:
        return self._snapshot

    def restore_paths(self, paths: tuple[str, ...], *, source: str | None = None) -> SessionSnapshot:
        return self._snapshot

    def commit(self, message: str) -> SessionSnapshot:
        return self._snapshot

    def select_change(self, path: str) -> SessionSnapshot:
        return self._snapshot

    def select_commit(self, commit_id: str) -> SessionSnapshot:
        return self._snapshot

    def create_branch(self, name: str, *, start_point: str | None = "HEAD") -> SessionSnapshot:
        return self._snapshot

    def select_branch(self, branch_name: str) -> SessionSnapshot:
        return self._snapshot

    def checkout(self, revision: str) -> SessionSnapshot:
        return self._snapshot

    def merge(self, revision: str) -> SessionSnapshot:
        return self._snapshot

    def abort_merge(self) -> SessionSnapshot:
        return self._snapshot

    def rebase(self, revision: str) -> SessionSnapshot:
        return self._snapshot

    def abort_rebase(self) -> SessionSnapshot:
        return self._snapshot

    def select_file(self, path: str) -> SessionSnapshot:
        return self._snapshot

    def _build_snapshot(self, root: Path, *, initialized: bool = False) -> SessionSnapshot:
        resolved_root = root.resolve()
        is_lit_repository = initialized or (resolved_root / ".lit").is_dir()
        branch_name = "main" if is_lit_repository else None
        status_text = (
            "Preview session detected a .lit workspace."
            if is_lit_repository
            else "No .lit metadata detected yet. Open a folder or initialize one from Home."
        )
        repository = RepositoryDescriptor(
            name=resolved_root.name or str(resolved_root),
            root=resolved_root,
            current_branch=branch_name,
            head_commit=None,
            status_text=status_text,
            is_lit_repository=is_lit_repository,
        )

        home = HomeViewState(
            route=NavigationTarget.HOME,
            title="Repository Home",
            subtitle="Open an existing folder or initialize local-only history in place.",
            context=repository,
            highlights=(
                SummaryItem(label="Current folder", value=str(resolved_root)),
                SummaryItem(
                    label="Repository status",
                    value="Detected .lit metadata" if is_lit_repository else "Not initialized yet",
                ),
                SummaryItem(
                    label="Shell contract",
                    value="Sidebar, center view, and right detail panel are now frozen.",
                ),
            ),
            recent_repositories=(
                RecentRepository(
                    name=repository.name,
                    root=resolved_root,
                    summary="Current working directory placeholder.",
                    is_lit_repository=is_lit_repository,
                ),
            ),
            call_to_action="Later steps wire real Open and Initialize actions through RepositorySession.",
            detail=DetailPaneState.placeholder(
                selection_title="Selected repository",
                selection_body=repository.name,
                metadata_title="Workspace metadata",
                metadata_body=status_text,
                guidance_title="Next action",
                guidance_body="Use Home to open a folder or initialize a .lit workspace.",
            ),
        )

        changes = ChangesViewState(
            route=NavigationTarget.CHANGES,
            title="Changes",
            subtitle="Working tree, staging, and commit flow will land here without changing the shell.",
            context=repository,
            highlights=(
                SummaryItem(label="Staged entries", value="0"),
                SummaryItem(label="Unstaged entries", value="0"),
                SummaryItem(label="Commit readiness", value="Disabled in the preview session"),
            ),
            staged=(),
            unstaged=(),
            selected_path=None,
            can_commit=False,
            commit_message_hint="Commit message input lands in this view in a later step.",
            detail=DetailPaneState.placeholder(
                selection_title="Selected change",
                selection_body="No file selected yet.",
                metadata_title="Changes metadata",
                metadata_body="The immutable DTO contract already reserves staged and unstaged collections.",
                guidance_title="Next action",
                guidance_body="Wire status, add, restore, and commit mutations through RepositorySession.",
            ),
        )

        history = HistoryViewState(
            route=NavigationTarget.HISTORY,
            title="History",
            subtitle="Commit timeline placeholders keep the center column and detail panel stable.",
            context=repository,
            highlights=(
                SummaryItem(label="Visible commits", value="0"),
                SummaryItem(label="Selected commit", value="None"),
            ),
            commits=(
                CommitSummary(
                    commit_id="preview",
                    message="History DTOs are ready for real log data.",
                    author="lit_gui",
                    committed_at="pending backend adapter",
                ),
            ),
            selected_commit=None,
            detail=DetailPaneState.placeholder(
                selection_title="Selected commit",
                selection_body="Pick a commit once RepositorySession is backed by the log view.",
                metadata_title="History metadata",
                metadata_body="Commit summaries already have room for ids, authors, timestamps, and changed paths.",
                guidance_title="Next action",
                guidance_body="Later work can bind commit selection without changing the right panel layout.",
            ),
        )

        branches = BranchesViewState(
            route=NavigationTarget.BRANCHES,
            title="Branches",
            subtitle="Branch switching and creation stay in the center view while details live on the right.",
            context=repository,
            highlights=(
                SummaryItem(label="Current branch", value=branch_name or "No repository loaded"),
                SummaryItem(label="Branch count", value="1" if is_lit_repository else "0"),
            ),
            branches=(
                BranchSummary(
                    name="main",
                    commit_id=None,
                    is_current=is_lit_repository,
                    note="Preview branch row for the frozen shell.",
                ),
            )
            if is_lit_repository
            else (),
            selected_branch=branch_name,
            can_checkout=is_lit_repository,
            detail=DetailPaneState.placeholder(
                selection_title="Selected branch",
                selection_body=branch_name or "No branch selected yet.",
                metadata_title="Branch metadata",
                metadata_body="The shell already reserves stable detail slots for branch facts and safety guidance.",
                guidance_title="Next action",
                guidance_body="Later steps can connect checkout and branch creation through RepositorySession.",
            ),
        )

        files = FilesViewState(
            route=NavigationTarget.FILES,
            title="Files",
            subtitle="Repository browsing and previews will attach here without moving the surrounding panes.",
            context=repository,
            highlights=(
                SummaryItem(label="Root", value=str(resolved_root)),
                SummaryItem(label="Selected file", value="None"),
            ),
            tree=(
                FileNode(path="src", display_name="src", node_kind="directory"),
                FileNode(path="src/lit", display_name="lit", node_kind="directory", depth=1),
                FileNode(path="src/lit_gui", display_name="lit_gui", node_kind="directory", depth=1),
            ),
            selected_path=None,
            detail=DetailPaneState.placeholder(
                selection_title="Selected file",
                selection_body="Choose a tree node once the file browser is wired.",
                metadata_title="File metadata",
                metadata_body="DTOs already reserve a tree model for repository browsing.",
                guidance_title="Next action",
                guidance_body="Later work can bind file previews and diff rendering into the existing slot layout.",
            ),
        )

        return SessionSnapshot(
            repository=repository,
            home=home,
            changes=changes,
            history=history,
            branches=branches,
            files=files,
        )


def create_application(argv: Sequence[str] | None = None) -> QtWidgets.QApplication:
    application = QtWidgets.QApplication.instance()
    if application is None:
        arguments = list(argv) if argv is not None else list(sys.argv)
        application = QtWidgets.QApplication(arguments)
        application.setApplicationName("lit")
    return application


def build_window(session: RepositorySession | None = None) -> LitShellWindow:
    create_application([])
    return LitShellWindow(session=session or LitRepositorySession())


def main(argv: Sequence[str] | None = None) -> int:
    application = create_application(argv)
    window = build_window()
    window.show()
    return application.exec()
