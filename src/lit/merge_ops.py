from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from lit.domain import OperationKind, OperationStatus, ProvenanceRecord
from lit.refs import branch_ref
from lit.repository import Repository, TrackedFile


@dataclass(frozen=True)
class MergeResult:
    status: str
    message: str
    commit_id: str | None = None
    conflicts: tuple[str, ...] = ()


def merge_revision(repository: Repository, revision: str) -> MergeResult:
    _ensure_operation_ready(repository)
    branch_name = _current_branch(repository)
    with repository._mutation(OperationKind.MERGE.value, message=f"merge {revision}"):
        operation = repository._begin_operation(
            OperationKind.MERGE,
            message=f"merge {revision}",
            lineage_id=branch_name,
        )
        try:
            current_commit = repository.current_commit_id()
            if current_commit is None:
                raise ValueError("merge requires at least one commit on the current branch")

            target_commit = repository.resolve_revision(revision)
            if target_commit is None:
                raise ValueError(f"unknown revision: {revision}")

            if target_commit == current_commit:
                repository._finish_operation(
                    operation,
                    status=OperationStatus.SUCCEEDED,
                    revision_id=current_commit,
                    lineage_id=branch_name,
                    message="Already up to date.",
                )
                return MergeResult(status="noop", message="Already up to date.")

            base_commit = repository.merge_base(current_commit, target_commit)
            if base_commit == target_commit:
                repository._finish_operation(
                    operation,
                    status=OperationStatus.SUCCEEDED,
                    revision_id=current_commit,
                    lineage_id=branch_name,
                    message="Already up to date.",
                )
                return MergeResult(status="noop", message="Already up to date.")

            target_ref = _resolve_target_ref(repository, revision)
            if base_commit == current_commit:
                repository.write_branch(branch_name, target_commit)
                repository.apply_commit(target_commit, baseline_commit=current_commit)
                repository.clear_merge()
                repository._ensure_lineage(branch_name, head_revision=target_commit)
                repository._finish_operation(
                    operation,
                    status=OperationStatus.SUCCEEDED,
                    revision_id=target_commit,
                    lineage_id=branch_name,
                )
                return MergeResult(
                    status="fast_forward",
                    message=f"Fast-forwarded to {target_commit[:12]}.",
                    commit_id=target_commit,
                )

            base_tree = repository.read_commit_tree(base_commit)
            current_tree = repository.read_commit_tree(current_commit)
            target_tree = repository.read_commit_tree(target_commit)
            plan = _merge_trees(repository, base_tree, current_tree, target_tree)

            repository.apply_tree(plan.files, baseline=current_tree)
            if plan.conflicts:
                _write_conflicts(repository, plan.conflicts)
                repository.begin_merge(
                    base_commit=base_commit or "",
                    current_commit=current_commit,
                    target_commit=target_commit,
                    target_ref=target_ref,
                    conflicts=plan.conflict_paths,
                )
                repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    revision_id=current_commit,
                    lineage_id=branch_name,
                    message="Merge stopped with conflicts.",
                )
                return MergeResult(
                    status="conflict",
                    message="Merge stopped with conflicts.",
                    conflicts=plan.conflict_paths,
                )

            commit_id = repository.create_revision_from_tree(
                tree=plan.files,
                parents=(current_commit, target_commit),
                message=f"Merge {revision} into {branch_name}",
                provenance=ProvenanceRecord(
                    actor_role="merge",
                    actor_id="lit",
                    lineage_id=branch_name,
                    committed_at=None,
                    origin_commit=current_commit,
                ),
            )
            repository.apply_commit(commit_id, baseline_commit=current_commit)
            repository.clear_merge()
            repository._finish_operation(
                operation,
                status=OperationStatus.SUCCEEDED,
                revision_id=commit_id,
                lineage_id=branch_name,
            )
            return MergeResult(
                status="merged",
                message=f"Merge commit created: {commit_id[:12]}",
                commit_id=commit_id,
            )
        except Exception as error:
            repository._finish_operation(
                operation,
                status=OperationStatus.FAILED,
                lineage_id=branch_name,
                message=str(error),
            )
            raise


@dataclass(frozen=True)
class ConflictFile:
    path: str
    content: str


@dataclass(frozen=True)
class MergePlan:
    files: dict[str, TrackedFile]
    conflicts: tuple[ConflictFile, ...]

    @property
    def conflict_paths(self) -> tuple[str, ...]:
        return tuple(conflict.path for conflict in self.conflicts)


def _merge_trees(
    repository: Repository,
    base_tree: Mapping[str, TrackedFile],
    current_tree: Mapping[str, TrackedFile],
    target_tree: Mapping[str, TrackedFile],
) -> MergePlan:
    merged: dict[str, TrackedFile] = {}
    conflicts: list[ConflictFile] = []
    for path in sorted(set(base_tree) | set(current_tree) | set(target_tree)):
        base_file = base_tree.get(path)
        current_file = current_tree.get(path)
        target_file = target_tree.get(path)
        resolved = _resolve_path(repository, base_file, current_file, target_file)
        if isinstance(resolved, ConflictFile):
            conflicts.append(resolved)
            continue
        if resolved is not None:
            merged[path] = resolved
    return MergePlan(files=merged, conflicts=tuple(conflicts))


def _resolve_path(
    repository: Repository,
    base_file: TrackedFile | None,
    current_file: TrackedFile | None,
    target_file: TrackedFile | None,
) -> TrackedFile | ConflictFile | None:
    if _same_file(current_file, target_file):
        return current_file
    if _same_file(base_file, current_file):
        return target_file
    if _same_file(base_file, target_file):
        return current_file

    path = (current_file or target_file or base_file)
    if path is None:
        return None
    return ConflictFile(
        path=path.path,
        content=_render_conflict(repository, base_file, current_file, target_file),
    )


def _same_file(left: TrackedFile | None, right: TrackedFile | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return (
        left.digest == right.digest
        and left.executable == right.executable
        and left.size == right.size
    )


def _render_conflict(
    repository: Repository,
    base_file: TrackedFile | None,
    current_file: TrackedFile | None,
    target_file: TrackedFile | None,
) -> str:
    ours = _decode_file(repository, current_file)
    base = _decode_file(repository, base_file)
    theirs = _decode_file(repository, target_file)
    return (
        "<<<<<<< current\n"
        f"{ours}"
        "||||||| base\n"
        f"{base}"
        "=======\n"
        f"{theirs}"
        ">>>>>>> target\n"
    )


def _decode_file(repository: Repository, file: TrackedFile | None) -> str:
    if file is None:
        return ""
    return repository.read_object("blobs", file.digest).decode("utf-8", errors="replace")


def _write_conflicts(repository: Repository, conflicts: tuple[ConflictFile, ...]) -> None:
    for conflict in conflicts:
        target = repository.root / Path(conflict.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        repository.write_working_text(conflict.path, conflict.content)


def _resolve_target_ref(repository: Repository, revision: str) -> str | None:
    try:
        commit_id = repository.read_branch(revision)
    except ValueError:
        return None
    if commit_id is not None or repository.layout.branch_path(revision).exists():
        return branch_ref(revision)
    return None


def _current_branch(repository: Repository) -> str:
    branch_name = repository.current_branch_name()
    if branch_name is None:
        raise RuntimeError("HEAD must point to a branch")
    return branch_name


def _ensure_operation_ready(repository: Repository) -> None:
    if repository.current_operation() is not None:
        raise ValueError("another operation is already in progress")
    if not repository.status().is_clean():
        raise ValueError("working tree must be clean before merge")
