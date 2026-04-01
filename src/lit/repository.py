from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from lit.checkpoints import (
    latest_safe_checkpoint as load_latest_safe_checkpoint,
    latest_safe_checkpoint_id as load_latest_safe_checkpoint_id,
    list_checkpoints as load_checkpoint_records,
    load_checkpoint,
    write_checkpoint,
)
from lit.commits import CommitMetadata, CommitRecord, deserialize_commit, serialize_commit
from lit.domain import (
    ApprovalState,
    ArtifactRecord,
    CheckpointRecord,
    LineageRecord,
    OperationKind,
    OperationRecord,
    OperationStatus,
    ProvenanceRecord,
    RevisionRecord,
    VerificationRecord,
    VerificationStatus,
)
from lit.index import IndexEntry, IndexState, read_index
from lit.layout import LitLayout, ObjectKind
from lit.migrations import bootstrap_repository
from lit.refs import (
    branch_name_from_ref,
    branch_ref,
    iter_ref_names,
    normalize_branch_name,
    read_head,
    read_ref,
    write_head,
    write_ref,
)
from lit.state import (
    MergeState,
    OperationState,
    RebaseState,
    active_operation,
    read_merge_state,
    read_rebase_state,
    write_merge_state,
    write_rebase_state,
)
from lit.storage import delete_path, hash_bytes, read_json, write_bytes, write_json
from lit.transactions import JournaledTransaction, next_identifier, utc_now
from lit.trees import TreeEntry, TreeRecord, deserialize_tree, serialize_tree
from lit.working_tree import FileSnapshot, normalize_repo_path, scan_working_tree

RepositoryLayout = LitLayout


@dataclass(frozen=True)
class TrackedFile:
    path: str
    digest: str
    size: int
    executable: bool = False

    @classmethod
    def from_snapshot(cls, snapshot: FileSnapshot) -> "TrackedFile":
        return cls(
            path=snapshot.path,
            digest=snapshot.digest,
            size=snapshot.size,
            executable=snapshot.executable,
        )

    @classmethod
    def from_index_entry(cls, entry: IndexEntry) -> "TrackedFile":
        if entry.digest is None:
            raise ValueError("cannot build a tracked file from a deletion entry")
        return cls(
            path=entry.path,
            digest=entry.digest,
            size=entry.size,
            executable=entry.executable,
        )


@dataclass(frozen=True)
class StatusReport:
    staged_added: tuple[str, ...] = ()
    staged_modified: tuple[str, ...] = ()
    staged_deleted: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    untracked: tuple[str, ...] = ()

    def is_clean(self) -> bool:
        return not any(
            (
                self.staged_added,
                self.staged_modified,
                self.staged_deleted,
                self.modified,
                self.deleted,
                self.untracked,
            )
        )


@dataclass(frozen=True)
class BranchRecord:
    name: str
    ref: str
    commit_id: str | None
    current: bool = False


@dataclass(frozen=True)
class CheckoutRecord:
    revision: str
    commit_id: str | None
    branch_name: str | None
    restored_paths: tuple[str, ...]

    @property
    def detached(self) -> bool:
        return self.branch_name is None


@dataclass(frozen=True)
class RepositoryConfig:
    schema_version: int = 1
    default_branch: str = "main"

    def to_dict(self) -> dict[str, object]:
        return {"default_branch": self.default_branch, "schema_version": self.schema_version}

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "RepositoryConfig":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            default_branch=normalize_branch_name(str(data.get("default_branch", "main"))),
        )


