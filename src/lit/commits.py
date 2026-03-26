from __future__ import annotations

import json
from dataclasses import dataclass

from lit.storage import hash_bytes


@dataclass(frozen=True)
class CommitRecord:
    tree: str
    parents: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            "parents": list(self.parents),
            "tree": self.tree,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CommitRecord":
        return cls(
            tree=str(data["tree"]),
            parents=tuple(str(parent) for parent in data.get("parents", [])),
            message=str(data["message"]),
        )


def serialize_commit(record: CommitRecord) -> bytes:
    return json.dumps(record.to_dict(), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def deserialize_commit(payload: bytes) -> CommitRecord:
    return CommitRecord.from_dict(json.loads(payload.decode("utf-8")))


def commit_id(record: CommitRecord) -> str:
    return hash_bytes(serialize_commit(record))
