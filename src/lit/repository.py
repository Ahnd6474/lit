from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lit.index import IndexState, read_index, write_index
from lit.refs import branch_ref, read_head, read_ref, write_head, write_ref
from lit.state import (
    MergeState,
    RebaseState,
    read_merge_state,
    read_rebase_state,
    write_merge_state,
    write_rebase_state,
)
from lit.storage import hash_bytes, read_json, write_json

ObjectKind = Literal["blobs", "trees", "commits"]


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
        return self.heads / branch_name

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
        config = RepositoryConfig(default_branch=default_branch)

        for directory in layout.directories():
            directory.mkdir(parents=True, exist_ok=True)

        if not layout.config.exists():
            write_json(layout.config, config.to_dict())
        if not layout.head.exists():
            write_head(layout.head, branch_ref(default_branch))
        if not layout.index.exists():
            write_index(layout.index, IndexState())
        if not layout.branch_path(default_branch).exists():
            write_ref(layout.branch_path(default_branch), None)
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

    def current_branch_name(self) -> str | None:
        head_ref = self.current_head_ref()
        if head_ref and head_ref.startswith("refs/heads/"):
            return head_ref.removeprefix("refs/heads/")
        return None

    def read_branch(self, branch_name: str) -> str | None:
        return read_ref(self.layout.branch_path(branch_name))

    def write_branch(self, branch_name: str, commit_id: str | None) -> None:
        write_ref(self.layout.branch_path(branch_name), commit_id)

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

    def store_object(self, kind: ObjectKind, payload: bytes) -> str:
        object_id = hash_bytes(payload)
        path = self.layout.object_path(kind, object_id)
        if not path.exists():
            path.write_bytes(payload)
        return object_id

    def read_object(self, kind: ObjectKind, object_id: str) -> bytes:
        return self.layout.object_path(kind, object_id).read_bytes()
