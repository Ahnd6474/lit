from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Literal

from lit.refs import branch_name_from_ref
from lit.repository import BranchRecord, Repository, StatusReport, TrackedFile
from lit.state import MergeState, OperationState, RebaseState
from lit.working_tree import normalize_repo_path
from lit_gui.contracts import (
    BranchSummary,
    BranchesViewState,
    ChangedPath,
    ChangesViewState,
    CommitSummary,
    DetailPaneState,
    FileNode,
    FilesViewState,
    HistoryViewState,
    HomeViewState,
    NavigationTarget,
    OperationSummary,
    RecentRepository,
    RepositoryDescriptor,
    SessionSnapshot,
    SummaryItem,
)

_MAX_PREVIEW_CHARS = 2000
_MAX_DIRECTORY_PREVIEW_ITEMS = 12


@dataclass(frozen=True, slots=True)
class SnapshotSelections:
    change_path: str | None = None
    commit_id: str | None = None
    branch_name: str | None = None
    file_path: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotFeedback:
    level: Literal["info", "success", "error"]
    message: str


def build_snapshot(
    *,
    root: Path,
    repository: Repository | None,
    recent_roots: tuple[Path, ...] = (),
    selections: SnapshotSelections = SnapshotSelections(),
    feedback: SnapshotFeedback | None = None,
) -> tuple[SessionSnapshot, SnapshotSelections]:
    resolved_root = root.resolve()
    recent = _build_recent_repositories(
        active_root=resolved_root,
        repository=repository,
        recent_roots=recent_roots,
    )

    if repository is None:
        snapshot = _build_non_repository_snapshot(
            root=resolved_root,
            recent=recent,
            feedback=feedback,
        )
        return snapshot, SnapshotSelections()

    status = repository.status()
    operation = repository.current_operation()
    descriptor = _build_repository_descriptor(
        repository=repository,
        status=status,
        operation=operation,
    )
    commits = _build_commit_summaries(repository)
    branches = _build_branch_summaries(repository)
    tree = _build_file_tree(repository.root)
    staged, unstaged = _build_change_lists(status)

    normalized = SnapshotSelections(
        change_path=_pick_selection(
            preferred=selections.change_path,
            available=_ordered_unique_paths(staged + unstaged),
        ),
        commit_id=_pick_selection(
            preferred=selections.commit_id,
            available=tuple(commit.commit_id for commit in commits),
            fallback=repository.current_commit_id(),
        ),
        branch_name=_pick_selection(
            preferred=selections.branch_name,
            available=tuple(branch.name for branch in branches),
            fallback=repository.current_branch_name(),
        ),
        file_path=_pick_selection(
            preferred=selections.file_path,
            available=tuple(node.path for node in tree),
            fallback=_first_file_path(tree),
        ),
    )

    snapshot = SessionSnapshot(
        repository=descriptor,
        home=_build_home_view(
            repository=repository,
            descriptor=descriptor,
            recent=recent,
            feedback=feedback,
        ),
        changes=_build_changes_view(
            repository=repository,
            descriptor=descriptor,
            status=status,
            operation=operation,
            staged=staged,
            unstaged=unstaged,
            selected_path=normalized.change_path,
            feedback=feedback,
        ),
        history=_build_history_view(
            repository=repository,
            descriptor=descriptor,
            commits=commits,
            selected_commit=normalized.commit_id,
            feedback=feedback,
        ),
        branches=_build_branches_view(
            repository=repository,
            descriptor=descriptor,
            status=status,
            operation=operation,
            branches=branches,
            selected_branch=normalized.branch_name,
            feedback=feedback,
        ),
        files=_build_files_view(
            repository=repository,
            descriptor=descriptor,
            status=status,
            tree=tree,
            selected_path=normalized.file_path,
            feedback=feedback,
        ),
    )
    return snapshot, normalized