@dataclass
class Repository:
    root: Path
    layout: LitLayout
    config: RepositoryConfig
    recovered_operations: tuple[str, ...] = field(default=(), repr=False)
    _active_transaction: JournaledTransaction | None = field(default=None, init=False, repr=False)
    _transaction_depth: int = field(default=0, init=False, repr=False)

    @classmethod
    def create(cls, root: str | Path, *, default_branch: str = "main") -> "Repository":
        repository_root = Path(root).resolve()
        repository_root.mkdir(parents=True, exist_ok=True)
        layout = LitLayout(repository_root)
        normalized_branch = normalize_branch_name(default_branch)
        if not layout.dot_lit.exists():
            with JournaledTransaction(layout, kind="init", message="initialize repository") as tx:
                for directory in layout.managed_directories():
                    directory.mkdir(parents=True, exist_ok=True)
                write_json(
                    layout.config,
                    RepositoryConfig(default_branch=normalized_branch).to_dict(),
                    mutation=tx,
                )
                write_head(layout.head, branch_ref(normalized_branch), mutation=tx)
                write_json(layout.index, IndexState().to_dict(), mutation=tx)
                write_ref(layout.branch_path(normalized_branch), None, mutation=tx)
                write_json(layout.merge_state, None, mutation=tx)
                write_json(layout.rebase_state, None, mutation=tx)
                now = utc_now()
                write_json(
                    layout.lineage_path(normalized_branch),
                    LineageRecord(
                        lineage_id=normalized_branch,
                        created_at=now,
                        updated_at=now,
                        title=normalized_branch,
                    ).to_dict(),
                    mutation=tx,
                )
        return cls.open(repository_root)

    @classmethod
    def open(cls, root: str | Path) -> "Repository":
        repository_root = Path(root).resolve()
        layout = LitLayout(repository_root)
        if not layout.dot_lit.is_dir():
            raise FileNotFoundError(f"lit repository not found at {layout.dot_lit}")
        recovered = bootstrap_repository(layout)
        config = RepositoryConfig.from_dict(read_json(layout.config, default=None))
        return cls(repository_root, layout, config, recovered_operations=recovered)

    @classmethod
    def discover(cls, start: str | Path) -> "Repository":
        current = Path(start).resolve()
        for candidate in (current, *current.parents):
            if (candidate / ".lit").is_dir():
                return cls.open(candidate)
        raise FileNotFoundError(f"lit repository not found from {current}")

    def repository_handle(self) -> RepositoryHandle:
        from lit.backend_api import RepositoryHandle

        return RepositoryHandle.for_root(
            self.root,
            default_branch=self.config.default_branch,
            current_branch=self.current_branch_name(),
            head_revision=self.current_commit_id(),
            current_lineage_id=self.current_branch_name() or self.config.default_branch,
            latest_safe_checkpoint_id=self.latest_safe_checkpoint_id(),
            is_initialized=True,
        )

    @contextmanager
    def _mutation(self, kind: str, *, message: str | None = None) -> Iterator[JournaledTransaction]:
        if self._active_transaction is not None:
            self._transaction_depth += 1
            try:
                yield self._active_transaction
            finally:
                self._transaction_depth -= 1
            return

        with JournaledTransaction(self.layout, kind=kind, message=message) as transaction:
            self._active_transaction = transaction
            self._transaction_depth = 1
            try:
                yield transaction
            finally:
                self._active_transaction = None
                self._transaction_depth = 0

    def _transaction_writer(self) -> JournaledTransaction | None:
        return self._active_transaction

    def _begin_operation(
        self,
        kind: OperationKind,
        *,
        message: str | None = None,
        lineage_id: str | None = None,
    ) -> OperationRecord:
        transaction = self._active_transaction
        if transaction is None:
            raise RuntimeError("operation tracking requires an active transaction")
        record = OperationRecord(
            operation_id=transaction.operation_id,
            kind=kind,
            status=OperationStatus.RUNNING,
            repository_root=self.root.as_posix(),
            lineage_id=lineage_id,
            journal_path=transaction.journal_path.as_posix(),
            started_at=utc_now(),
            message=message,
        )
        self._write_operation_record(record)
        return record

    def _finish_operation(
        self,
        record: OperationRecord,
        *,
        status: OperationStatus,
        revision_id: str | None = None,
        checkpoint_id: str | None = None,
        verification_id: str | None = None,
        artifact_ids: tuple[str, ...] | None = None,
        lineage_id: str | None = None,
        message: str | None = None,
    ) -> OperationRecord:
        data = record.to_dict()
        data["status"] = status.value
        data["finished_at"] = utc_now()
        data["revision_id"] = revision_id if revision_id is not None else record.revision_id
        data["checkpoint_id"] = checkpoint_id if checkpoint_id is not None else record.checkpoint_id
        data["verification_id"] = verification_id if verification_id is not None else record.verification_id
        data["artifact_ids"] = list(artifact_ids if artifact_ids is not None else record.artifact_ids)
        data["lineage_id"] = lineage_id if lineage_id is not None else record.lineage_id
        data["message"] = message if message is not None else record.message
        updated = OperationRecord.from_dict(data)
        self._write_operation_record(updated)
        return updated

    def _write_operation_record(self, record: OperationRecord) -> None:
        if record.operation_id is None:
            raise ValueError("operation record requires an identifier")
        write_json(self.layout.operation_path(record.operation_id), record.to_dict())

    def _normalize_provenance(
        self,
        provenance: ProvenanceRecord | None,
        *,
        origin_commit: str | None = None,
        rewritten_from: str | None = None,
        promoted_from: str | None = None,
        verification_status: VerificationStatus | None = None,
    ) -> ProvenanceRecord:
        base = provenance or ProvenanceRecord()
        return ProvenanceRecord(
            actor_role=base.actor_role,
            actor_id=base.actor_id,
            prompt_template=base.prompt_template,
            agent_family=base.agent_family,
            run_id=base.run_id,
            block_id=base.block_id,
            step_id=base.step_id,
            lineage_id=base.lineage_id or self.current_branch_name() or self.config.default_branch,
            verification_status=verification_status or base.verification_status,
            verification_summary=base.verification_summary,
            committed_at=base.committed_at or utc_now(),
            origin_commit=base.origin_commit or origin_commit,
            rewritten_from=base.rewritten_from or rewritten_from,
            promoted_from=base.promoted_from or promoted_from,
        )

    def current_head_ref(self) -> str | None:
        head = read_head(self.layout.head)
        if branch_name_from_ref(head) is None:
            return None
        return head

    def set_head_ref(self, ref_name: str) -> None:
        with self._mutation("head", message=f"update HEAD to {ref_name}"):
            write_head(self.layout.head, ref_name, mutation=self._transaction_writer())

    def set_head_commit(self, commit_id: str) -> None:
        with self._mutation("head", message=f"detach HEAD at {commit_id}"):
            write_head(
                self.layout.head,
                commit_id,
                symbolic=False,
                mutation=self._transaction_writer(),
            )

    def current_head_target(self) -> str | None:
        return read_head(self.layout.head)

    def current_branch_name(self) -> str | None:
        return branch_name_from_ref(self.current_head_target())

    def read_branch(self, branch_name: str) -> str | None:
        return read_ref(self.layout.branch_path(branch_name))

    def write_branch(self, branch_name: str, commit_id: str | None) -> None:
        with self._mutation("ref", message=f"update branch {branch_name}"):
            write_ref(
                self.layout.branch_path(branch_name),
                commit_id,
                mutation=self._transaction_writer(),
            )

    def read_index(self) -> IndexState:
        return read_index(self.layout.index)

    def write_index(self, state: IndexState) -> None:
        with self._mutation("index", message="update index"):
            write_json(self.layout.index, state.to_dict(), mutation=self._transaction_writer())

    def read_merge_state(self) -> MergeState | None:
        return read_merge_state(self.layout.merge_state)

    def write_merge_state(self, state: MergeState | None) -> None:
        with self._mutation("merge", message="update merge state"):
            write_merge_state(self.layout.merge_state, state, mutation=self._transaction_writer())

    def read_rebase_state(self) -> RebaseState | None:
        return read_rebase_state(self.layout.rebase_state)

    def write_rebase_state(self, state: RebaseState | None) -> None:
        with self._mutation("rebase", message="update rebase state"):
            write_rebase_state(self.layout.rebase_state, state, mutation=self._transaction_writer())

    def current_operation(self) -> OperationState | None:
        return active_operation(self.read_merge_state(), self.read_rebase_state())

    def store_object(self, kind: ObjectKind, payload: bytes) -> str:
        with self._mutation("object", message=f"store {kind} object"):
            return self._store_object(kind, payload)

    def _store_object(self, kind: ObjectKind, payload: bytes) -> str:
        object_id = hash_bytes(payload)
        path = self.layout.object_path(kind, object_id)
        if not path.exists():
            write_bytes(path, payload, mutation=self._transaction_writer())
        return object_id

    def read_object(self, kind: ObjectKind, object_id: str) -> bytes:
        return self.layout.object_path(kind, object_id).read_bytes()

    def current_commit_id(self) -> str | None:
        head_target = self.current_head_target()
        branch_name = branch_name_from_ref(head_target)
        if branch_name is not None:
            return self.read_branch(branch_name)
        if head_target is not None and self.layout.object_path("commits", head_target).exists():
            return head_target
        return None

    def resolve_branch_name(self, revision: str) -> str | None:
        try:
            normalized = normalize_branch_name(revision)
        except ValueError:
            return None
        if self.layout.branch_path(normalized).exists():
            return normalized
        return None

    def resolve_revision(self, revision: str | None = None) -> str | None:
        if revision in (None, "HEAD"):
            return self.current_commit_id()
        if self.layout.checkpoint_path(revision).exists():
            return self.get_checkpoint(revision).revision_id
        branch_name = self.resolve_branch_name(revision)
        if branch_name is not None:
            return self.read_branch(branch_name)
        if self.layout.object_path("commits", revision).exists():
            return revision
        raise ValueError(f"unknown revision: {revision}")

    def read_commit(self, commit_id: str) -> CommitRecord:
        return deserialize_commit(self.read_object("commits", commit_id))

    def get_revision(self, revision_id: str) -> RevisionRecord:
        path = self.layout.revision_path(revision_id)
        if path.exists():
            record = RevisionRecord.from_dict(read_json(path, default=None))
        else:
            commit = self.read_commit(revision_id)
            record = RevisionRecord(
                revision_id=revision_id,
                tree=commit.tree,
                parents=commit.parents,
                message=commit.message,
                provenance=commit.metadata.to_provenance(),
            )
        if record.revision_id is None:
            data = record.to_dict()
            data["revision_id"] = revision_id
            return RevisionRecord.from_dict(data)
        return record

    def current_revision(self) -> RevisionRecord | None:
        revision_id = self.current_commit_id()
        if revision_id is None:
            return None
        return self.get_revision(revision_id)

    def list_revisions(
        self,
        *,
        start_revision: str | None = None,
        lineage_id: str | None = None,
    ) -> tuple[RevisionRecord, ...]:
        if lineage_id is not None and start_revision is None:
            try:
                start_revision = self.get_lineage(lineage_id).head_revision
            except FileNotFoundError:
                return ()
        history = self.iter_commit_graph(self.resolve_revision(start_revision))
        revisions = [self.get_revision(commit_id) for commit_id, _ in history]
        if lineage_id is None:
            return tuple(revisions)
        return tuple(record for record in revisions if record.provenance.lineage_id == lineage_id)

    def changed_files(
        self,
        revision_id: str | None = None,
        *,
        since_revision: str | None = None,
    ) -> tuple[str, ...]:
        resolved_revision = self.resolve_revision(revision_id)
        if resolved_revision is None:
            return ()
        revision = self.get_revision(resolved_revision)
        baseline = since_revision
        if baseline is None and revision.parents:
            baseline = revision.parents[0]
        resolved_baseline = self.resolve_revision(baseline) if baseline is not None else None
        before = {} if resolved_baseline is None else self.read_commit_tree(resolved_baseline)
        after = self.read_commit_tree(resolved_revision)
        changed: list[str] = []
        for path in sorted(set(before) | set(after)):
            if before.get(path) != after.get(path):
                changed.append(path)
        return tuple(changed)

    def iter_history(self, start_commit: str | None = None) -> tuple[tuple[str, CommitRecord], ...]:
        history: list[tuple[str, CommitRecord]] = []
        commit_id = start_commit if start_commit is not None else self.current_commit_id()
        while commit_id is not None:
            record = self.read_commit(commit_id)
            history.append((commit_id, record))
            commit_id = record.primary_parent
        return tuple(history)

    def iter_commit_graph(
        self,
        start_commit: str | None = None,
    ) -> tuple[tuple[str, CommitRecord], ...]:
        commit_id = start_commit if start_commit is not None else self.current_commit_id()
        if commit_id is None:
            return ()
        seen: set[str] = set()
        ordered: list[tuple[str, CommitRecord]] = []
        stack: list[str] = [commit_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            record = self.read_commit(current)
            ordered.append((current, record))
            for parent in reversed(record.parents):
                if parent not in seen:
                    stack.append(parent)
        return tuple(ordered)

    def ancestor_distances(self, commit_id: str | None) -> dict[str, int]:
        if commit_id is None:
            return {}
        distances: dict[str, int] = {}
        queue: list[tuple[str, int]] = [(commit_id, 0)]
        while queue:
            current, distance = queue.pop(0)
            previous = distances.get(current)
            if previous is not None and previous <= distance:
                continue
            distances[current] = distance
            for parent in self.read_commit(current).parents:
                queue.append((parent, distance + 1))
        return distances

    def is_ancestor(self, ancestor_commit: str | None, descendant_commit: str | None) -> bool:
        if ancestor_commit is None or descendant_commit is None:
            return False
        return ancestor_commit in self.ancestor_distances(descendant_commit)

    def merge_base(self, left_commit: str | None, right_commit: str | None) -> str | None:
        if left_commit is None or right_commit is None:
            return None
        left = self.ancestor_distances(left_commit)
        right = self.ancestor_distances(right_commit)
        common = set(left) & set(right)
        if not common:
            return None
        return min(
            common,
            key=lambda commit_id: (
                left[commit_id] + right[commit_id],
                max(left[commit_id], right[commit_id]),
                commit_id,
            ),
        )

    def first_parent_range(
        self,
        ancestor_commit: str | None,
        descendant_commit: str | None,
    ) -> tuple[str, ...]:
        if descendant_commit is None:
            return ()
        commits: list[str] = []
        current = descendant_commit
        while current is not None and current != ancestor_commit:
            commits.append(current)
            current = self.read_commit(current).primary_parent
        if ancestor_commit is not None and current != ancestor_commit:
            raise ValueError(f"{ancestor_commit} is not on the first-parent chain of {descendant_commit}")
        commits.reverse()
        return tuple(commits)

    def commits_to_replay(self, head_commit: str | None, onto_commit: str | None) -> tuple[str, ...]:
        return self.first_parent_range(self.merge_base(head_commit, onto_commit), head_commit)

    def list_branches(self) -> tuple[BranchRecord, ...]:
        current = self.current_branch_name()
        names = tuple(sorted(iter_ref_names(self.layout.heads)))
        return tuple(
            BranchRecord(name=name, ref=branch_ref(name), commit_id=self.read_branch(name), current=name == current)
            for name in names
        )

    def create_branch(
        self,
        branch_name: str,
        *,
        start_point: str | None = "HEAD",
        force: bool = False,
    ) -> BranchRecord:
        normalized = normalize_branch_name(branch_name)
        with self._mutation("branch", message=f"create branch {normalized}"):
            path = self.layout.branch_path(normalized)
            if path.exists() and not force:
                raise ValueError(f"branch already exists: {normalized}")
            commit_id = self.resolve_revision(start_point)
            write_ref(path, commit_id, mutation=self._transaction_writer())
            self._ensure_lineage(normalized, head_revision=commit_id, forked_from=self.current_branch_name(), title=normalized)
        return BranchRecord(normalized, branch_ref(normalized), commit_id, normalized == self.current_branch_name())

    def begin_merge(
        self,
        *,
        base_commit: str,
        target_commit: str,
        current_commit: str | None = None,
        target_ref: str | None = None,
        conflicts: tuple[str, ...] = (),
    ) -> MergeState:
        with self._mutation("merge", message="begin merge"):
            head_ref = self.current_head_ref()
            if head_ref is None:
                raise RuntimeError("merge state requires HEAD to point to a branch")
            state = MergeState(head_ref, base_commit, current_commit or self.current_commit_id() or "", target_commit, target_ref, tuple(sorted(set(conflicts))))
            write_merge_state(self.layout.merge_state, state, mutation=self._transaction_writer())
            return state

    def clear_merge(self) -> None:
        self.write_merge_state(None)

    def begin_rebase(
        self,
        *,
        onto: str,
        original_head: str | None = None,
        pending_commits: tuple[str, ...] = (),
        applied_commits: tuple[str, ...] = (),
        current_commit: str | None = None,
        conflicts: tuple[str, ...] = (),
    ) -> RebaseState:
        with self._mutation("rebase", message="begin rebase"):
            head_ref = self.current_head_ref()
            resolved_head = original_head or self.current_commit_id()
            if head_ref is None or resolved_head is None:
                raise RuntimeError("rebase state requires a current branch and commit")
            state = RebaseState(head_ref, resolved_head, onto, tuple(pending_commits), tuple(applied_commits), current_commit, tuple(sorted(set(conflicts))))
            write_rebase_state(self.layout.rebase_state, state, mutation=self._transaction_writer())
            return state

    def advance_rebase(
        self,
        *,
        pending_commits: tuple[str, ...],
        applied_commits: tuple[str, ...],
        current_commit: str | None = None,
        conflicts: tuple[str, ...] = (),
    ) -> RebaseState:
        with self._mutation("rebase", message="advance rebase"):
            state = self.read_rebase_state()
            if state is None:
                raise RuntimeError("no rebase is in progress")
            updated = RebaseState(state.head_ref, state.original_head, state.onto, tuple(pending_commits), tuple(applied_commits), current_commit, tuple(sorted(set(conflicts))))
            write_rebase_state(self.layout.rebase_state, updated, mutation=self._transaction_writer())
            return updated

    def clear_rebase(self) -> None:
        self.write_rebase_state(None)

    def clear_operations(self) -> None:
        with self._mutation("operations", message="clear operation state"):
            write_merge_state(self.layout.merge_state, None, mutation=self._transaction_writer())
            write_rebase_state(self.layout.rebase_state, None, mutation=self._transaction_writer())

    def working_tree(self) -> dict[str, TrackedFile]:
        return {snapshot.path: TrackedFile.from_snapshot(snapshot) for snapshot in scan_working_tree(self.root)}

    def get_revision(self, revision_id: str) -> RevisionRecord:
        path = self.layout.revision_path(revision_id)
        if path.exists():
            record = RevisionRecord.from_dict(read_json(path, default=None))
        else:
            commit = self.read_commit(revision_id)
            record = RevisionRecord(
                revision_id=revision_id,
                tree=commit.tree,
                parents=commit.parents,
                message=commit.message,
                provenance=commit.metadata.to_provenance(),
            )
        if record.revision_id is None:
            data = record.to_dict()
            data["revision_id"] = revision_id
            return RevisionRecord.from_dict(data)
        return record

    def list_revisions(
        self,
        *,
        start_revision: str | None = None,
        lineage_id: str | None = None,
    ) -> tuple[RevisionRecord, ...]:
        if lineage_id is not None and start_revision is None:
            try:
                start_revision = self.get_lineage(lineage_id).head_revision
            except FileNotFoundError:
                return ()
        history = self.iter_commit_graph(self.resolve_revision(start_revision))
        revisions = [self.get_revision(commit_id) for commit_id, _ in history]
        if lineage_id is None:
            return tuple(revisions)
        return tuple(record for record in revisions if record.provenance.lineage_id == lineage_id)

    def stage(self, paths: tuple[str | Path, ...] | list[str | Path]) -> tuple[IndexEntry, ...]:
        candidate_paths = tuple(paths)
        if not candidate_paths:
            raise ValueError("at least one path is required")

        with self._mutation("stage", message="stage paths"):
            existing_index = {entry.path: entry for entry in self.read_index().entries}
            head_files = self.read_commit_tree(self.current_commit_id())
            working_files = self.working_tree()
            staged_updates: dict[str, IndexEntry] = {}

            for raw_path in candidate_paths:
                resolved = (self.root / raw_path).resolve()
                if not resolved.exists():
                    repo_path = normalize_repo_path(Path(raw_path))
                    if repo_path in head_files or repo_path in working_files or repo_path in existing_index:
                        staged_updates[repo_path] = IndexEntry.deletion(repo_path)
                        continue
                if resolved.is_file():
                    snapshot = working_files.get(normalize_repo_path(resolved.relative_to(self.root)))
                    if snapshot is None:
                        raise FileNotFoundError(f"path not found: {raw_path}")
                    self._store_object("blobs", (self.root / snapshot.path).read_bytes())
                    staged_updates[snapshot.path] = IndexEntry(snapshot.path, snapshot.digest, snapshot.size, snapshot.executable)
                    continue
                if resolved.is_dir():
                    prefix = normalize_repo_path(resolved.relative_to(self.root))
                    prefix = "" if prefix == "." else prefix
                    for path, snapshot in working_files.items():
                        if prefix and not path.startswith(f"{prefix}/") and path != prefix:
                            continue
                        self._store_object("blobs", (self.root / path).read_bytes())
                        staged_updates[path] = IndexEntry(path, snapshot.digest, snapshot.size, snapshot.executable)
                    tracked_prefix = f"{prefix}/" if prefix else ""
                    tracked_paths = set(head_files) | set(existing_index)
                    for tracked_path in tracked_paths:
                        if prefix and tracked_path != prefix and not tracked_path.startswith(tracked_prefix):
                            continue
                        if tracked_path not in working_files:
                            staged_updates[tracked_path] = IndexEntry.deletion(tracked_path)
                    continue
                raise FileNotFoundError(f"path not found: {raw_path}")

            updated_entries = dict(existing_index)
            updated_entries.update(staged_updates)
            write_json(
                self.layout.index,
                IndexState(tuple(sorted(updated_entries.values(), key=lambda entry: entry.path))).to_dict(),
                mutation=self._transaction_writer(),
            )
            return tuple(sorted(staged_updates.values(), key=lambda entry: entry.path))

    def create_revision(
        self,
        *,
        message: str,
        tree: str | Mapping[str, TrackedFile] | None = None,
        parents: tuple[str, ...] = (),
        provenance: ProvenanceRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
    ) -> OperationRecord:
        normalized = self._normalize_provenance(provenance)
        with self._mutation(OperationKind.COMMIT.value, message=message):
            operation = self._begin_operation(OperationKind.COMMIT, message=message, lineage_id=normalized.lineage_id)
            try:
                commit_id = self._create_revision_commit(
                    message=message,
                    tree=tree,
                    parents=parents,
                    provenance=normalized,
                    artifact_ids=artifact_ids,
                )
            except Exception as error:
                self._finish_operation(operation, status=OperationStatus.FAILED, lineage_id=normalized.lineage_id, message=str(error))
                raise
            return self._finish_operation(
                operation,
                status=OperationStatus.SUCCEEDED,
                revision_id=commit_id,
                artifact_ids=artifact_ids,
                lineage_id=normalized.lineage_id,
            )

    def _create_revision_commit(
        self,
        *,
        message: str,
        tree: str | Mapping[str, TrackedFile] | None,
        parents: tuple[str, ...],
        provenance: ProvenanceRecord,
        artifact_ids: tuple[str, ...] = (),
    ) -> str:
        head_commit = self.current_commit_id()
        if tree is None:
            index_state = self.read_index()
            if not index_state.entries:
                raise ValueError("nothing staged for commit")
            tracked_files = self.read_commit_tree(head_commit)
            for entry in index_state.entries:
                if entry.kind == "delete":
                    tracked_files.pop(entry.path, None)
                else:
                    tracked_files[entry.path] = TrackedFile.from_index_entry(entry)
            tree_id = self._store_tree(tracked_files)
        elif isinstance(tree, str):
            tree_id = tree
        else:
            tree_id = self._store_tree(tree)

        resolved_parents = tuple(parents) if parents else (() if head_commit is None else (head_commit,))
        commit_id = self._persist_revision(tree_id=tree_id, parents=resolved_parents, message=message, provenance=provenance, artifact_ids=artifact_ids)
        branch_name = self.current_branch_name()
        if branch_name is None:
            write_head(self.layout.head, commit_id, symbolic=False, mutation=self._transaction_writer())
        else:
            write_ref(self.layout.branch_path(branch_name), commit_id, mutation=self._transaction_writer())
        write_json(self.layout.index, IndexState().to_dict(), mutation=self._transaction_writer())
        return commit_id

    def commit(
        self,
        message: str,
        *,
        parents: tuple[str, ...] | None = None,
        provenance: ProvenanceRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
    ) -> str:
        operation = self.create_revision(
            message=message,
            parents=tuple(parents) if parents is not None else (),
            provenance=provenance,
            artifact_ids=artifact_ids,
        )
        if operation.revision_id is None:
            raise RuntimeError("commit operation did not produce a revision")
        return operation.revision_id

    def create_revision_from_tree(
        self,
        *,
        tree: Mapping[str, TrackedFile],
        parents: tuple[str, ...],
        message: str,
        provenance: ProvenanceRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
    ) -> str:
        return self._create_revision_commit(
            message=message,
            tree=tree,
            parents=parents,
            provenance=self._normalize_provenance(provenance),
            artifact_ids=artifact_ids,
        )

    def _persist_revision(
        self,
        *,
        tree_id: str,
        parents: tuple[str, ...],
        message: str,
        provenance: ProvenanceRecord,
        artifact_ids: tuple[str, ...] = (),
        verification_id: str | None = None,
        checkpoint_ids: tuple[str, ...] = (),
    ) -> str:
        commit_id = self._store_object(
            "commits",
            serialize_commit(CommitRecord(tree_id, parents, message, CommitMetadata.from_provenance(provenance))),
        )
        revision = RevisionRecord(
            revision_id=commit_id,
            tree=tree_id,
            parents=parents,
            message=message,
            provenance=provenance,
            verification_id=verification_id,
            artifact_ids=artifact_ids,
            checkpoint_ids=checkpoint_ids,
        )
        write_json(self.layout.revision_path(commit_id), revision.to_dict(), mutation=self._transaction_writer())
        if provenance.lineage_id is not None:
            self._ensure_lineage(provenance.lineage_id, head_revision=commit_id)
        return commit_id

    def read_tree(self, tree_id: str) -> dict[str, TrackedFile]:
        files: dict[str, TrackedFile] = {}
        self._populate_tree(tree_id, Path(), files)
        return dict(sorted(files.items()))

    def read_commit_tree(self, commit_id: str | None) -> dict[str, TrackedFile]:
        if commit_id is None:
            return {}
        return self.read_tree(self.read_commit(commit_id).tree)

    def working_tree(self) -> dict[str, TrackedFile]:
        return {
            snapshot.path: TrackedFile.from_snapshot(snapshot)
            for snapshot in scan_working_tree(self.root)
        }

    def stage(self, paths: Iterable[str | Path]) -> tuple[IndexEntry, ...]:
        candidate_paths = tuple(paths)
        if not candidate_paths:
            raise ValueError("at least one path is required")

        existing_index = {entry.path: entry for entry in self.read_index().entries}
        head_files = self.read_commit_tree(self.current_commit_id())
        working_files = self.working_tree()
        staged_updates: dict[str, IndexEntry] = {}

        for raw_path in candidate_paths:
            resolved = (self.root / raw_path).resolve()
            if not resolved.exists():
                repo_path = normalize_repo_path(Path(raw_path))
                if repo_path in head_files or repo_path in working_files or repo_path in existing_index:
                    staged_updates[repo_path] = IndexEntry.deletion(repo_path)
                    continue
            if resolved.is_file():
                snapshot = working_files.get(normalize_repo_path(resolved.relative_to(self.root)))
                if snapshot is None:
                    raise FileNotFoundError(f"path not found: {raw_path}")
                self.store_object("blobs", (self.root / snapshot.path).read_bytes())
                staged_updates[snapshot.path] = IndexEntry(
                    path=snapshot.path,
                    digest=snapshot.digest,
                    size=snapshot.size,
                    executable=snapshot.executable,
                )
                continue
            if resolved.is_dir():
                prefix = normalize_repo_path(resolved.relative_to(self.root))
                prefix = "" if prefix == "." else prefix
                for path, snapshot in working_files.items():
                    if prefix and not path.startswith(f"{prefix}/") and path != prefix:
                        continue
                    self.store_object("blobs", (self.root / path).read_bytes())
                    staged_updates[path] = IndexEntry(
                        path=path,
                        digest=snapshot.digest,
                        size=snapshot.size,
                        executable=snapshot.executable,
                    )
                tracked_prefix = f"{prefix}/" if prefix else ""
                tracked_paths = set(head_files) | set(existing_index)
                for tracked_path in tracked_paths:
                    if prefix and tracked_path != prefix and not tracked_path.startswith(tracked_prefix):
                        continue
                    if tracked_path not in working_files:
                        staged_updates[tracked_path] = IndexEntry.deletion(tracked_path)
                continue
            raise FileNotFoundError(f"path not found: {raw_path}")

        updated_entries = dict(existing_index)
        updated_entries.update(staged_updates)
        index_state = IndexState(entries=tuple(sorted(updated_entries.values(), key=lambda entry: entry.path)))
        self.write_index(index_state)
        return tuple(sorted(staged_updates.values(), key=lambda entry: entry.path))

    def commit(
        self,
        message: str,
        *,
        parents: Iterable[str] | None = None,
        provenance: ProvenanceRecord | None = None,
        artifact_ids: tuple[str, ...] = (),
    ) -> str:
        index_state = self.read_index()
        if not index_state.entries:
            raise ValueError("nothing staged for commit")

        head_commit = self.current_commit_id()
        tracked_files = self.read_commit_tree(head_commit)
        for entry in index_state.entries:
            if entry.kind == "delete":
                tracked_files.pop(entry.path, None)
                continue
            tracked_files[entry.path] = TrackedFile.from_index_entry(entry)

        tree_id = self._store_tree(tracked_files)
        resolved_parents = tuple(parents) if parents is not None else (() if head_commit is None else (head_commit,))
        normalized = self._normalize_provenance(provenance)
        record = CommitRecord(
            tree=tree_id,
            parents=resolved_parents,
            message=message,
            metadata=CommitMetadata.from_provenance(normalized),
        )
        commit_id = self.store_object("commits", serialize_commit(record))
        write_json(
            self.layout.revision_path(commit_id),
            RevisionRecord(
                revision_id=commit_id,
                tree=tree_id,
                parents=resolved_parents,
                message=message,
                provenance=normalized,
                artifact_ids=artifact_ids,
            ).to_dict(),
        )

        branch_name = self.current_branch_name()
        if branch_name is None:
            raise RuntimeError("commits require HEAD to point to a branch")
        self.write_branch(branch_name, commit_id)
        self.write_index(IndexState())
        if normalized.lineage_id is not None:
            self._ensure_lineage(normalized.lineage_id, head_revision=commit_id)
        return commit_id

    def list_checkpoints(
        self,
        *,
        lineage_id: str | None = None,
        only_safe: bool = False,
    ) -> tuple[CheckpointRecord, ...]:
        if not self.layout.checkpoints.exists():
            return ()
        checkpoints = [
            CheckpointRecord.from_dict(read_json(path, default=None))
            for path in sorted(self.layout.checkpoints.glob("*.json"))
        ]
        if lineage_id is not None:
            checkpoints = [
                checkpoint
                for checkpoint in checkpoints
                if checkpoint.provenance.lineage_id == lineage_id
            ]
        if only_safe:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.safe]
        checkpoints.sort(
            key=lambda checkpoint: (
                checkpoint.created_at or "",
                checkpoint.checkpoint_id or "",
            )
        )
        return tuple(checkpoints)

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointRecord:
        path = self.layout.checkpoint_path(checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"checkpoint not found: {checkpoint_id}")
        return CheckpointRecord.from_dict(read_json(path, default=None))

    def latest_safe_checkpoint_id(self, *, lineage_id: str | None = None) -> str | None:
        safe = self.list_checkpoints(lineage_id=lineage_id, only_safe=True)
        return None if not safe else safe[-1].checkpoint_id

    def latest_safe_checkpoint(self, *, lineage_id: str | None = None) -> CheckpointRecord | None:
        checkpoint_id = self.latest_safe_checkpoint_id(lineage_id=lineage_id)
        return None if checkpoint_id is None else self.get_checkpoint(checkpoint_id)

    def rollback_to_checkpoint(
        self,
        checkpoint_id: str | None = None,
        *,
        use_latest_safe: bool = True,
        lineage_id: str | None = None,
    ) -> CheckpointRecord:
        scoped_lineage = lineage_id or self.current_branch_name()
        checkpoint: CheckpointRecord | None = None
        if checkpoint_id is not None:
            checkpoint = self.get_checkpoint(checkpoint_id)
        elif use_latest_safe:
            checkpoint = self.latest_safe_checkpoint(lineage_id=scoped_lineage)
            if checkpoint is None and scoped_lineage is not None:
                checkpoint = self.latest_safe_checkpoint()
        if checkpoint is None:
            candidates = self.list_checkpoints(lineage_id=scoped_lineage)
            if not candidates and scoped_lineage is not None:
                candidates = self.list_checkpoints()
            if not candidates:
                raise FileNotFoundError("no checkpoints available for rollback")
            checkpoint = candidates[-1]
        target_revision = self.resolve_revision(checkpoint.revision_id)
        if target_revision is None:
            raise FileNotFoundError(
                f"checkpoint {checkpoint.checkpoint_id} points to an unknown revision"
            )
        current_commit = self.current_commit_id()
        self._ensure_checkout_safe(target_revision, baseline_commit=current_commit)
        self.apply_commit(target_revision, baseline_commit=current_commit)
        branch_name = self.current_branch_name()
        if branch_name is not None:
            self.write_branch(branch_name, target_revision)
        else:
            self.set_head_commit(target_revision)
        lineage_target = scoped_lineage or checkpoint.provenance.lineage_id
        if lineage_target is not None:
            self._ensure_lineage(
                lineage_target,
                head_revision=target_revision,
                checkpoint_id=checkpoint.checkpoint_id,
            )
        return checkpoint

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
    ) -> CheckpointRecord:
        resolved_revision = self.resolve_revision(revision_id)
        if resolved_revision is None:
            raise ValueError(f"unknown revision: {revision_id}")
        revision = self.get_revision(resolved_revision)
        normalized = self._normalize_provenance(
            provenance,
            fallback=revision.provenance,
        )
        checkpoint = CheckpointRecord(
            checkpoint_id=next_identifier("checkpoint"),
            revision_id=resolved_revision,
            name=name,
            note=note,
            created_at=utc_now(),
            safe=safe,
            pinned=pinned,
            approval_state=approval_state,
            approval_note=approval_note,
            provenance=normalized,
            verification_id=revision.verification_id,
            artifact_ids=artifact_ids,
        )
        write_json(self.layout.checkpoint_path(checkpoint.checkpoint_id or ""), checkpoint.to_dict())
        self._append_revision_checkpoint(resolved_revision, checkpoint.checkpoint_id or "")
        if normalized.lineage_id is not None:
            self._ensure_lineage(
                normalized.lineage_id,
                head_revision=resolved_revision,
                checkpoint_id=checkpoint.checkpoint_id,
            )
        return checkpoint

    def list_lineages(self) -> tuple[LineageRecord, ...]:
        if not self.layout.lineages.exists():
            return ()
        records = [
            LineageRecord.from_dict(read_json(path, default=None))
            for path in sorted(self.layout.lineages.glob("*.json"))
        ]
        records.sort(key=lambda record: (record.created_at or "", record.lineage_id))
        return tuple(records)

    def get_lineage(self, lineage_id: str) -> LineageRecord:
        path = self.layout.lineage_path(normalize_branch_name(lineage_id))
        if not path.exists():
            raise FileNotFoundError(f"lineage not found: {lineage_id}")
        return LineageRecord.from_dict(read_json(path, default=None))

    def list_managed_lineages(self, *, include_inactive: bool = True) -> tuple[object, ...]:
        from lit.lineage import LineageService

        return LineageService.open(self.root).list_lineages(include_inactive=include_inactive)

    def get_managed_lineage(self, lineage_id: str) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).get_lineage(lineage_id)

    def create_lineage(
        self,
        lineage_id: str,
        *,
        forked_from: str | None = None,
        base_checkpoint_id: str | None = None,
        owned_paths: tuple[str | Path, ...] = (),
        allow_owned_path_overlap_with: tuple[str, ...] = (),
        title: str = "",
        description: str = "",
    ) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).create_lineage(
            lineage_id,
            forked_from=forked_from,
            base_checkpoint_id=base_checkpoint_id,
            owned_paths=owned_paths,
            allow_owned_path_overlap_with=allow_owned_path_overlap_with,
            title=title,
            description=description,
        )

    def switch_lineage(self, lineage_id: str) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).switch_lineage(lineage_id)

    def preview_promotion_conflicts(
        self,
        lineage_id: str,
        destination_lineage_id: str | None = None,
    ) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).preview_promotion_conflicts(
            lineage_id,
            destination_lineage_id,
        )

    def promote_lineage(
        self,
        lineage_id: str,
        *,
        destination_lineage_id: str | None = None,
        expected_head_revision: str | None = None,
        allow_conflicts: bool = False,
    ) -> object:
        from lit.workflows import WorkflowService

        return WorkflowService(self).promote_lineage(
            lineage_id,
            destination_lineage_id=destination_lineage_id,
            expected_head_revision=expected_head_revision,
            allow_conflicts=allow_conflicts,
        )

    def discard_lineage(self, lineage_id: str) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).discard_lineage(lineage_id)

    def validate_ownership(self, paths: Iterable[str | Path]) -> None:
        from lit.lineage import LineageService

        current_lineage = self.current_branch_name()
        if current_lineage is None:
            return
        LineageService.open(self.root).validate_ownership(current_lineage, paths)

    def list_workspaces(self) -> tuple[object, ...]:
        from lit.lineage import LineageService

        return LineageService.open(self.root).list_workspaces()

    def inspect_workspaces(self) -> tuple[object, ...]:
        from lit.lineage import LineageService

        return LineageService.open(self.root).inspect_workspaces()

    def get_workspace(self, workspace_id: str) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).get_workspace(workspace_id)

    def create_workspace(
        self,
        lineage_id: str,
        workspace_root: str | Path,
        *,
        workspace_id: str | None = None,
    ) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).create_workspace(
            lineage_id,
            workspace_root,
            workspace_id=workspace_id,
        )

    def attach_workspace(self, lineage_id: str, workspace_id: str) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).attach_workspace(lineage_id, workspace_id)

    def gc_workspaces(self) -> object:
        from lit.lineage import LineageService

        return LineageService.open(self.root).gc_workspaces()

    def list_verifications(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[object, ...]:
        from lit.verification import VerificationRecordStore

        return VerificationRecordStore(self.layout).list_records(
            owner_kind=owner_kind,
            owner_id=owner_id,
        )

    def get_verification(self, verification_id: str) -> object:
        from lit.verification import VerificationRecordStore

        return VerificationRecordStore(self.layout).get_record(verification_id)

    def verification_status(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        linked_verification_id: str | None = None,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        command_identity: str | None = None,
    ) -> object:
        from lit.verification import (
            VerificationCacheService,
            VerificationRecordStore,
            VerificationSummaryService,
        )

        store = VerificationRecordStore(self.layout)
        cache = VerificationCacheService(store)
        summary = VerificationSummaryService(store, cache)
        return summary.summarize_owner(
            owner_kind=owner_kind,
            owner_id=owner_id,
            linked_verification_id=linked_verification_id,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        )

    def run_verification(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        definition_name: str | None = None,
        command: tuple[str, ...] = (),
        command_identity: str | None = None,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        allow_cache: bool = True,
    ) -> object:
        from lit.verification import (
            VerificationCacheService,
            VerificationRecordStore,
            VerificationRunService,
        )

        store = VerificationRecordStore(self.layout)
        cache = VerificationCacheService(store)
        service = VerificationRunService(
            self.layout,
            records=store,
            cache=cache,
        )
        record = service.verify(
            owner_kind=owner_kind,
            owner_id=owner_id,
            definition_name=definition_name,
            command=command,
            command_identity=command_identity,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            allow_cache=allow_cache,
        )
        if record.verification_id is None:
            return record
        if owner_kind == "revision" and owner_id is not None:
            self._attach_revision_verification(owner_id, record.verification_id)
        elif owner_kind == "checkpoint" and owner_id is not None:
            self._attach_checkpoint_verification(owner_id, record.verification_id)
        return record

    def list_artifact_manifests(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[object, ...]:
        from lit.artifact_store import ArtifactStore

        return ArtifactStore().list_manifests(
            self.root,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )

    def get_artifact_manifest(self, artifact_id: str) -> object:
        from lit.artifact_store import ArtifactStore

        return ArtifactStore().read_manifest(self.root, artifact_id)

    def list_artifacts(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[object, ...]:
        return tuple(
            manifest.to_record()
            for manifest in self.list_artifact_manifests(
                owner_kind=owner_kind,
                owner_id=owner_id,
            )
        )

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        return self.get_artifact_manifest(artifact_id).to_record()

    def link_artifact(
        self,
        artifact_id: str,
        *,
        owner_kind: str,
        owner_id: str,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> object:
        from lit.artifact_store import ArtifactStore

        return ArtifactStore().link_artifact_to_owner(
            self.root,
            artifact_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            relationship=relationship,
            note=note,
            pinned=pinned,
        )

    def status(self) -> StatusReport:
        head_files = self.read_commit_tree(self.current_commit_id())
        index_entries = {entry.path: entry for entry in self.read_index().entries}
        working_files = self.working_tree()

        staged_added: list[str] = []
        staged_modified: list[str] = []
        staged_deleted: list[str] = []
        for path, entry in sorted(index_entries.items()):
            head_file = head_files.get(path)
            if entry.kind == "delete":
                staged_deleted.append(path)
            elif head_file is None:
                staged_added.append(path)
            elif entry.digest != head_file.digest or entry.executable != head_file.executable:
                staged_modified.append(path)

        modified: list[str] = []
        deleted: list[str] = []
        for path in sorted(set(head_files) | set(index_entries)):
            entry = index_entries.get(path)
            working_file = working_files.get(path)
            if entry is not None and entry.kind == "delete":
                if working_file is not None:
                    modified.append(path)
                continue
            baseline = TrackedFile.from_index_entry(entry) if entry is not None and entry.kind == "blob" else head_files.get(path)
            if baseline is None:
                continue
            if working_file is None:
                deleted.append(path)
            elif working_file.digest != baseline.digest or working_file.executable != baseline.executable:
                modified.append(path)

        untracked = tuple(path for path in sorted(working_files) if path not in head_files and path not in index_entries)
        return StatusReport(tuple(staged_added), tuple(staged_modified), tuple(staged_deleted), tuple(modified), tuple(deleted), untracked)

    def diff(self) -> str:
        from difflib import unified_diff

        head_files = self.read_commit_tree(self.current_commit_id())
        working_files = self.working_tree()
        chunks: list[str] = []
        for path in sorted(set(head_files) | set(working_files)):
            head_file = head_files.get(path)
            working_file = working_files.get(path)
            if head_file is not None and working_file is not None and head_file.digest == working_file.digest and head_file.executable == working_file.executable:
                continue
            before = [] if head_file is None else self._read_blob_text(head_file.digest)
            after = [] if working_file is None else self._read_file_text(path)
            diff_lines = list(unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
            if diff_lines:
                chunks.append("\n".join(diff_lines))
        return "\n\n".join(chunks)

    def apply_commit(
        self,
        commit_id: str | None,
        *,
        paths: tuple[str | Path, ...] | None = None,
        baseline_commit: str | None = None,
        clear_index: bool = True,
    ) -> tuple[str, ...]:
        return self.apply_tree(
            self.read_commit_tree(commit_id),
            paths=paths,
            baseline=self.read_commit_tree(self.current_commit_id() if baseline_commit is None else baseline_commit),
            clear_index=clear_index,
        )

    def apply_tree(
        self,
        tracked_files: Mapping[str, TrackedFile],
        *,
        paths: tuple[str | Path, ...] | None = None,
        baseline: Mapping[str, TrackedFile] | None = None,
        clear_index: bool = True,
    ) -> tuple[str, ...]:
        with self._mutation("working-tree", message="apply tree"):
            requested_paths = tuple(paths or ())
            baseline_files = baseline or {}
            if not requested_paths:
                selected_source_paths = set(tracked_files)
                selected_baseline_paths = set(baseline_files)
            else:
                selected_source_paths = self._select_tree_paths(tracked_files, requested_paths)
                selected_baseline_paths = self._select_tree_paths(baseline_files, requested_paths)

            for path in sorted(selected_baseline_paths - selected_source_paths):
                target = self.root / path
                if target.exists():
                    delete_path(target, mutation=self._transaction_writer())
                    self._prune_empty_directories(target.parent)

            for path in sorted(selected_source_paths):
                self._write_working_file(path, tracked_files[path])

            if clear_index:
                self._clear_index_entries(requested_paths)
            return tuple(sorted(selected_source_paths | selected_baseline_paths))

    def restore(self, paths: tuple[str | Path, ...] | list[str | Path] | None = None, *, source: str | None = None) -> tuple[str, ...]:
        return self.apply_commit(self.resolve_revision(source), paths=tuple(paths or ()), baseline_commit=self.current_commit_id(), clear_index=True)

    def checkout(self, revision: str) -> CheckoutRecord:
        with self._mutation("checkout", message=f"checkout {revision}"):
            operation = self.current_operation()
            if operation is not None:
                raise RuntimeError(f"cannot checkout while a {operation.kind} is in progress")
            target_branch = self.resolve_branch_name(revision)
            target_commit = self.resolve_revision(revision)
            current_commit = self.current_commit_id()
            self._ensure_checkout_safe(target_commit, baseline_commit=current_commit)
            restored_paths = self.apply_commit(target_commit, baseline_commit=current_commit)
            if target_branch is not None:
                write_head(self.layout.head, branch_ref(target_branch), mutation=self._transaction_writer())
            elif target_commit is not None:
                write_head(self.layout.head, target_commit, symbolic=False, mutation=self._transaction_writer())
            else:
                raise RuntimeError(f"cannot detach HEAD at unresolved revision: {revision}")
            return CheckoutRecord(revision, target_commit, target_branch, restored_paths)

    def list_checkpoints(
        self,
        *,
        lineage_id: str | None = None,
        only_safe: bool = False,
    ) -> tuple[CheckpointRecord, ...]:
        checkpoints = list(load_checkpoint_records(self.layout))
        if lineage_id is not None:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.provenance.lineage_id == lineage_id]
        if only_safe:
            checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.safe]
        return tuple(checkpoints)

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointRecord:
        return load_checkpoint(self.layout, checkpoint_id)

    def latest_safe_checkpoint_id(self, *, lineage_id: str | None = None) -> str | None:
        if lineage_id is None:
            return load_latest_safe_checkpoint_id(self.layout)
        safe = sorted(
            self.list_checkpoints(lineage_id=lineage_id, only_safe=True),
            key=lambda checkpoint: (checkpoint.created_at or "", checkpoint.checkpoint_id or ""),
        )
        return None if not safe else safe[-1].checkpoint_id

    def latest_safe_checkpoint(self, *, lineage_id: str | None = None) -> CheckpointRecord | None:
        if lineage_id is None:
            return load_latest_safe_checkpoint(self.layout)
        checkpoint_id = self.latest_safe_checkpoint_id(lineage_id=lineage_id)
        return None if checkpoint_id is None else self.get_checkpoint(checkpoint_id)

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
    ) -> CheckpointRecord:
        from lit.workflows import WorkflowService

        return WorkflowService(self).create_checkpoint(
            revision_id=revision_id,
            name=name,
            note=note,
            safe=safe,
            pinned=pinned,
            approval_state=approval_state,
            approval_note=approval_note,
            provenance=provenance,
            artifact_ids=artifact_ids,
        )

    def update_checkpoint(
        self,
        checkpoint_id: str,
        *,
        safe: bool | None = None,
        pinned: bool | None = None,
        approval_state: ApprovalState | None = None,
        approval_note: str | None = None,
        note: str | None = None,
        name: str | None = None,
    ) -> CheckpointRecord:
        existing = self.get_checkpoint(checkpoint_id)
        with self._mutation("checkpoint", message=f"update checkpoint {checkpoint_id}"):
            updated = CheckpointRecord(
                checkpoint_id=existing.checkpoint_id,
                revision_id=existing.revision_id,
                name=existing.name if name is None else name,
                note=existing.note if note is None else note,
                created_at=existing.created_at,
                safe=existing.safe if safe is None else safe,
                pinned=existing.pinned if pinned is None else pinned,
                approval_state=existing.approval_state if approval_state is None else approval_state,
                approval_note=existing.approval_note if approval_note is None else approval_note,
                provenance=existing.provenance,
                verification_id=existing.verification_id,
                artifact_ids=existing.artifact_ids,
            )
            write_checkpoint(self.layout, updated, mutation=self._transaction_writer())
            return updated

    def pin_checkpoint(self, checkpoint_id: str) -> CheckpointRecord:
        return self.update_checkpoint(checkpoint_id, pinned=True)

    def unpin_checkpoint(self, checkpoint_id: str) -> CheckpointRecord:
        return self.update_checkpoint(checkpoint_id, pinned=False)

    def set_checkpoint_approval(self, checkpoint_id: str, *, state: ApprovalState, note: str | None = None) -> CheckpointRecord:
        return self.update_checkpoint(checkpoint_id, approval_state=state, approval_note=note)

    def rollback_to_checkpoint(
        self,
        checkpoint_id: str | None = None,
        *,
        use_latest_safe: bool = True,
        lineage_id: str | None = None,
    ) -> CheckpointRecord:
        from lit.workflows import WorkflowService

        return WorkflowService(self).rollback_to_checkpoint(
            checkpoint_id,
            use_latest_safe=use_latest_safe,
            lineage_id=lineage_id,
        )

    def list_lineages(self) -> tuple[LineageRecord, ...]:
        return tuple(
            LineageRecord.from_dict(read_json(path, default=None))
            for path in sorted(self.layout.lineages.glob("*.json"))
        )

    def _append_revision_checkpoint(self, revision_id: str, checkpoint_id: str) -> None:
        revision = self.get_revision(revision_id)
        write_json(
            self.layout.revision_path(revision_id),
            RevisionRecord(
                revision_id=revision.revision_id,
                tree=revision.tree,
                parents=revision.parents,
                message=revision.message,
                provenance=revision.provenance,
                verification_id=revision.verification_id,
                artifact_ids=revision.artifact_ids,
                checkpoint_ids=self._append_unique(revision.checkpoint_ids, (checkpoint_id,)),
            ).to_dict(),
        )

    def _attach_revision_verification(self, revision_id: str, verification_id: str) -> None:
        revision = self.get_revision(revision_id)
        verification = self.get_verification(verification_id)
        write_json(
            self.layout.revision_path(revision_id),
            RevisionRecord(
                revision_id=revision.revision_id,
                tree=revision.tree,
                parents=revision.parents,
                message=revision.message,
                provenance=self._provenance_with_verification(revision.provenance, verification),
                verification_id=verification_id,
                artifact_ids=revision.artifact_ids,
                checkpoint_ids=revision.checkpoint_ids,
            ).to_dict(),
        )

    def _attach_checkpoint_verification(self, checkpoint_id: str, verification_id: str) -> None:
        checkpoint = self.get_checkpoint(checkpoint_id)
        verification = self.get_verification(verification_id)
        write_json(
            self.layout.checkpoint_path(checkpoint_id),
            CheckpointRecord(
                checkpoint_id=checkpoint.checkpoint_id,
                revision_id=checkpoint.revision_id,
                name=checkpoint.name,
                note=checkpoint.note,
                created_at=checkpoint.created_at,
                safe=checkpoint.safe,
                pinned=checkpoint.pinned,
                approval_state=checkpoint.approval_state,
                approval_note=checkpoint.approval_note,
                provenance=self._provenance_with_verification(checkpoint.provenance, verification),
                verification_id=verification_id,
                artifact_ids=checkpoint.artifact_ids,
            ).to_dict(),
        )

    def _ensure_lineage(
        self,
        lineage_id: str,
        *,
        head_revision: str | None = None,
        forked_from: str | None = None,
        promoted_from: str | None = None,
        checkpoint_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> object:
        from lit.lineage import upsert_lineage_record

        return upsert_lineage_record(
            self.layout,
            lineage_id,
            head_revision=head_revision,
            forked_from=forked_from,
            promoted_from=promoted_from,
            checkpoint_id=checkpoint_id,
            title=title,
            description=description,
        )

    def _append_unique(self, existing: tuple[str, ...], additional: tuple[str, ...]) -> tuple[str, ...]:
        ordered = list(existing)
        seen = set(existing)
        for item in additional:
            if item not in seen:
                ordered.append(item)
                seen.add(item)
        return tuple(ordered)

    def _provenance_with_verification(
        self,
        provenance: ProvenanceRecord,
        verification: object,
    ) -> ProvenanceRecord:
        return ProvenanceRecord(
            actor_role=provenance.actor_role,
            actor_id=provenance.actor_id,
            prompt_template=provenance.prompt_template,
            agent_family=provenance.agent_family,
            run_id=provenance.run_id,
            block_id=provenance.block_id,
            step_id=provenance.step_id,
            lineage_id=provenance.lineage_id,
            verification_status=verification.status,
            verification_summary=verification.summary,
            committed_at=provenance.committed_at,
            origin_commit=provenance.origin_commit,
            rewritten_from=provenance.rewritten_from,
            promoted_from=provenance.promoted_from,
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
        from lit.workflows import WorkflowService

        return WorkflowService(self).record_verification(
            revision_id=revision_id,
            definition_name=definition_name,
            command=command,
            allow_cache=allow_cache,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        )

    def _find_cached_verification(self, revision_id: str, *, state_fingerprint: str | None, environment_fingerprint: str | None, command_identity: str | None) -> VerificationRecord | None:
        for path in sorted(self.layout.verifications.glob("*.json")):
            record = VerificationRecord.from_dict(read_json(path, default=None))
            if record.owner_id == revision_id and record.state_fingerprint == state_fingerprint and record.environment_fingerprint == environment_fingerprint and record.command_identity == command_identity:
                return record
        return None

    def _populate_tree(self, tree_id: str, prefix: Path, files: dict[str, TrackedFile]) -> None:
        record = deserialize_tree(self.read_object("trees", tree_id))
        for entry in record.entries:
            child_path = prefix / entry.name
            if entry.entry_type == "tree":
                self._populate_tree(entry.object_id, child_path, files)
                continue
            path = normalize_repo_path(child_path)
            files[path] = TrackedFile(path, entry.object_id, entry.size, entry.executable)

    def _store_tree(self, files: Mapping[str, TrackedFile]) -> str:
        nested: dict[str, dict[str, object] | TrackedFile] = {}
        for path, tracked in sorted(files.items()):
            cursor = nested
            parts = path.split("/")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})  # type: ignore[assignment]
            cursor[parts[-1]] = tracked
        return self._store_tree_node(nested)

    def _store_tree_node(self, node: dict[str, dict[str, object] | TrackedFile]) -> str:
        entries: list[TreeEntry] = []
        for name in sorted(node):
            value = node[name]
            if isinstance(value, TrackedFile):
                entries.append(TreeEntry(name, "blob", value.digest, value.size, value.executable))
            else:
                entries.append(TreeEntry(name, "tree", self._store_tree_node(value)))
        return self._store_object("trees", serialize_tree(TreeRecord(tuple(entries))))

    def _select_tree_paths(self, files: Mapping[str, TrackedFile], requested_paths: tuple[str | Path, ...]) -> set[str]:
        selected: set[str] = set()
        for raw_path in requested_paths:
            normalized = normalize_repo_path(Path(raw_path))
            normalized = "" if normalized == "." else normalized
            prefixes = (normalized, f"{normalized}/") if normalized else ("",)
            selected.update(path for path in files if any(path == prefix or path.startswith(prefix) for prefix in prefixes))
        return selected

    def _clear_index_entries(self, requested_paths: tuple[str | Path, ...]) -> None:
        if requested_paths:
            def matches_selected(entry_path: str) -> bool:
                return any(entry_path == normalize_repo_path(Path(raw)) or entry_path.startswith(f"{normalize_repo_path(Path(raw))}/") for raw in requested_paths)

            remaining_entries = tuple(entry for entry in self.read_index().entries if not matches_selected(entry.path))
        else:
            remaining_entries = ()
        write_json(self.layout.index, IndexState(remaining_entries).to_dict(), mutation=self._transaction_writer())

    def _ensure_checkout_safe(self, target_commit: str | None, *, baseline_commit: str | None) -> None:
        status = self.status()
        if any((status.staged_added, status.staged_modified, status.staged_deleted, status.modified, status.deleted)):
            raise RuntimeError("checkout requires a clean index and tracked working tree")
        target_files = self.read_commit_tree(target_commit)
        baseline_files = self.read_commit_tree(baseline_commit)
        clobbered = sorted(path for path in status.untracked if path in target_files and path not in baseline_files)
        if clobbered:
            listed = ", ".join(clobbered[:3])
            suffix = "" if len(clobbered) <= 3 else ", ..."
            raise RuntimeError(f"checkout would overwrite untracked paths: {listed}{suffix}")

    def _write_working_file(self, path: str, tracked: TrackedFile) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(target, self.read_object("blobs", tracked.digest), mutation=self._transaction_writer())
        if target.exists():
            mode = target.stat().st_mode
            target.chmod((mode | 0o111) if tracked.executable else (mode & ~0o111))

    def write_working_text(self, path: str, content: str) -> None:
        write_bytes(self.root / path, content.encode("utf-8"), mutation=self._transaction_writer())

    def _read_blob_text(self, digest: str) -> list[str]:
        return self.read_object("blobs", digest).decode("utf-8", errors="replace").splitlines()

    def _read_file_text(self, path: str) -> list[str]:
        return (self.root / path).read_text(encoding="utf-8", errors="replace").splitlines()

    def _prune_empty_directories(self, start: Path) -> None:
        current = start
        while current != self.root and current.exists():
            if current == self.layout.dot_lit:
                return
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent


try:
    from lit.backend_api import BackendService
except ImportError:  # pragma: no cover - legacy backend shim during circular imports
    class BackendService:  # type: ignore[no-redef]
        pass


class RepositoryBackend(BackendService):
    def open_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        if request.create_if_missing and not (request.root / ".lit").is_dir():
            return Repository.create(request.root, default_branch=request.default_branch).repository_handle()
        return Repository.open(request.root).repository_handle()

    def initialize_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        return Repository.create(request.root, default_branch=request.default_branch).repository_handle()

    def get_repository_state(self, root: Path) -> RepositoryHandle:
        return Repository.open(root).repository_handle()

    def list_revisions(self, root: Path, *, start_revision: str | None = None, lineage_id: str | None = None) -> tuple[RevisionRecord, ...]:
        return Repository.open(root).list_revisions(start_revision=start_revision, lineage_id=lineage_id)

    def get_revision(self, root: Path, revision_id: str) -> RevisionRecord:
        return Repository.open(root).get_revision(revision_id)

    def create_revision(self, request: CreateRevisionRequest) -> OperationRecord:
        return Repository.open(request.root).create_revision(message=request.message, tree=request.tree, parents=request.parents, provenance=request.provenance, artifact_ids=request.artifact_ids)

    def list_checkpoints(self, root: Path, *, lineage_id: str | None = None, only_safe: bool = False) -> tuple[CheckpointRecord, ...]:
        return Repository.open(root).list_checkpoints(lineage_id=lineage_id, only_safe=only_safe)

    def get_checkpoint(self, root: Path, checkpoint_id: str) -> CheckpointRecord:
        return Repository.open(root).get_checkpoint(checkpoint_id)

    def create_checkpoint(self, request: CreateCheckpointRequest) -> OperationRecord:
        return Repository.open(request.root).create_checkpoint(revision_id=request.revision_id, name=request.name, note=request.note, safe=request.safe, pinned=request.pinned, approval_state=request.approval_state, provenance=request.provenance, artifact_ids=request.artifact_ids)

    def rollback_to_checkpoint(self, request: RollbackRequest) -> OperationRecord:
        return Repository.open(request.root).rollback_to_checkpoint(checkpoint_id=request.checkpoint_id, use_latest_safe=request.use_latest_safe)

    def list_lineages(self, root: Path) -> tuple[LineageRecord, ...]:
        return Repository.open(root).list_lineages()

    def get_lineage(self, root: Path, lineage_id: str) -> LineageRecord:
        return Repository.open(root).get_lineage(lineage_id)

    def create_lineage(self, request: CreateLineageRequest) -> OperationRecord:
        return Repository.open(request.root).create_lineage(lineage_id=request.lineage_id, forked_from=request.forked_from, title=request.title, description=request.description)

    def promote_lineage(self, request: PromoteLineageRequest) -> OperationRecord:
        return Repository.open(request.root).promote_lineage(lineage_id=request.lineage_id, destination_lineage_id=request.destination_lineage_id, expected_head_revision=request.expected_head_revision)

    def record_verification(self, request: VerifyRevisionRequest) -> VerificationRecord:
        return Repository.open(request.root).record_verification(revision_id=request.revision_id, command=request.command, allow_cache=request.allow_cache, state_fingerprint=request.state_fingerprint, environment_fingerprint=request.environment_fingerprint, command_identity=request.command_identity)

    def get_verification(self, root: Path, verification_id: str) -> VerificationRecord:
        return Repository.open(root).get_verification(verification_id)

    def list_artifacts(self, root: Path, *, owner_id: str | None = None) -> tuple[ArtifactRecord, ...]:
        return Repository.open(root).list_artifacts(owner_id=owner_id)

    def get_artifact(self, root: Path, artifact_id: str) -> ArtifactRecord:
        return Repository.open(root).get_artifact(artifact_id)


__all__ = [
    "BranchRecord",
    "CheckoutRecord",
    "Repository",
    "RepositoryBackend",
    "RepositoryConfig",
    "RepositoryLayout",
    "StatusReport",
    "TrackedFile",
]
