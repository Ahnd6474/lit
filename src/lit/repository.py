from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

from lit.commits import CommitMetadata, CommitRecord, deserialize_commit, serialize_commit
from lit.domain import ApprovalState, CheckpointRecord, LineageRecord, ProvenanceRecord, RevisionRecord
from lit.index import IndexEntry, IndexState, read_index, write_index
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
from lit.storage import hash_bytes, read_json, write_json
from lit.trees import TreeEntry, TreeRecord, deserialize_tree, serialize_tree
from lit.transactions import next_identifier, utc_now
from lit.working_tree import FileSnapshot, normalize_repo_path, scan_working_tree

ObjectKind = Literal["blobs", "trees", "commits"]


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
        return {
            "default_branch": self.default_branch,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "RepositoryConfig":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            default_branch=str(data.get("default_branch", "main")),
        )


@dataclass(frozen=True)
class RepositoryLayout:
    root: Path

    @property
    def dot_lit(self) -> Path:
        return self.root / ".lit"

    @property
    def config(self) -> Path:
        return self.dot_lit / "config.json"

    @property
    def head(self) -> Path:
        return self.dot_lit / "HEAD"

    @property
    def index(self) -> Path:
        return self.dot_lit / "index.json"

    @property
    def refs(self) -> Path:
        return self.dot_lit / "refs"

    @property
    def heads(self) -> Path:
        return self.refs / "heads"

    @property
    def tags(self) -> Path:
        return self.refs / "tags"

    @property
    def v1(self) -> Path:
        return self.dot_lit / "v1"

    @property
    def objects(self) -> Path:
        return self.dot_lit / "objects"

    @property
    def blobs(self) -> Path:
        return self.objects / "blobs"

    @property
    def trees(self) -> Path:
        return self.objects / "trees"

    @property
    def commits(self) -> Path:
        return self.objects / "commits"

    @property
    def state(self) -> Path:
        return self.dot_lit / "state"

    @property
    def merge_state(self) -> Path:
        return self.state / "merge.json"

    @property
    def rebase_state(self) -> Path:
        return self.state / "rebase.json"

    @property
    def revisions(self) -> Path:
        return self.v1 / "revisions"

    @property
    def checkpoints(self) -> Path:
        return self.v1 / "checkpoints"

    @property
    def lineages(self) -> Path:
        return self.v1 / "lineages"

    @property
    def verifications(self) -> Path:
        return self.v1 / "verifications"

    @property
    def artifacts(self) -> Path:
        return self.v1 / "artifacts"

    @property
    def operations(self) -> Path:
        return self.v1 / "operations"

    @property
    def journals(self) -> Path:
        return self.v1 / "journals"

    @property
    def locks(self) -> Path:
        return self.v1 / "locks"

    def branch_path(self, branch_name: str) -> Path:
        return self.heads / normalize_branch_name(branch_name)

    def object_dir(self, kind: ObjectKind) -> Path:
        return getattr(self, kind)

    def object_path(self, kind: ObjectKind, object_id: str) -> Path:
        return self.object_dir(kind) / object_id

    def revision_path(self, revision_id: str) -> Path:
        return self.revisions / f"{revision_id}.json"

    def checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoints / f"{checkpoint_id}.json"

    def lineage_path(self, lineage_id: str) -> Path:
        return self.lineages / f"{lineage_id}.json"

    def verification_path(self, verification_id: str) -> Path:
        return self.verifications / f"{verification_id}.json"

    def artifact_dir(self, artifact_id: str) -> Path:
        return self.artifacts / artifact_id

    def artifact_record_path(self, artifact_id: str) -> Path:
        return self.artifact_dir(artifact_id) / "artifact.json"

    def artifact_payload_path(self, artifact_id: str, filename: str = "payload") -> Path:
        return self.artifact_dir(artifact_id) / filename

    def operation_path(self, operation_id: str) -> Path:
        return self.operations / f"{operation_id}.json"

    def journal_path(self, operation_id: str) -> Path:
        return self.journals / f"{operation_id}.jsonl"

    def journal_dir(self, operation_id: str) -> Path:
        return self.journals / operation_id

    def lock_path(self, name: str = "repository") -> Path:
        return self.locks / f"{name}.lock"

    def directories(self) -> tuple[Path, ...]:
        return (
            self.dot_lit,
            self.v1,
            self.objects,
            self.blobs,
            self.trees,
            self.commits,
            self.refs,
            self.heads,
            self.tags,
            self.state,
            self.revisions,
            self.checkpoints,
            self.lineages,
            self.verifications,
            self.artifacts,
            self.operations,
            self.journals,
            self.locks,
        )


