from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from lit.config import SafeRollbackPreference, read_lit_config
from lit.domain import (
    ApprovalState,
    OperationKind,
    OperationStatus,
    ProvenanceRecord,
    VerificationRecord,
)
from lit.lineage import LineageService

if TYPE_CHECKING:
    from lit.repository import Repository, TrackedFile


@dataclass(frozen=True)
class MergeResult:
    status: str
    message: str
    commit_id: str | None = None
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class RebaseResult:
    status: str
    message: str
    commit_id: str | None = None
    replayed: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


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


class WorkflowService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.policy = read_lit_config(repository.layout)

    @classmethod
    def open(cls, root: str | Path) -> "WorkflowService":
        from lit.repository import Repository

        return cls(Repository.open(root))

    def safe_rollback_checkpoint_id(self, *, lineage_id: str | None = None) -> str | None:
        preference = self.policy.operations.safe_rollback_preference
        current_lineage = lineage_id or self.repository.current_branch_name()
        if preference is SafeRollbackPreference.LINEAGE:
            return self.repository.latest_safe_checkpoint_id(lineage_id=current_lineage)
        if preference is SafeRollbackPreference.REPOSITORY:
            return self.repository.latest_safe_checkpoint_id()
        return self.repository.latest_safe_checkpoint_id(
            lineage_id=current_lineage
        ) or self.repository.latest_safe_checkpoint_id()

    def create_checkpoint(
        self,
        *,
        revision_id: str,
        name: str | None = None,
        note: str | None = None,
        safe: bool = True,
        pinned: bool = False,
        approval_state: ApprovalState = ApprovalState.NOT_REQUESTED,
        approval_note: str | None = None,
        provenance: ProvenanceRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
    ):
        resolved_revision = self.repository.resolve_revision(revision_id)
        if resolved_revision is None:
            raise ValueError(f"unknown revision: {revision_id}")
        revision = self.repository.get_revision(resolved_revision)
        normalized = self.repository._normalize_provenance(
            provenance,
            origin_commit=revision.provenance.origin_commit or resolved_revision,
            verification_status=revision.provenance.verification_status,
        )
        if safe and self.policy.checkpoints.require_approval_for_safe:
            if approval_state is not ApprovalState.APPROVED:
                raise ValueError("safe checkpoints require approval by policy")
        effective_pinned = pinned or (safe and self.policy.checkpoints.auto_pin_safe)
        from lit.domain import CheckpointRecord
        from lit.storage import write_json
        from lit.transactions import next_identifier, utc_now

        checkpoint = CheckpointRecord(
            checkpoint_id=next_identifier("checkpoint"),
            revision_id=resolved_revision,
            name=name,
            note=note,
            created_at=utc_now(),
            safe=safe,
            pinned=effective_pinned,
            approval_state=approval_state,
            approval_note=approval_note,
            provenance=normalized,
            verification_id=revision.verification_id,
            artifact_ids=artifact_ids,
        )
        write_json(
            self.repository.layout.checkpoint_path(checkpoint.checkpoint_id or ""),
            checkpoint.to_dict(),
        )
        self.repository._append_revision_checkpoint(
            resolved_revision,
            checkpoint.checkpoint_id or "",
        )
        if normalized.lineage_id is not None:
            self.repository._ensure_lineage(
                normalized.lineage_id,
                head_revision=resolved_revision,
                checkpoint_id=checkpoint.checkpoint_id,
            )
        return checkpoint

    def rollback_to_checkpoint(
        self,
        checkpoint_id: str | None = None,
        *,
        use_latest_safe: bool = True,
        lineage_id: str | None = None,
    ):
        scoped_lineage = lineage_id or self.repository.current_branch_name()
        target = (
            self.repository.get_checkpoint(checkpoint_id)
            if checkpoint_id is not None
            else None
        )
        if target is None and use_latest_safe:
            safe_target_id = self.safe_rollback_checkpoint_id(lineage_id=scoped_lineage)
            if safe_target_id is not None:
                target = self.repository.get_checkpoint(safe_target_id)
        if target is None:
            candidates = self.repository.list_checkpoints(lineage_id=scoped_lineage)
            if not candidates and scoped_lineage is not None:
                candidates = self.repository.list_checkpoints()
            if not candidates:
                raise FileNotFoundError("no checkpoints available for rollback")
            target = candidates[-1]
        if target.revision_id is None:
            raise ValueError("no checkpoint available for rollback")
        with self.repository._mutation(
            OperationKind.ROLLBACK.value,
            message=f"rollback to {target.checkpoint_id}",
        ):
            operation = self.repository._begin_operation(
                OperationKind.ROLLBACK,
                message=f"rollback to {target.checkpoint_id}",
                lineage_id=target.provenance.lineage_id,
            )
            try:
                current_commit = self.repository.current_commit_id()
                self.repository.clear_operations()
                self.repository.apply_commit(
                    target.revision_id,
                    baseline_commit=current_commit,
                )
                branch_name = self.repository.current_branch_name()
                if branch_name is not None:
                    self.repository.write_branch(branch_name, target.revision_id)
                else:
                    self.repository.set_head_commit(target.revision_id)
                if target.provenance.lineage_id is not None:
                    self.repository._ensure_lineage(
                        target.provenance.lineage_id,
                        head_revision=target.revision_id,
                    )
            except Exception as error:
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    checkpoint_id=target.checkpoint_id,
                    lineage_id=target.provenance.lineage_id,
                    message=str(error),
                )
                raise
            self.repository._finish_operation(
                operation,
                status=OperationStatus.SUCCEEDED,
                revision_id=target.revision_id,
                checkpoint_id=target.checkpoint_id,
                lineage_id=target.provenance.lineage_id,
            )
            return target

    def merge_revision(self, revision: str) -> MergeResult:
        _ensure_operation_ready(self.repository)
        branch_name = _current_branch(self.repository)
        with self.repository._mutation(
            OperationKind.MERGE.value,
            message=f"merge {revision}",
        ):
            operation = self.repository._begin_operation(
                OperationKind.MERGE,
                message=f"merge {revision}",
                lineage_id=branch_name,
            )
            try:
                current_commit = self.repository.current_commit_id()
                if current_commit is None:
                    raise ValueError(
                        "merge requires at least one commit on the current branch"
                    )

                target_commit = self.repository.resolve_revision(revision)
                if target_commit is None:
                    raise ValueError(f"unknown revision: {revision}")

                if target_commit == current_commit:
                    self.repository._finish_operation(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        revision_id=current_commit,
                        lineage_id=branch_name,
                        message="Already up to date.",
                    )
                    return MergeResult(status="noop", message="Already up to date.")

                base_commit = self.repository.merge_base(current_commit, target_commit)
                if base_commit == target_commit:
                    self.repository._finish_operation(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        revision_id=current_commit,
                        lineage_id=branch_name,
                        message="Already up to date.",
                    )
                    return MergeResult(status="noop", message="Already up to date.")

                target_ref = _resolve_target_ref(self.repository, revision)
                if base_commit == current_commit:
                    self.repository.write_branch(branch_name, target_commit)
                    self.repository.apply_commit(
                        target_commit,
                        baseline_commit=current_commit,
                    )
                    self.repository.clear_merge()
                    self.repository._ensure_lineage(
                        branch_name,
                        head_revision=target_commit,
                    )
                    self.repository._finish_operation(
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

                base_tree = self.repository.read_commit_tree(base_commit)
                current_tree = self.repository.read_commit_tree(current_commit)
                target_tree = self.repository.read_commit_tree(target_commit)
                plan = _merge_trees(
                    self.repository,
                    base_tree,
                    current_tree,
                    target_tree,
                )

                self.repository.apply_tree(plan.files, baseline=current_tree)
                if plan.conflicts:
                    _write_conflicts(self.repository, plan.conflicts)
                    self.repository.begin_merge(
                        base_commit=base_commit or "",
                        current_commit=current_commit,
                        target_commit=target_commit,
                        target_ref=target_ref,
                        conflicts=plan.conflict_paths,
                    )
                    self.repository._finish_operation(
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

                commit_id = self._create_merge_commit(
                    current_commit=current_commit,
                    target_commit=target_commit,
                    revision_label=revision,
                )
                self.repository.apply_commit(commit_id, baseline_commit=current_commit)
                self.repository.clear_merge()
                self.repository._finish_operation(
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
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    lineage_id=branch_name,
                    message=str(error),
                )
                raise

    def continue_merge(self) -> MergeResult:
        if not self.policy.operations.allow_resume:
            raise ValueError("merge resume is disabled by policy")
        state = self.repository.read_merge_state()
        if state is None:
            raise ValueError("No merge in progress.")
        branch_name = _current_branch(self.repository)
        with self.repository._mutation(
            OperationKind.MERGE.value,
            message=f"continue merge {state.target_commit}",
        ):
            operation = self.repository._begin_operation(
                OperationKind.MERGE,
                message=f"continue merge {state.target_commit}",
                lineage_id=branch_name,
            )
            try:
                commit_id = self._create_merge_commit(
                    current_commit=state.current_commit,
                    target_commit=state.target_commit,
                    revision_label=state.target_ref or state.target_commit,
                )
                self.repository.clear_merge()
            except Exception as error:
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    revision_id=state.current_commit,
                    lineage_id=branch_name,
                    message=str(error),
                )
                raise
            self.repository._finish_operation(
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

    def abort_merge(self) -> str:
        state = self.repository.read_merge_state()
        if state is None:
            raise ValueError("No merge in progress.")
        self.repository.apply_commit(
            state.current_commit,
            baseline_commit=self.repository.current_commit_id(),
        )
        self.repository.clear_merge()
        return state.current_commit

    def rebase_onto(self, revision: str) -> RebaseResult:
        _ensure_operation_ready(self.repository)
        branch_name = _current_branch(self.repository)
        with self.repository._mutation(
            OperationKind.REBASE.value,
            message=f"rebase onto {revision}",
        ):
            operation = self.repository._begin_operation(
                OperationKind.REBASE,
                message=f"rebase onto {revision}",
                lineage_id=branch_name,
            )
            try:
                head_commit = self.repository.current_commit_id()
                if head_commit is None:
                    raise ValueError(
                        "rebase requires the current branch to have at least one commit"
                    )

                onto_commit = self.repository.resolve_revision(revision)
                if onto_commit is None:
                    raise ValueError(f"unknown revision: {revision}")
                if onto_commit == head_commit:
                    self.repository._finish_operation(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        revision_id=head_commit,
                        lineage_id=branch_name,
                        message="Already up to date.",
                    )
                    return RebaseResult(status="noop", message="Already up to date.")

                base_commit = self.repository.merge_base(head_commit, onto_commit)
                pending = self.repository.commits_to_replay(head_commit, onto_commit)
                if base_commit == head_commit:
                    self.repository.write_branch(branch_name, onto_commit)
                    self.repository.apply_commit(
                        onto_commit,
                        baseline_commit=head_commit,
                    )
                    self.repository.clear_rebase()
                    self.repository._ensure_lineage(
                        branch_name,
                        head_revision=onto_commit,
                    )
                    self.repository._finish_operation(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        revision_id=onto_commit,
                        lineage_id=branch_name,
                    )
                    return RebaseResult(
                        status="fast_forward",
                        message=f"Rebased by fast-forwarding to {onto_commit[:12]}.",
                        commit_id=onto_commit,
                    )
                if base_commit == onto_commit:
                    self.repository._finish_operation(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        revision_id=head_commit,
                        lineage_id=branch_name,
                        message="Already up to date.",
                    )
                    return RebaseResult(status="noop", message="Already up to date.")

                self.repository.begin_rebase(
                    onto=onto_commit,
                    original_head=head_commit,
                    pending_commits=pending,
                    applied_commits=(),
                )
                return self._continue_rebase_sequence(
                    operation=operation,
                    branch_name=branch_name,
                    revision_label=revision,
                    original_head=head_commit,
                    current_base=onto_commit,
                    pending_commits=pending,
                    applied_commits=(),
                )
            except Exception as error:
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    lineage_id=branch_name,
                    message=str(error),
                )
                raise

    def continue_rebase(self) -> RebaseResult:
        if not self.policy.operations.allow_resume:
            raise ValueError("rebase resume is disabled by policy")
        state = self.repository.read_rebase_state()
        if state is None:
            raise ValueError("No rebase in progress.")
        branch_name = _current_branch(self.repository)
        current_base = state.applied_commits[-1] if state.applied_commits else state.onto
        with self.repository._mutation(
            OperationKind.REBASE.value,
            message=f"continue rebase onto {state.onto}",
        ):
            operation = self.repository._begin_operation(
                OperationKind.REBASE,
                message=f"continue rebase onto {state.onto}",
                lineage_id=branch_name,
            )
            try:
                return self._continue_rebase_sequence(
                    operation=operation,
                    branch_name=branch_name,
                    revision_label=state.onto,
                    original_head=state.original_head,
                    current_base=current_base,
                    pending_commits=state.pending_commits,
                    applied_commits=state.applied_commits,
                    resume_current_commit=state.current_commit,
                )
            except Exception as error:
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    lineage_id=branch_name,
                    message=str(error),
                )
                raise

    def abort_rebase(self) -> str:
        state = self.repository.read_rebase_state()
        if state is None:
            raise ValueError("No rebase in progress.")
        branch_name = self.repository.current_branch_name()
        if branch_name is not None:
            self.repository.write_branch(branch_name, state.original_head)
        self.repository.apply_commit(
            state.original_head,
            baseline_commit=self.repository.current_commit_id(),
        )
        self.repository.clear_rebase()
        return state.original_head

    def resume_operation(self) -> MergeResult | RebaseResult:
        operation = self.repository.current_operation()
        if operation is None:
            raise ValueError("No operation is in progress.")
        if not self.policy.operations.allow_resume:
            raise ValueError("resume is disabled by policy")
        if operation.kind == "merge":
            return self.continue_merge()
        return self.continue_rebase()

    def abort_operation(self) -> str:
        operation = self.repository.current_operation()
        if operation is None:
            raise ValueError("No operation is in progress.")
        if operation.kind == "merge":
            return self.abort_merge()
        return self.abort_rebase()

    def promote_lineage(
        self,
        lineage_id: str,
        *,
        destination_lineage_id: str | None = None,
        expected_head_revision: str | None = None,
        allow_conflicts: bool = False,
    ):
        return LineageService.open(self.repository.root).promote_lineage(
            lineage_id,
            destination_lineage_id=destination_lineage_id,
            expected_head_revision=expected_head_revision,
            allow_conflicts=allow_conflicts,
        )

    def record_verification(
        self,
        *,
        revision_id: str,
        definition_name: str | None = None,
        command: tuple[str, ...] = (),
        allow_cache: bool = True,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        command_identity: str | None = None,
    ) -> VerificationRecord:
        resolved_revision = self.repository.resolve_revision(revision_id)
        if resolved_revision is None:
            raise ValueError(f"unknown revision: {revision_id}")
        revision = self.repository.get_revision(resolved_revision)
        effective_command = command or self.policy.verification.default_command
        effective_definition_name = (
            definition_name or self.policy.verification.default_definition_name
        )
        effective_allow_cache = allow_cache and self.policy.verification.allow_cache
        return self.repository.run_verification(
            owner_kind="revision",
            owner_id=revision.revision_id,
            definition_name=effective_definition_name,
            command=effective_command,
            command_identity=command_identity,
            state_fingerprint=state_fingerprint or revision.tree,
            environment_fingerprint=environment_fingerprint,
            allow_cache=effective_allow_cache,
        )

    def _create_merge_commit(
        self,
        *,
        current_commit: str,
        target_commit: str,
        revision_label: str,
    ) -> str:
        branch_name = _current_branch(self.repository)
        return self.repository.create_revision_from_tree(
            tree=self._materialized_working_tree(),
            parents=(current_commit, target_commit),
            message=f"Merge {revision_label} into {branch_name}",
            provenance=ProvenanceRecord(
                actor_role="merge",
                actor_id="lit",
                lineage_id=branch_name,
                committed_at=None,
                origin_commit=current_commit,
            ),
        )

    def _continue_rebase_sequence(
        self,
        *,
        operation,
        branch_name: str,
        revision_label: str,
        original_head: str,
        current_base: str,
        pending_commits: tuple[str, ...],
        applied_commits: tuple[str, ...],
        resume_current_commit: str | None = None,
    ) -> RebaseResult:
        rewritten = list(applied_commits)
        pending = list(pending_commits)

        if resume_current_commit is not None:
            if not pending or pending[0] != resume_current_commit:
                raise RuntimeError("rebase state is inconsistent with pending commits")
            resumed_record = self.repository.read_commit(resume_current_commit)
            current_base = _rewrite_commit_from_working_tree(
                self.repository,
                source_commit_id=resume_current_commit,
                record=resumed_record,
                parent=current_base,
            )
            rewritten.append(current_base)
            pending = pending[1:]
            self.repository.advance_rebase(
                pending_commits=tuple(pending),
                applied_commits=tuple(rewritten),
            )

        for index, commit_id in enumerate(tuple(pending)):
            record = self.repository.read_commit(commit_id)
            parent_commit = record.primary_parent
            parent_tree = self.repository.read_commit_tree(parent_commit)
            current_tree = self.repository.read_commit_tree(current_base)
            commit_tree = self.repository.read_commit_tree(commit_id)
            plan = _merge_trees(
                self.repository,
                parent_tree,
                current_tree,
                commit_tree,
            )

            self.repository.apply_tree(plan.files, baseline=current_tree)
            if plan.conflicts:
                _write_conflicts(self.repository, plan.conflicts)
                remaining = tuple(pending[index:])
                self.repository.advance_rebase(
                    pending_commits=remaining,
                    applied_commits=tuple(rewritten),
                    current_commit=commit_id,
                    conflicts=plan.conflict_paths,
                )
                self.repository._finish_operation(
                    operation,
                    status=OperationStatus.FAILED,
                    revision_id=current_base,
                    lineage_id=branch_name,
                    message=f"Rebase stopped while replaying {commit_id[:12]}.",
                )
                return RebaseResult(
                    status="conflict",
                    message=f"Rebase stopped while replaying {commit_id[:12]}.",
                    commit_id=current_base,
                    replayed=tuple(rewritten),
                    conflicts=plan.conflict_paths,
                )

            current_base = _rewrite_commit(
                self.repository,
                source_commit_id=commit_id,
                record=record,
                parent=current_base,
                tree=plan,
            )
            rewritten.append(current_base)
            self.repository.apply_commit(
                current_base,
                baseline_commit=record.primary_parent,
            )
            self.repository.advance_rebase(
                pending_commits=tuple(pending[index + 1 :]),
                applied_commits=tuple(rewritten),
            )

        self.repository.clear_rebase()
        self.repository.write_branch(branch_name, current_base)
        self.repository._finish_operation(
            operation,
            status=OperationStatus.SUCCEEDED,
            revision_id=current_base,
            lineage_id=branch_name,
        )
        return RebaseResult(
            status="rebased",
            message=f"Rebased onto {revision_label} at {current_base[:12]}.",
            commit_id=current_base,
            replayed=tuple(rewritten),
        )

    def _materialized_working_tree(self):
        tree = self.repository.working_tree()
        for tracked in tree.values():
            self.repository._store_object(
                "blobs",
                (self.repository.root / tracked.path).read_bytes(),
            )
        return tree


