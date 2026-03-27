from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal


class NavigationTarget(StrEnum):
    HOME = "home"
    CHANGES = "changes"
    HISTORY = "history"
    BRANCHES = "branches"
    FILES = "files"


VIEW_ORDER: tuple[NavigationTarget, ...] = (
    NavigationTarget.HOME,
    NavigationTarget.CHANGES,
    NavigationTarget.HISTORY,
    NavigationTarget.BRANCHES,
    NavigationTarget.FILES,
)


class DetailSlotId(StrEnum):
    SELECTION = "selection"
    METADATA = "metadata"
    GUIDANCE = "guidance"


@dataclass(frozen=True, slots=True)
class OperationSummary:
    kind: Literal["merge", "rebase"]
    summary: str
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepositoryDescriptor:
    name: str
    root: Path | None = None
    current_branch: str | None = None
    head_commit: str | None = None
    status_text: str = ""
    is_lit_repository: bool = False
    operation: OperationSummary | None = None
    attention: str = ""


@dataclass(frozen=True, slots=True)
class RecentRepository:
    name: str
    root: Path
    summary: str = ""
    is_lit_repository: bool = False


@dataclass(frozen=True, slots=True)
class SummaryItem:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class DetailSlotState:
    slot_id: DetailSlotId
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class DetailPaneState:
    selection: DetailSlotState
    metadata: DetailSlotState
    guidance: DetailSlotState

    @classmethod
    def placeholder(
        cls,
        *,
        selection_title: str,
        selection_body: str,
        metadata_title: str,
        metadata_body: str,
        guidance_title: str,
        guidance_body: str,
    ) -> "DetailPaneState":
        return cls(
            selection=DetailSlotState(
                slot_id=DetailSlotId.SELECTION,
                title=selection_title,
                body=selection_body,
            ),
            metadata=DetailSlotState(
                slot_id=DetailSlotId.METADATA,
                title=metadata_title,
                body=metadata_body,
            ),
            guidance=DetailSlotState(
                slot_id=DetailSlotId.GUIDANCE,
                title=guidance_title,
                body=guidance_body,
            ),
        )

    def slots(self) -> tuple[DetailSlotState, ...]:
        return (self.selection, self.metadata, self.guidance)


@dataclass(frozen=True, slots=True)
class BaseViewState:
    route: NavigationTarget
    title: str
    subtitle: str
    detail: DetailPaneState


@dataclass(frozen=True, slots=True)
class ChangedPath:
    path: str
    change_kind: Literal["added", "modified", "deleted", "untracked"]
    staged: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class CommitSummary:
    commit_id: str
    message: str
    author: str = ""
    committed_at: str = ""
    changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BranchSummary:
    name: str
    commit_id: str | None = None
    is_current: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class FileNode:
    path: str
    display_name: str
    node_kind: Literal["directory", "file"]
    depth: int = 0


@dataclass(frozen=True, slots=True)
class HomeViewState(BaseViewState):
    context: RepositoryDescriptor | None = None
    highlights: tuple[SummaryItem, ...] = ()
    recent_repositories: tuple[RecentRepository, ...] = ()
    call_to_action: str = ""


@dataclass(frozen=True, slots=True)
class ChangesViewState(BaseViewState):
    context: RepositoryDescriptor | None = None
    highlights: tuple[SummaryItem, ...] = ()
    staged: tuple[ChangedPath, ...] = ()
    unstaged: tuple[ChangedPath, ...] = ()
    selected_path: str | None = None
    can_commit: bool = False
    commit_message_hint: str = ""


@dataclass(frozen=True, slots=True)
class HistoryViewState(BaseViewState):
    context: RepositoryDescriptor | None = None
    highlights: tuple[SummaryItem, ...] = ()
    commits: tuple[CommitSummary, ...] = ()
    selected_commit: str | None = None
    selected_path: str | None = None