def _build_non_repository_snapshot(
    *,
    root: Path,
    recent: tuple[RecentRepository, ...],
    feedback: SnapshotFeedback | None,
) -> SessionSnapshot:
    guidance_title, guidance_body = _guidance(
        base=(
            "Initialize this folder to create a local-only repository, or open another folder "
            "that already contains .lit metadata."
        ),
        feedback=feedback,
    )
    descriptor = RepositoryDescriptor(
        name=root.name or str(root),
        root=root,
        status_text="No .lit metadata detected yet.",
        is_lit_repository=False,
    )
    home = HomeViewState(
        route=NavigationTarget.HOME,
        title="Repository Home",
        subtitle="Open an existing lit repository or initialize this folder in place.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Current folder", value=str(root)),
            SummaryItem(label="Repository status", value="Not initialized"),
            SummaryItem(label="Default branch", value="main"),
        ),
        recent_repositories=recent,
        call_to_action="Initialize this folder to start local-only history.",
        detail=DetailPaneState.placeholder(
            selection_title="Selected repository",
            selection_body=descriptor.name,
            metadata_title="Workspace metadata",
            metadata_body="No .lit directory was found in this folder.",
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )
    changes = ChangesViewState(
        route=NavigationTarget.CHANGES,
        title="Changes",
        subtitle="Load or initialize a repository to inspect working tree changes.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Staged entries", value="0"),
            SummaryItem(label="Unstaged entries", value="0"),
            SummaryItem(label="Commit readiness", value="No repository loaded"),
        ),
        staged=(),
        unstaged=(),
        selected_path=None,
        can_commit=False,
        commit_message_hint="Open or initialize a repository first.",
        detail=DetailPaneState.placeholder(
            selection_title="Selected change",
            selection_body="No repository loaded.",
            metadata_title="Changes metadata",
            metadata_body="The Changes view is unavailable until a lit repository is open.",
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )
    history = HistoryViewState(
        route=NavigationTarget.HISTORY,
        title="History",
        subtitle="Open a repository to inspect commit history.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Visible commits", value="0"),
            SummaryItem(label="Selected commit", value="None"),
        ),
        commits=(),
        selected_commit=None,
        detail=DetailPaneState.placeholder(
            selection_title="Selected commit",
            selection_body="No repository loaded.",
            metadata_title="History metadata",
            metadata_body="Commit history appears here after opening a lit repository.",
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )
    branches = BranchesViewState(
        route=NavigationTarget.BRANCHES,
        title="Branches",
        subtitle="Branch information appears after opening a repository.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Current branch", value="n/a"),
            SummaryItem(label="Branch count", value="0"),
        ),
        branches=(),
        selected_branch=None,
        can_checkout=False,
        detail=DetailPaneState.placeholder(
            selection_title="Selected branch",
            selection_body="No repository loaded.",
            metadata_title="Branch metadata",
            metadata_body="Branch actions are unavailable until a lit repository is open.",
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )
    files = FilesViewState(
        route=NavigationTarget.FILES,
        title="Files",
        subtitle="Repository file browsing appears after opening a repository.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Root", value=str(root)),
            SummaryItem(label="Visible nodes", value="0"),
        ),
        tree=(),
        selected_path=None,
        detail=DetailPaneState.placeholder(
            selection_title="Selected file",
            selection_body="No repository loaded.",
            metadata_title="File metadata",
            metadata_body="Open or initialize a repository to browse files.",
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )
    return SessionSnapshot(
        repository=descriptor,
        home=home,
        changes=changes,
        history=history,
        branches=branches,
        files=files,
    )


def _build_repository_descriptor(
    *,
    repository: Repository,
    status: StatusReport,
    operation: OperationState | None,
) -> RepositoryDescriptor:
    return RepositoryDescriptor(
        name=repository.root.name or str(repository.root),
        root=repository.root,
        current_branch=repository.current_branch_name(),
        head_commit=repository.current_commit_id(),
        status_text=_repository_status_text(repository, status, operation),
        is_lit_repository=True,
        operation=_operation_summary(operation),
    )