def _rewrite_commit(
    repository: Repository,
    *,
    source_commit_id: str,
    record,
    parent: str,
    tree: MergePlan,
) -> str:
    return repository.create_revision_from_tree(
        tree=tree.files,
        parents=(parent,),
        message=record.message,
        provenance=ProvenanceRecord(
            actor_role="rebase",
            actor_id="lit",
            lineage_id=_current_branch(repository),
            origin_commit=getattr(record.metadata, "origin_commit", None) or source_commit_id,
            rewritten_from=source_commit_id,
        ),
    )


def _rewrite_commit_from_working_tree(
    repository: Repository,
    *,
    source_commit_id: str,
    record,
    parent: str,
) -> str:
    tree = repository.working_tree()
    for tracked in tree.values():
        repository._store_object(
            "blobs",
            (repository.root / tracked.path).read_bytes(),
        )
    return repository.create_revision_from_tree(
        tree=tree,
        parents=(parent,),
        message=record.message,
        provenance=ProvenanceRecord(
            actor_role="rebase",
            actor_id="lit",
            lineage_id=_current_branch(repository),
            origin_commit=getattr(record.metadata, "origin_commit", None) or source_commit_id,
            rewritten_from=source_commit_id,
        ),
    )


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

    path = current_file or target_file or base_file
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
    from lit.refs import branch_ref

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


__all__ = [
    "ConflictFile",
    "MergePlan",
    "MergeResult",
    "RebaseResult",
    "WorkflowService",
]