@dataclass(frozen=True, slots=True)
class BranchesViewState(BaseViewState):
    context: RepositoryDescriptor | None = None
    highlights: tuple[SummaryItem, ...] = ()
    branches: tuple[BranchSummary, ...] = ()
    selected_branch: str | None = None
    can_checkout: bool = False
    can_merge: bool = False
    can_rebase: bool = False
    restore_suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class FilesViewState(BaseViewState):
    context: RepositoryDescriptor | None = None
    highlights: tuple[SummaryItem, ...] = ()
    tree: tuple[FileNode, ...] = ()
    selected_path: str | None = None


ShellViewState = HomeViewState | ChangesViewState | HistoryViewState | BranchesViewState | FilesViewState


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    repository: RepositoryDescriptor | None
    home: HomeViewState
    changes: ChangesViewState
    history: HistoryViewState
    branches: BranchesViewState
    files: FilesViewState

    @property
    def default_view(self) -> NavigationTarget:
        if self.repository is not None and self.repository.is_lit_repository:
            return NavigationTarget.CHANGES
        return NavigationTarget.HOME

    def for_view(self, target: NavigationTarget) -> ShellViewState:
        return {
            NavigationTarget.HOME: self.home,
            NavigationTarget.CHANGES: self.changes,
            NavigationTarget.HISTORY: self.history,
            NavigationTarget.BRANCHES: self.branches,
            NavigationTarget.FILES: self.files,
        }[target]


class RepositorySession(ABC):
    """Desktop GUI boundary: `lit_gui` is a PySide6 client over the existing Python `lit` backend. `RepositorySession` is the only query and mutation gateway and returns immutable DTOs for all views. The shell owns three stable regions (sidebar, active center view, right detail panel); feature views may fill slots but must not rewire the shell. Views do not import `lit.repository` directly and do not persist metadata inside user repositories."""

    @abstractmethod
    def snapshot(self) -> SessionSnapshot:
        """Return the latest immutable snapshot for all shell views."""

    @abstractmethod
    def open_repository(self, root: Path) -> SessionSnapshot:
        """Open an existing folder and rebuild every view state."""

    @abstractmethod
    def initialize_repository(self, root: Path) -> SessionSnapshot:
        """Initialize a repository and rebuild every view state."""

    @abstractmethod
    def refresh(self) -> SessionSnapshot:
        """Reload the active repository into a fresh snapshot."""

    @abstractmethod
    def stage_paths(self, paths: tuple[str, ...]) -> SessionSnapshot:
        """Stage the provided paths for commit."""

    @abstractmethod
    def restore_paths(self, paths: tuple[str, ...], *, source: str | None = None) -> SessionSnapshot:
        """Restore paths from the working tree or a specific revision."""

    @abstractmethod
    def commit(self, message: str) -> SessionSnapshot:
        """Create a commit and return the updated shell snapshot."""

    @abstractmethod
    def select_change(self, path: str) -> SessionSnapshot:
        """Update the selected change and its shared detail slots."""

    @abstractmethod
    def select_commit(self, commit_id: str) -> SessionSnapshot:
        """Update the selected history item and its shared detail slots."""

    @abstractmethod
    def select_commit_path(self, path: str | None) -> SessionSnapshot:
        """Update the selected changed file for the current history item."""

    @abstractmethod
    def create_branch(self, name: str, *, start_point: str | None = "HEAD") -> SessionSnapshot:
        """Create a branch and return the updated shell snapshot."""

    @abstractmethod
    def select_branch(self, branch_name: str) -> SessionSnapshot:
        """Update the selected branch and its shared detail slots."""

    @abstractmethod
    def checkout(self, revision: str) -> SessionSnapshot:
        """Switch to another branch or detach at a commit."""

    @abstractmethod
    def merge(self, revision: str) -> SessionSnapshot:
        """Start or complete a merge and return the updated shell snapshot."""

    @abstractmethod
    def abort_merge(self) -> SessionSnapshot:
        """Abort the active merge state and return the updated shell snapshot."""

    @abstractmethod
    def rebase(self, revision: str) -> SessionSnapshot:
        """Start or complete a rebase and return the updated shell snapshot."""

    @abstractmethod
    def abort_rebase(self) -> SessionSnapshot:
        """Abort the active rebase state and return the updated shell snapshot."""

    @abstractmethod
    def select_file(self, path: str) -> SessionSnapshot:
        """Update the selected file or tree node and its shared detail slots."""