def _build_home_view(
    *,
    repository: Repository,
    descriptor: RepositoryDescriptor,
    recent: tuple[RecentRepository, ...],
    feedback: SnapshotFeedback | None,
) -> HomeViewState:
    guidance_title, guidance_body = _guidance(
        base=(
            "Use Changes to stage and commit work, History to inspect revisions, "
            "and Branches for checkout, merge, or rebase."
        ),
        feedback=feedback,
    )
    branch_label = descriptor.current_branch or "detached"
    commit_label = descriptor.head_commit[:12] if descriptor.head_commit is not None else "unborn"
    return HomeViewState(
        route=NavigationTarget.HOME,
        title="Repository Home",
        subtitle="Local-only repository state and recent workspaces.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Current folder", value=str(repository.root)),
            SummaryItem(label="Repository status", value=descriptor.status_text),
            SummaryItem(label="Branch", value=branch_label),
            SummaryItem(label="HEAD", value=commit_label),
        ),
        recent_repositories=recent,
        call_to_action="Use Changes to stage work or Branches to switch context.",
        detail=DetailPaneState.placeholder(
            selection_title="Selected repository",
            selection_body=descriptor.name,
            metadata_title="Workspace metadata",
            metadata_body=(
                f"Branch: {branch_label}\n"
                f"HEAD: {commit_label}\n"
                f"Root: {repository.root}"
            ),
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )


def _build_changes_view(
    *,
    repository: Repository,
    descriptor: RepositoryDescriptor,
    status: StatusReport,
    operation: OperationState | None,
    staged: tuple[ChangedPath, ...],
    unstaged: tuple[ChangedPath, ...],
    selected_path: str | None,
    feedback: SnapshotFeedback | None,
) -> ChangesViewState:
    selected_entries = tuple(entry for entry in staged + unstaged if entry.path == selected_path)
    guidance_title, guidance_body = _guidance(
        base=_changes_guidance(status=status, operation=operation),
        feedback=feedback,
    )
    return ChangesViewState(
        route=NavigationTarget.CHANGES,
        title="Changes",
        subtitle="Staged and unstaged working tree changes for the current repository.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Staged entries", value=str(len(staged))),
            SummaryItem(label="Unstaged entries", value=str(len(status.modified) + len(status.deleted))),
            SummaryItem(label="Untracked entries", value=str(len(status.untracked))),
            SummaryItem(label="Commit readiness", value="Ready" if _can_commit(staged, operation) else "Blocked"),
        ),
        staged=staged,
        unstaged=unstaged,
        selected_path=selected_path,
        can_commit=_can_commit(staged, operation),
        commit_message_hint=_commit_message_hint(staged, operation),
        detail=DetailPaneState.placeholder(
            selection_title="Selected change",
            selection_body=_change_selection_body(repository, selected_path),
            metadata_title="Change metadata",
            metadata_body=_change_metadata(selected_entries),
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )


def _build_history_view(
    *,
    repository: Repository,
    descriptor: RepositoryDescriptor,
    commits: tuple[CommitSummary, ...],
    selected_commit: str | None,
    feedback: SnapshotFeedback | None,
) -> HistoryViewState:
    selected = next((commit for commit in commits if commit.commit_id == selected_commit), None)
    guidance_title, guidance_body = _guidance(
        base="Select a commit to inspect its message, parent chain, and changed paths.",
        feedback=feedback,
    )
    return HistoryViewState(
        route=NavigationTarget.HISTORY,
        title="History",
        subtitle="First-parent commit history for the current checkout.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Visible commits", value=str(len(commits))),
            SummaryItem(label="Selected commit", value=selected_commit[:12] if selected_commit else "None"),
        ),
        commits=commits,
        selected_commit=selected_commit,
        detail=DetailPaneState.placeholder(
            selection_title="Selected commit",
            selection_body=_commit_selection_body(selected),
            metadata_title="Commit metadata",
            metadata_body=_commit_metadata(repository, selected),
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )


def _build_branches_view(
    *,
    repository: Repository,
    descriptor: RepositoryDescriptor,
    status: StatusReport,
    operation: OperationState | None,
    branches: tuple[BranchSummary, ...],
    selected_branch: str | None,
    feedback: SnapshotFeedback | None,
) -> BranchesViewState:
    selected = next((branch for branch in branches if branch.name == selected_branch), None)
    guidance_title, guidance_body = _guidance(
        base=_branch_guidance(status=status, operation=operation),
        feedback=feedback,
    )
    return BranchesViewState(
        route=NavigationTarget.BRANCHES,
        title="Branches",
        subtitle="Local branches and checkout readiness for the current repository.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Current branch", value=descriptor.current_branch or "detached"),
            SummaryItem(label="Branch count", value=str(len(branches))),
            SummaryItem(label="Checkout readiness", value="Ready" if _can_checkout(status, operation) else "Blocked"),
        ),
        branches=branches,
        selected_branch=selected_branch,
        can_checkout=_can_checkout(status, operation),
        detail=DetailPaneState.placeholder(
            selection_title="Selected branch",
            selection_body=_branch_selection_body(selected),
            metadata_title="Branch metadata",
            metadata_body=_branch_metadata(selected),
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )


def _build_files_view(
    *,
    repository: Repository,
    descriptor: RepositoryDescriptor,
    status: StatusReport,
    tree: tuple[FileNode, ...],
    selected_path: str | None,
    feedback: SnapshotFeedback | None,
) -> FilesViewState:
    selected = next((node for node in tree if node.path == selected_path), None)
    guidance_title, guidance_body = _guidance(
        base="Select a file to preview the working tree contents for the current checkout.",
        feedback=feedback,
    )
    return FilesViewState(
        route=NavigationTarget.FILES,
        title="Files",
        subtitle="Working tree file browser for the current repository.",
        context=descriptor,
        highlights=(
            SummaryItem(label="Root", value=str(repository.root)),
            SummaryItem(label="Visible nodes", value=str(len(tree))),
            SummaryItem(label="Selected file", value=selected_path or "None"),
        ),
        tree=tree,
        selected_path=selected_path,
        detail=DetailPaneState.placeholder(
            selection_title="Selected file",
            selection_body=_file_selection_body(repository, selected),
            metadata_title="File metadata",
            metadata_body=_file_metadata(repository, status, selected),
            guidance_title=guidance_title,
            guidance_body=guidance_body,
        ),
    )


def _build_recent_repositories(
    *,
    active_root: Path,
    repository: Repository | None,
    recent_roots: tuple[Path, ...],
) -> tuple[RecentRepository, ...]:
    ordered: list[Path] = []
    for candidate in (active_root, *recent_roots):
        resolved = candidate.resolve()
        if resolved not in ordered:
            ordered.append(resolved)

    entries: list[RecentRepository] = []
    for root in ordered[:5]:
        is_lit_repository = (root == active_root and repository is not None) or (root / ".lit").is_dir()
        summary = (
            _repository_status_text(repository, repository.status(), repository.current_operation())
            if root == active_root and repository is not None
            else "lit repository" if is_lit_repository else "Initialize this folder to start local history."
        )
        entries.append(
            RecentRepository(
                name=root.name or str(root),
                root=root,
                summary=summary,
                is_lit_repository=is_lit_repository,
            )
        )
    return tuple(entries)


def _build_change_lists(status: StatusReport) -> tuple[tuple[ChangedPath, ...], tuple[ChangedPath, ...]]:
    staged = tuple(
        ChangedPath(path=path, change_kind="added", staged=True)
        for path in status.staged_added
    ) + tuple(
        ChangedPath(path=path, change_kind="modified", staged=True)
        for path in status.staged_modified
    ) + tuple(
        ChangedPath(path=path, change_kind="deleted", staged=True)
        for path in status.staged_deleted
    )
    unstaged = tuple(
        ChangedPath(path=path, change_kind="modified")
        for path in status.modified
    ) + tuple(
        ChangedPath(path=path, change_kind="deleted")
        for path in status.deleted
    ) + tuple(
        ChangedPath(path=path, change_kind="untracked")
        for path in status.untracked
    )
    return staged, unstaged


