from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, TypeVar

from lit.merge_ops import MergeResult, merge_revision
from lit.rebase_ops import RebaseResult, rebase_onto
from lit.repository import CheckoutRecord, Repository
from lit_gui.backend import SnapshotFeedback, SnapshotSelections, build_snapshot
from lit_gui.contracts import RepositorySession, SessionSnapshot
from lit_gui.persistence import RecentRepositoriesStore

_T = TypeVar("_T")


class LitRepositorySession(RepositorySession):
    def __init__(
        self,
        root: Path | None = None,
        *,
        recent_store: RecentRepositoriesStore | None = None,
    ) -> None:
        self._recent_store = recent_store or RecentRepositoriesStore()
        self._root = self._resolve_root(root or Path.cwd())
        self._repository: Repository | None = self._reload_repository(self._root)
        self._recent_roots: tuple[Path, ...] = self._recent_store.load()
        self._selections = SnapshotSelections()
        self._feedback: SnapshotFeedback | None = None
        self._snapshot = self._rebuild_snapshot()

    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def open_repository(self, root: Path) -> SessionSnapshot:
        self._root = self._resolve_root(root)
        validation_error = self._validate_open_root(self._root)
        if validation_error is not None:
            self._repository = None
            self._selections = SnapshotSelections()
            return self._rebuild_snapshot(
                feedback=SnapshotFeedback(level="error", message=validation_error)
            )

        self._repository = self._reload_repository(self._root)
        self._selections = SnapshotSelections()
        self._remember_recent(self._root, persist=True)
        if self._repository is None:
            return self._rebuild_snapshot(
                feedback=SnapshotFeedback(
                    level="info",
                    message=f"No .lit metadata detected at {self._root}.",
                )
            )
        return self._rebuild_snapshot(
            feedback=SnapshotFeedback(
                level="success",
                message=f"Opened lit repository at {self._root}.",
            )
        )

    def initialize_repository(self, root: Path) -> SessionSnapshot:
        self._root = self._resolve_root(root)
        validation_error = self._validate_initialize_root(self._root)
        if validation_error is not None:
            self._repository = None
            self._selections = SnapshotSelections()
            return self._rebuild_snapshot(
                feedback=SnapshotFeedback(level="error", message=validation_error)
            )

        already_initialized = (self._root / ".lit").is_dir()
        self._repository = Repository.create(self._root)
        self._selections = SnapshotSelections()
        self._remember_recent(self._root, persist=True)
        message = (
            f"Opened existing lit repository at {self._root}."
            if already_initialized
            else f"Initialized empty lit repository in {self._repository.layout.dot_lit}."
        )
        return self._rebuild_snapshot(feedback=SnapshotFeedback(level="success", message=message))

    def refresh(self) -> SessionSnapshot:
        self._repository = self._reload_repository(self._root)
        message = (
            f"Repository refreshed at {self._root}."
            if self._repository is not None
            else f"No .lit metadata detected at {self._root}."
        )
        level = "success" if self._repository is not None else "info"
        return self._rebuild_snapshot(feedback=SnapshotFeedback(level=level, message=message))

    def stage_paths(self, paths: tuple[str, ...]) -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: repository.stage(paths),
            on_success=lambda staged: SnapshotFeedback(
                level="success",
                message=f"staged {len(staged)} path(s)",
            ),
        )

    def restore_paths(self, paths: tuple[str, ...], *, source: str | None = None) -> SessionSnapshot:
        source_label = source or "HEAD"
        return self._run_repository_action(
            lambda repository: repository.restore(paths, source=source),
            on_success=lambda restored: SnapshotFeedback(
                level="success",
                message=f"restored {len(restored)} path(s) from {source_label}",
            ),
        )

    def commit(self, message: str) -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: repository.commit(message),
            on_success=lambda commit_id: self._commit_feedback(commit_id, message),
            update_selections=lambda commit_id: replace(self._selections, commit_id=commit_id),
        )

    def select_change(self, path: str) -> SessionSnapshot:
        self._selections = replace(self._selections, change_path=path)
        return self._rebuild_snapshot()

    def select_commit(self, commit_id: str) -> SessionSnapshot:
        self._selections = replace(self._selections, commit_id=commit_id)
        return self._rebuild_snapshot()

    def create_branch(self, name: str, *, start_point: str | None = "HEAD") -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: repository.create_branch(name, start_point=start_point),
            on_success=lambda branch: SnapshotFeedback(
                level="success",
                message=f"{branch.name} -> {branch.commit_id[:12] if branch.commit_id else 'unborn'}",
            ),
            update_selections=lambda branch: replace(self._selections, branch_name=branch.name),
        )

    def select_branch(self, branch_name: str) -> SessionSnapshot:
        self._selections = replace(self._selections, branch_name=branch_name)
        return self._rebuild_snapshot()

    def checkout(self, revision: str) -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: repository.checkout(revision),
            on_success=self._checkout_feedback,
            update_selections=self._checkout_selections,
        )

    def merge(self, revision: str) -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: merge_revision(repository, revision),
            on_success=lambda result: SnapshotFeedback(level="success", message=result.message),
            update_selections=self._merge_selections,
        )

    def abort_merge(self) -> SessionSnapshot:
        def abort(repository: Repository) -> str:
            state = repository.read_merge_state()
            if state is None:
                raise ValueError("No merge in progress.")
            repository.apply_commit(
                state.current_commit,
                baseline_commit=repository.current_commit_id(),
            )
            repository.clear_merge()
            return state.current_commit

        return self._run_repository_action(
            abort,
            on_success=lambda _: SnapshotFeedback(level="success", message="Merge state cleared."),
            update_selections=lambda commit_id: replace(
                self._selections,
                change_path=None,
                commit_id=commit_id,
            ),
        )

    def rebase(self, revision: str) -> SessionSnapshot:
        return self._run_repository_action(
            lambda repository: rebase_onto(repository, revision),
            on_success=lambda result: SnapshotFeedback(level="success", message=result.message),
            update_selections=self._rebase_selections,
        )

    def abort_rebase(self) -> SessionSnapshot:
        def abort(repository: Repository) -> str:
            state = repository.read_rebase_state()
            if state is None:
                raise ValueError("No rebase in progress.")
            branch_name = repository.current_branch_name()
            if branch_name is not None:
                repository.write_branch(branch_name, state.original_head)
            repository.apply_commit(
                state.original_head,
                baseline_commit=repository.current_commit_id(),
            )
            repository.clear_rebase()
            return state.original_head

        return self._run_repository_action(
            abort,
            on_success=lambda _: SnapshotFeedback(level="success", message="Rebase state cleared."),
            update_selections=lambda commit_id: replace(
                self._selections,
                change_path=None,
                commit_id=commit_id,
            ),
        )

    def select_file(self, path: str) -> SessionSnapshot:
        self._selections = replace(self._selections, file_path=path)
        return self._rebuild_snapshot()

    def _run_repository_action(
        self,
        operation: Callable[[Repository], _T],
        *,
        on_success: Callable[[_T], SnapshotFeedback],
        update_selections: Callable[[_T], SnapshotSelections] | None = None,
    ) -> SessionSnapshot:
        repository = self._repository
        if repository is None:
            return self._rebuild_snapshot(
                feedback=SnapshotFeedback(
                    level="error",
                    message="Open or initialize a repository first.",
                )
            )

        try:
            result = operation(repository)
        except (FileNotFoundError, RuntimeError, ValueError) as error:
            self._repository = self._reload_repository(self._root)
            return self._rebuild_snapshot(
                feedback=SnapshotFeedback(level="error", message=str(error))
            )

        if update_selections is not None:
            self._selections = update_selections(result)
        self._repository = self._reload_repository(self._root)
        return self._rebuild_snapshot(feedback=on_success(result))

    def _rebuild_snapshot(self, *, feedback: SnapshotFeedback | None = None) -> SessionSnapshot:
        if feedback is not None:
            self._feedback = feedback
        self._snapshot, self._selections = build_snapshot(
            root=self._root,
            repository=self._repository,
            recent_roots=self._recent_roots,
            selections=self._selections,
            feedback=self._feedback,
        )
        return self._snapshot

    def _remember_recent(self, root: Path, *, persist: bool = False) -> None:
        ordered = [root]
        ordered.extend(existing for existing in self._recent_roots if existing != root)
        self._recent_roots = tuple(ordered[:5])
        if persist:
            self._recent_store.save(self._recent_roots)

    def _reload_repository(self, root: Path) -> Repository | None:
        try:
            return Repository.open(root)
        except FileNotFoundError:
            return None

    def _resolve_root(self, root: Path) -> Path:
        return Path(root).expanduser().resolve()

    def _validate_open_root(self, root: Path) -> str | None:
        if not root.exists():
            return f"Folder not found: {root}."
        if not root.is_dir():
            return f"Path is not a folder: {root}."
        return None

    def _validate_initialize_root(self, root: Path) -> str | None:
        if root.exists() and not root.is_dir():
            return f"Path is not a folder: {root}."
        return None

    def _commit_feedback(self, commit_id: str, message: str) -> SnapshotFeedback:
        branch_name = self._repository.current_branch_name() if self._repository is not None else None
        label = branch_name or "detached"
        return SnapshotFeedback(
            level="success",
            message=f"[{label} {commit_id[:12]}] {message}",
        )

    def _checkout_feedback(self, result: CheckoutRecord) -> SnapshotFeedback:
        if result.branch_name is not None:
            return SnapshotFeedback(
                level="success",
                message=f"switched to branch {result.branch_name}",
            )
        target = "unborn" if result.commit_id is None else result.commit_id[:12]
        return SnapshotFeedback(level="success", message=f"detached HEAD at {target}")

    def _checkout_selections(self, result: CheckoutRecord) -> SnapshotSelections:
        return replace(
            self._selections,
            branch_name=result.branch_name,
            commit_id=result.commit_id,
            change_path=None,
        )

    def _merge_selections(self, result: MergeResult) -> SnapshotSelections:
        branch_name = self._repository.current_branch_name() if self._repository is not None else self._selections.branch_name
        return replace(
            self._selections,
            branch_name=branch_name,
            change_path=result.conflicts[0] if result.conflicts else None,
            file_path=result.conflicts[0] if result.conflicts else self._selections.file_path,
            commit_id=result.commit_id if result.commit_id is not None else self._selections.commit_id,
        )

    def _rebase_selections(self, result: RebaseResult) -> SnapshotSelections:
        branch_name = self._repository.current_branch_name() if self._repository is not None else self._selections.branch_name
        return replace(
            self._selections,
            branch_name=branch_name,
            change_path=result.conflicts[0] if result.conflicts else None,
            file_path=result.conflicts[0] if result.conflicts else self._selections.file_path,
            commit_id=result.commit_id if result.commit_id is not None else self._selections.commit_id,
        )
