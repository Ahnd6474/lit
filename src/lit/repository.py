from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping

from lit.commits import CommitRecord, deserialize_commit, serialize_commit
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

    def branch_path(self, branch_name: str) -> Path:
        return self.heads / normalize_branch_name(branch_name)

    def object_dir(self, kind: ObjectKind) -> Path:
        return getattr(self, kind)

    def object_path(self, kind: ObjectKind, object_id: str) -> Path:
        return self.object_dir(kind) / object_id

    def directories(self) -> tuple[Path, ...]:
        return (
            self.dot_lit,
            self.objects,
            self.blobs,
            self.trees,
            self.commits,
            self.refs,
            self.heads,
            self.tags,
            self.state,
        )


@dataclass
class Repository:
    root: Path
    layout: RepositoryLayout
    config: RepositoryConfig

    @classmethod
    def create(cls, root: str | Path, *, default_branch: str = "main") -> "Repository":
        repository_root = Path(root).resolve()
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
        return read_head(self.layout.head)

    def set_head_ref(self, ref_name: str) -> None:
        write_head(self.layout.head, ref_name)

    def current_branch_name(self) -> str | None:
        return branch_name_from_ref(self.current_head_ref())

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
        branch_name = self.current_branch_name()
        if branch_name is None:
            return None
        return self.read_branch(branch_name)

    def resolve_revision(self, revision: str | None = None) -> str | None:
        if revision in (None, "HEAD"):
            return self.current_commit_id()
        branch_commit = self.read_branch(revision)
        if branch_commit is not None or self.layout.branch_path(revision).exists():
            return branch_commit
        if self.layout.object_path("commits", revision).exists():
            return revision
        raise ValueError(f"unknown revision: {revision}")

    def read_commit(self, commit_id: str) -> CommitRecord:
        return deserialize_commit(self.read_object("commits", commit_id))

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

    def commit(self, message: str, *, parents: Iterable[str] | None = None) -> str:
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
        record = CommitRecord(tree=tree_id, parents=resolved_parents, message=message)
        commit_id = self.store_object("commits", serialize_commit(record))

        branch_name = self.current_branch_name()
        if branch_name is None:
            raise RuntimeError("commits require HEAD to point to a branch")
        self.write_branch(branch_name, commit_id)
        self.write_index(IndexState())
        return commit_id

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