def _build_commit_summaries(repository: Repository) -> tuple[CommitSummary, ...]:
    commits: list[CommitSummary] = []
    for commit_id, record in repository.iter_history():
        commits.append(
            CommitSummary(
                commit_id=commit_id,
                message=record.summary,
                author=record.metadata.author,
                committed_at=record.metadata.committed_at or "",
                changed_paths=_changed_paths_for_commit(repository, commit_id),
            )
        )
    return tuple(commits)


def _build_branch_summaries(repository: Repository) -> tuple[BranchSummary, ...]:
    return tuple(
        BranchSummary(
            name=branch.name,
            commit_id=branch.commit_id,
            is_current=branch.current,
            note=_branch_note(branch),
        )
        for branch in repository.list_branches()
    )


def _build_file_tree(root: Path) -> tuple[FileNode, ...]:
    nodes: list[FileNode] = []

    def visit(directory: Path, depth: int) -> None:
        entries = [
            entry
            for entry in sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower(), item.name),
            )
            if entry.name != ".lit"
        ]
        for entry in entries:
            relative = normalize_repo_path(entry.relative_to(root))
            nodes.append(
                FileNode(
                    path=relative,
                    display_name=entry.name,
                    node_kind="directory" if entry.is_dir() else "file",
                    depth=depth,
                )
            )
            if entry.is_dir():
                visit(entry, depth + 1)

    if root.exists():
        visit(root, 0)
    return tuple(nodes)


