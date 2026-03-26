from __future__ import annotations

import json
from dataclasses import dataclass, field

from lit.storage import hash_bytes


@dataclass(frozen=True)
class CommitMetadata:
    author: str = "lit"
    committed_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"author": self.author}
        if self.committed_at is not None:
            data["committed_at"] = self.committed_at
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "CommitMetadata":
        if not data:
            return cls()
        return cls(
            author=str(data.get("author", "lit")),
            committed_at=(
                None if data.get("committed_at") is None else str(data["committed_at"])
            ),
        )


@dataclass(frozen=True)
class CommitRecord:
    tree: str
    parents: tuple[str, ...]
    message: str
    metadata: CommitMetadata = field(default_factory=CommitMetadata)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def summary(self) -> str:
        return self.message.splitlines()[0] if self.message else ""

    @property
    def primary_parent(self) -> str | None:
        return self.parents[0] if self.parents else None

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            "metadata": self.metadata.to_dict(),
            "parents": list(self.parents),
            "tree": self.tree,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CommitRecord":
        return cls(
            tree=str(data["tree"]),
            parents=tuple(str(parent) for parent in data.get("parents", [])),
            message=str(data["message"]),
            metadata=CommitMetadata.from_dict(data.get("metadata")),
        )


def serialize_commit(record: CommitRecord) -> bytes:
    return json.dumps(record.to_dict(), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def deserialize_commit(payload: bytes) -> CommitRecord:
    return CommitRecord.from_dict(json.loads(payload.decode("utf-8")))


def commit_id(record: CommitRecord) -> str:
    return hash_bytes(serialize_commit(record))