@dataclass
class Repository:
    root: Path
    layout: RepositoryLayout
    config: RepositoryConfig

    @classmethod
    def create(cls, root: str | Path, *, default_branch: str = "main") -> "Repository":
        repository_root = Path(root).resolve()
        repository_root.mkdir(parents=True, exist_ok=True)
        layout = RepositoryLayout(repository_root)
        existed = layout.dot_lit.exists()
        config = RepositoryConfig(default_branch=normalize_branch_name(default_branch))

        for directory in layout.directories():
            directory.mkdir(parents=True, exist_ok=True)

        if not layout.config.exists():
            write_json(layout.config, config.to_dict())
        if not layout.head.exists():
            write_head(layout.head, branch_ref(config.default_branch))
        if not layout.index.exists():
            write_index(layout.index, IndexState())
        if not layout.branch_path(config.default_branch).exists():
            write_ref(layout.branch_path(config.default_branch), None)
        if not layout.merge_state.exists():
            write_merge_state(layout.merge_state, None)
        if not layout.rebase_state.exists():
            write_rebase_state(layout.rebase_state, None)
        if not layout.lineage_path(config.default_branch).exists():
            now = utc_now()
            write_json(
                layout.lineage_path(config.default_branch),
                LineageRecord(
                    lineage_id=config.default_branch,
                    created_at=now,
                    updated_at=now,
                    title=config.default_branch,
                ).to_dict(),
            )

        repository = cls.open(repository_root)
        if not existed and repository.current_branch_name() is None:
            raise RuntimeError("new repository should initialize HEAD to a branch")
        return repository

    @classmethod
    def open(cls, root: str | Path) -> "Repository":
        repository_root = Path(root).resolve()
        layout = RepositoryLayout(repository_root)
        if not layout.dot_lit.is_dir():
            raise FileNotFoundError(f"lit repository not found at {layout.dot_lit}")
        config = RepositoryConfig.from_dict(read_json(layout.config, default=None))
        return cls(root=repository_root, layout=layout, config=config)

    @classmethod
    def discover(cls, start: str | Path) -> "Repository":
        current = Path(start).resolve()
        for candidate in (current, *current.parents):
            if (candidate / ".lit").is_dir():
                return cls.open(candidate)
        raise FileNotFoundError(f"lit repository not found from {current}")

    def current_head_ref(self) -> str | None:
        head = read_head(self.layout.head)
        if branch_name_from_ref(head) is None:
            return None
        return head

    def set_head_ref(self, ref_name: str) -> None:
        write_head(self.layout.head, ref_name)

    def set_head_commit(self, commit_id: str) -> None:
        write_head(self.layout.head, commit_id, symbolic=False)

    def current_head_target(self) -> str | None:
        return read_head(self.layout.head)

    def current_branch_name(self) -> str | None:
        return branch_name_from_ref(self.current_head_target())

    def read_branch(self, branch_name: str) -> str | None:
        return read_ref(self.layout.branch_path(branch_name))

    def write_branch(self, branch_name: str, commit_id: str | None) -> None:
        write_ref(self.layout.branch_path(branch_name), commit_id)

    def list_branches(self) -> tuple[BranchRecord, ...]:
        current = self.current_branch_name()
        names = tuple(sorted(iter_ref_names(self.layout.heads)))
        return tuple(
            BranchRecord(
                name=name,
                ref=branch_ref(name),
                commit_id=self.read_branch(name),
                current=name == current,
            )
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
        path = self.layout.branch_path(normalized)
        if path.exists() and not force:
            raise ValueError(f"branch already exists: {normalized}")
        commit_id = self.resolve_revision(start_point)
        self.write_branch(normalized, commit_id)
        return BranchRecord(
            name=normalized,
            ref=branch_ref(normalized),
            commit_id=commit_id,
            current=normalized == self.current_branch_name(),
        )

    def read_index(self) -> IndexState:
        return read_index(self.layout.index)

    def write_index(self, state: IndexState) -> None:
        write_index(self.layout.index, state)

    def read_merge_state(self) -> MergeState | None:
        return read_merge_state(self.layout.merge_state)

    def write_merge_state(self, state: MergeState | None) -> None:
        write_merge_state(self.layout.merge_state, state)

    def read_rebase_state(self) -> RebaseState | None:
        return read_rebase_state(self.layout.rebase_state)

    def write_rebase_state(self, state: RebaseState | None) -> None:
        write_rebase_state(self.layout.rebase_state, state)

    def current_operation(self) -> OperationState | None:
        return active_operation(self.read_merge_state(), self.read_rebase_state())

    def begin_merge(
        self,
        *,
        base_commit: str,
        target_commit: str,
        current_commit: str | None = None,
        target_ref: str | None = None,
        conflicts: Iterable[str] = (),
    ) -> MergeState:
        head_ref = self.current_head_ref()
        if head_ref is None:
            raise RuntimeError("merge state requires HEAD to point to a branch")
        state = MergeState(
            head_ref=head_ref,
            base_commit=base_commit,
            current_commit=current_commit or self.current_commit_id() or "",
            target_commit=target_commit,
            target_ref=target_ref,
            conflicts=tuple(sorted(set(conflicts))),
        )
        self.write_merge_state(state)
        return state

    def clear_merge(self) -> None:
        self.write_merge_state(None)

    def begin_rebase(
        self,
        *,
        onto: str,
        original_head: str | None = None,
        pending_commits: Iterable[str] = (),
        applied_commits: Iterable[str] = (),
        current_commit: str | None = None,
        conflicts: Iterable[str] = (),
    ) -> RebaseState:
        head_ref = self.current_head_ref()
        resolved_head = original_head or self.current_commit_id()
        if head_ref is None or resolved_head is None:
            raise RuntimeError("rebase state requires a current branch and commit")
        state = RebaseState(
            head_ref=head_ref,
            original_head=resolved_head,
            onto=onto,
            pending_commits=tuple(pending_commits),
            applied_commits=tuple(applied_commits),
            current_commit=current_commit,
            conflicts=tuple(sorted(set(conflicts))),
        )
        self.write_rebase_state(state)
        return state

    def advance_rebase(
        self,
        *,
        pending_commits: Iterable[str],
        applied_commits: Iterable[str],
        current_commit: str | None = None,
        conflicts: Iterable[str] = (),
    ) -> RebaseState:
        state = self.read_rebase_state()
        if state is None:
            raise RuntimeError("no rebase is in progress")
        updated = RebaseState(
            head_ref=state.head_ref,
            original_head=state.original_head,
            onto=state.onto,
            pending_commits=tuple(pending_commits),
            applied_commits=tuple(applied_commits),
            current_commit=current_commit,
            conflicts=tuple(sorted(set(conflicts))),
        )
        self.write_rebase_state(updated)
        return updated

    def clear_rebase(self) -> None:
        self.write_rebase_state(None)

    def clear_operations(self) -> None:
        self.clear_merge()
        self.clear_rebase()

    def store_object(self, kind: ObjectKind, payload: bytes) -> str:
        object_id = hash_bytes(payload)
        path = self.layout.object_path(kind, object_id)
        if not path.exists():
            path.write_bytes(payload)
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
            branch_commit = self.read_branch(branch_name)
            return branch_commit
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
            baseline = (
                TrackedFile.from_index_entry(entry)
                if entry is not None and entry.kind == "blob"
                else head_files.get(path)
            )
            if baseline is None:
                continue
            if working_file is None:
                deleted.append(path)
            elif (
                working_file.digest != baseline.digest
                or working_file.executable != baseline.executable
            ):
                modified.append(path)

        untracked = tuple(
            path
            for path in sorted(working_files)
            if path not in head_files and path not in index_entries
        )
        return StatusReport(
            staged_added=tuple(staged_added),
            staged_modified=tuple(staged_modified),
            staged_deleted=tuple(staged_deleted),
            modified=tuple(modified),
            deleted=tuple(deleted),
            untracked=untracked,
        )

    def diff(self) -> str:
        from difflib import unified_diff

        head_files = self.read_commit_tree(self.current_commit_id())
        working_files = self.working_tree()
        chunks: list[str] = []
        for path in sorted(set(head_files) | set(working_files)):
            head_file = head_files.get(path)
            working_file = working_files.get(path)
            if head_file is not None and working_file is not None:
                if (
                    head_file.digest == working_file.digest
                    and head_file.executable == working_file.executable
                ):
                    continue
            if head_file is None and working_file is None:
                continue
            before = [] if head_file is None else self._read_blob_text(head_file.digest)
            after = [] if working_file is None else self._read_file_text(path)
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
                chunks.append("\n".join(diff_lines))
        return "\n\n".join(chunks)

    def apply_commit(
        self,
        commit_id: str | None,
        *,
        paths: Iterable[str | Path] | None = None,
        baseline_commit: str | None = None,
        clear_index: bool = True,
    ) -> tuple[str, ...]:
        return self.apply_tree(
            self.read_commit_tree(commit_id),
            paths=paths,
            baseline=self.read_commit_tree(
                self.current_commit_id() if baseline_commit is None else baseline_commit
            ),
            clear_index=clear_index,
        )

    def apply_tree(
        self,
        tracked_files: Mapping[str, TrackedFile],
        *,
        paths: Iterable[str | Path] | None = None,
        baseline: Mapping[str, TrackedFile] | None = None,
        clear_index: bool = True,
    ) -> tuple[str, ...]:
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
                target.unlink()
                self._prune_empty_directories(target.parent)

        for path in sorted(selected_source_paths):
            self._write_working_file(path, tracked_files[path])

        if clear_index:
            self._clear_index_entries(requested_paths)
        return tuple(sorted(selected_source_paths | selected_baseline_paths))

    def restore(self, paths: Iterable[str | Path] | None = None, *, source: str | None = None) -> tuple[str, ...]:
        return self.apply_commit(
            self.resolve_revision(source),
            paths=paths,
            baseline_commit=self.current_commit_id(),
            clear_index=True,
        )

    def checkout(self, revision: str) -> CheckoutRecord:
        operation = self.current_operation()
        if operation is not None:
            raise RuntimeError(f"cannot checkout while a {operation.kind} is in progress")

        target_branch = self.resolve_branch_name(revision)
        target_commit = self.resolve_revision(revision)
        current_commit = self.current_commit_id()
        self._ensure_checkout_safe(target_commit, baseline_commit=current_commit)
        restored_paths = self.apply_commit(target_commit, baseline_commit=current_commit)
        if target_branch is not None:
            self.set_head_ref(branch_ref(target_branch))
        elif target_commit is not None:
            self.set_head_commit(target_commit)
        else:
            raise RuntimeError(f"cannot detach HEAD at unresolved revision: {revision}")
        return CheckoutRecord(
            revision=revision,
            commit_id=target_commit,
            branch_name=target_branch,
            restored_paths=restored_paths,
        )

    def _normalize_provenance(
        self,
        provenance: ProvenanceRecord | None,
        *,
        fallback: ProvenanceRecord | None = None,
    ) -> ProvenanceRecord:
        base = provenance or fallback or ProvenanceRecord()
        return ProvenanceRecord(
            actor_role=base.actor_role,
            actor_id=base.actor_id,
            prompt_template=base.prompt_template,
            agent_family=base.agent_family,
            run_id=base.run_id,
            block_id=base.block_id,
            step_id=base.step_id,
            lineage_id=base.lineage_id or self.current_branch_name() or self.config.default_branch,
            verification_status=base.verification_status,
            verification_summary=base.verification_summary,
            committed_at=base.committed_at or utc_now(),
            origin_commit=base.origin_commit,
            rewritten_from=base.rewritten_from,
            promoted_from=base.promoted_from,
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

    def _populate_tree(
        self,
        tree_id: str,
        prefix: Path,
        files: dict[str, TrackedFile],
    ) -> None:
        record = deserialize_tree(self.read_object("trees", tree_id))
        for entry in record.entries:
            child_path = prefix / entry.name
            if entry.entry_type == "tree":
                self._populate_tree(entry.object_id, child_path, files)
                continue
            path = normalize_repo_path(child_path)
            files[path] = TrackedFile(
                path=path,
                digest=entry.object_id,
                size=entry.size,
                executable=entry.executable,
            )

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
                entries.append(
                    TreeEntry(
                        name=name,
                        entry_type="blob",
                        object_id=value.digest,
                        size=value.size,
                        executable=value.executable,
                    )
                )
                continue
            subtree_id = self._store_tree_node(value)
            entries.append(TreeEntry(name=name, entry_type="tree", object_id=subtree_id))
        return self.store_object("trees", serialize_tree(TreeRecord(entries=tuple(entries))))

    def _select_tree_paths(
        self,
        files: Mapping[str, TrackedFile],
        requested_paths: Iterable[str | Path],
    ) -> set[str]:
        selected: set[str] = set()
        for raw_path in requested_paths:
            normalized = normalize_repo_path(Path(raw_path))
            prefixes = (normalized, f"{normalized}/")
            selected.update(
                path
                for path in files
                if any(path == prefix or path.startswith(prefix) for prefix in prefixes)
            )
        return selected

    def _clear_index_entries(self, requested_paths: tuple[str | Path, ...]) -> None:
        if requested_paths:
            def matches_selected(entry_path: str) -> bool:
                return any(
                    entry_path == normalize_repo_path(Path(raw))
                    or entry_path.startswith(f"{normalize_repo_path(Path(raw))}/")
                    for raw in requested_paths
                )

            remaining_entries = tuple(
                entry for entry in self.read_index().entries if not matches_selected(entry.path)
            )
        else:
            remaining_entries = ()
        self.write_index(IndexState(entries=remaining_entries))

    def _ensure_checkout_safe(
        self,
        target_commit: str | None,
        *,
        baseline_commit: str | None,
    ) -> None:
        status = self.status()
        if any(
            (
                status.staged_added,
                status.staged_modified,
                status.staged_deleted,
                status.modified,
                status.deleted,
            )
        ):
            raise RuntimeError("checkout requires a clean index and tracked working tree")

        target_files = self.read_commit_tree(target_commit)
        baseline_files = self.read_commit_tree(baseline_commit)
        clobbered = sorted(
            path
            for path in status.untracked
            if path in target_files and path not in baseline_files
        )
        if clobbered:
            listed = ", ".join(clobbered[:3])
            suffix = "" if len(clobbered) <= 3 else ", ..."
            raise RuntimeError(f"checkout would overwrite untracked paths: {listed}{suffix}")

    def _write_working_file(self, path: str, tracked: TrackedFile) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.read_object("blobs", tracked.digest))
        mode = target.stat().st_mode
        if tracked.executable:
            target.chmod(mode | 0o111)
        else:
            target.chmod(mode & ~0o111)

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