def _ordered_unique_paths(entries: tuple[ChangedPath, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in entries:
        if entry.path in seen:
            continue
        seen.add(entry.path)
        ordered.append(entry.path)
    return tuple(ordered)


def _pick_selection(
    *,
    preferred: str | None,
    available: tuple[str, ...],
    fallback: str | None = None,
) -> str | None:
    allowed = set(available)
    if preferred in allowed:
        return preferred
    if fallback in allowed:
        return fallback
    return available[0] if available else None


def _first_file_path(tree: tuple[FileNode, ...]) -> str | None:
    for node in tree:
        if node.node_kind == "file":
            return node.path
    return None


def _changed_paths_for_commit(repository: Repository, commit_id: str) -> tuple[str, ...]:
    record = repository.read_commit(commit_id)
    current = repository.read_commit_tree(commit_id)
    parent = repository.read_commit_tree(record.primary_parent)
    changed = sorted(
        path
        for path in set(current) | set(parent)
        if not _tracked_file_equal(current.get(path), parent.get(path))
    )
    return tuple(changed)


def _tracked_file_equal(left: TrackedFile | None, right: TrackedFile | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return (
        left.digest == right.digest
        and left.executable == right.executable
        and left.size == right.size
    )


def _guidance(*, base: str, feedback: SnapshotFeedback | None) -> tuple[str, str]:
    if feedback is None:
        return "Next action", base
    title = {
        "error": "Action blocked",
        "info": "Latest action",
        "success": "Latest action",
    }[feedback.level]
    return title, f"{feedback.message}\n\n{base}"


def _repository_status_text(
    repository: Repository,
    status: StatusReport,
    operation: OperationState | None,
) -> str:
    if operation is not None:
        operation_summary = _operation_summary(operation)
        return operation_summary.summary if operation_summary is not None else "Operation in progress."

    head_commit = repository.current_commit_id()
    if head_commit is None:
        if status.untracked:
            return f"Unborn branch with {len(status.untracked)} untracked path(s)."
        return "No commits yet."
    if status.is_clean():
        if repository.current_branch_name() is None:
            return f"Detached HEAD at {head_commit[:12]}."
        return "Working tree clean."

    parts: list[str] = []
    staged_count = len(status.staged_added) + len(status.staged_modified) + len(status.staged_deleted)
    unstaged_count = len(status.modified) + len(status.deleted)
    if staged_count:
        parts.append(f"{staged_count} staged")
    if unstaged_count:
        parts.append(f"{unstaged_count} unstaged")
    if status.untracked:
        parts.append(f"{len(status.untracked)} untracked")
    return ", ".join(parts) + " path(s)."


def _operation_summary(operation: OperationState | None) -> OperationSummary | None:
    if operation is None:
        return None

    if operation.kind == "merge":
        state = operation.state
        assert isinstance(state, MergeState)
        target = branch_name_from_ref(state.target_ref) or state.target_commit[:12]
        summary = (
            f"Merge in progress from {target} with {len(state.conflicts)} conflicting path(s)."
            if state.conflicts
            else f"Merge in progress from {target}."
        )
        return OperationSummary(kind="merge", summary=summary, conflicts=state.conflicts)

    state = operation.state
    assert isinstance(state, RebaseState)
    summary = (
        f"Rebase in progress onto {state.onto[:12]} with {len(state.conflicts)} conflicting path(s)."
        if state.conflicts
        else f"Rebase in progress onto {state.onto[:12]}."
    )
    return OperationSummary(kind="rebase", summary=summary, conflicts=state.conflicts)


def _can_commit(staged: tuple[ChangedPath, ...], operation: OperationState | None) -> bool:
    return bool(staged) and operation is None


def _commit_message_hint(staged: tuple[ChangedPath, ...], operation: OperationState | None) -> str:
    if operation is not None:
        return "Resolve or abort the active operation before creating another commit."
    if not staged:
        return "Stage one or more paths to enable commit."
    return "Enter a message to commit the staged paths."


def _changes_guidance(*, status: StatusReport, operation: OperationState | None) -> str:
    if operation is not None:
        return (
            "Resolve the listed conflicts or abort the active operation before staging, "
            "checking out, or committing more work."
        )
    if status.is_clean():
        return "Working tree clean. Edit files or switch branches to create new changes."
    return "Stage paths to prepare a commit, or restore them to discard working tree changes."


def _change_selection_body(repository: Repository, path: str | None) -> str:
    if path is None:
        return "No changed path selected."
    return _truncate_text(_render_change_preview(repository, path))


def _change_metadata(entries: tuple[ChangedPath, ...]) -> str:
    if not entries:
        return "No change metadata available."

    lines = [f"Path: {entries[0].path}"]
    states = [f"{'staged ' if entry.staged else ''}{entry.change_kind}" for entry in entries]
    lines.append(f"State: {', '.join(states)}")
    if len(entries) > 1:
        lines.append("This path has both staged and unstaged changes.")
    return "\n".join(lines)


def _render_change_preview(repository: Repository, path: str) -> str:
    head_file = repository.read_commit_tree(repository.current_commit_id()).get(path)
    before = [] if head_file is None else _decode_blob_lines(repository, head_file)
    working_path = repository.root / path
    after = [] if not working_path.exists() or not working_path.is_file() else _read_text_lines(working_path)
    diff_lines = list(
        unified_diff(
            before,
            after,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if diff_lines:
        return "\n".join(diff_lines)
    if working_path.exists() and working_path.is_file():
        return _read_preview_text(working_path)
    return "File was removed from the working tree."


def _commit_selection_body(selected: CommitSummary | None) -> str:
    if selected is None:
        return "No commit selected."
    return selected.message or "(empty commit message)"


def _commit_metadata(repository: Repository, selected: CommitSummary | None) -> str:
    if selected is None:
        return "No commit metadata available."

    record = repository.read_commit(selected.commit_id)
    parents = ", ".join(parent[:12] for parent in record.parents) or "none"
    changed = ", ".join(selected.changed_paths) or "none"
    committed_at = selected.committed_at or "unknown"
    return (
        f"Commit: {selected.commit_id}\n"
        f"Author: {selected.author or 'lit'}\n"
        f"Committed at: {committed_at}\n"
        f"Parents: {parents}\n"
        f"Changed paths: {changed}"
    )


def _branch_guidance(*, status: StatusReport, operation: OperationState | None) -> str:
    if operation is not None:
        return "Abort the active operation before checking out another branch."
    if not _can_checkout(status, operation):
        return "Clean tracked changes before checkout. Untracked files may still block specific targets."
    return "Create a branch from the current HEAD or checkout another local branch or commit."


def _can_checkout(status: StatusReport, operation: OperationState | None) -> bool:
    if operation is not None:
        return False
    return not any(
        (
            status.staged_added,
            status.staged_modified,
            status.staged_deleted,
            status.modified,
            status.deleted,
        )
    )


def _branch_selection_body(selected: BranchSummary | None) -> str:
    if selected is None:
        return "No branch selected."
    target = selected.commit_id[:12] if selected.commit_id is not None else "unborn"
    prefix = "Current branch" if selected.is_current else "Local branch"
    return f"{prefix}: {selected.name} -> {target}"


def _branch_metadata(selected: BranchSummary | None) -> str:
    if selected is None:
        return "No branch metadata available."
    target = selected.commit_id or "unborn"
    state = "current" if selected.is_current else "not current"
    note = selected.note or "No branch note."
    return f"Commit: {target}\nState: {state}\nNote: {note}"


def _branch_note(branch: BranchRecord) -> str:
    if branch.current:
        return "Checked out."
    if branch.commit_id is None:
        return "Unborn branch."
    return f"Points to {branch.commit_id[:12]}."


def _file_selection_body(repository: Repository, selected: FileNode | None) -> str:
    if selected is None:
        return "No file selected."

    target = repository.root / selected.path
    if selected.node_kind == "directory":
        return _directory_preview(target)
    if not target.exists():
        return "File is no longer present in the working tree."
    return _truncate_text(_read_preview_text(target))


def _file_metadata(repository: Repository, status: StatusReport, selected: FileNode | None) -> str:
    if selected is None:
        return "No file metadata available."

    staged_paths = set(status.staged_added) | set(status.staged_modified) | set(status.staged_deleted)
    unstaged_paths = set(status.modified) | set(status.deleted)
    labels: list[str] = []
    if selected.path in staged_paths:
        labels.append("staged")
    if selected.path in unstaged_paths:
        labels.append("unstaged")
    if selected.path in set(status.untracked):
        labels.append("untracked")
    if not labels and selected.node_kind == "file":
        labels.append("tracked")

    target = repository.root / selected.path
    size = target.stat().st_size if target.exists() and target.is_file() else 0
    state = ", ".join(labels) if labels else "n/a"
    return f"Path: {selected.path}\nKind: {selected.node_kind}\nState: {state}\nSize: {size} bytes"


def _directory_preview(path: Path) -> str:
    if not path.exists():
        return "Directory is no longer present in the working tree."

    children = [
        child.name
        for child in sorted(
            path.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower(), item.name),
        )
        if child.name != ".lit"
    ]
    if not children:
        return "Empty directory."

    listed = children[:_MAX_DIRECTORY_PREVIEW_ITEMS]
    preview = "\n".join(listed)
    if len(children) > len(listed):
        preview += f"\n... and {len(children) - len(listed)} more"
    return preview


def _read_preview_text(path: Path) -> str:
    payload = path.read_bytes()
    if b"\x00" in payload:
        return "Binary preview unavailable."
    text = payload.decode("utf-8", errors="replace")
    return text if text else "(empty file)"


def _decode_blob_lines(repository: Repository, tracked_file: TrackedFile) -> list[str]:
    payload = repository.read_object("blobs", tracked_file.digest)
    return payload.decode("utf-8", errors="replace").splitlines()


def _read_text_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _truncate_text(text: str) -> str:
    if len(text) <= _MAX_PREVIEW_CHARS:
        return text
    return text[:_MAX_PREVIEW_CHARS].rstrip() + "\n...\n[truncated]"
