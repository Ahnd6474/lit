from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

TreeEntryType = Literal["blob", "tree"]


@dataclass(frozen=True)
class TreeEntry:
    name: str
    entry_type: TreeEntryType
    object_id: str
    size: int = 0
    executable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_type": self.entry_type,
            "executable": self.executable,
            "name": self.name,
            "object_id": self.object_id,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TreeEntry":
        return cls(
            name=str(data["name"]),
            entry_type=str(data["entry_type"]),
            object_id=str(data["object_id"]),
            size=int(data.get("size", 0)),
            executable=bool(data.get("executable", False)),
        )


@dataclass(frozen=True)
class TreeRecord:
    entries: tuple[TreeEntry, ...] = ()

    def to_dict(self) -> dict[str, object]:
        ordered_entries = sorted(self.entries, key=lambda entry: (entry.name, entry.entry_type))
        return {"entries": [entry.to_dict() for entry in ordered_entries]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TreeRecord":
        entries = tuple(
            TreeEntry.from_dict(entry) for entry in data.get("entries", [])
        )
        return cls(entries=tuple(sorted(entries, key=lambda entry: (entry.name, entry.entry_type))))


def serialize_tree(record: TreeRecord) -> bytes:
    return json.dumps(record.to_dict(), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def deserialize_tree(payload: bytes) -> TreeRecord:
    return TreeRecord.from_dict(json.loads(payload.decode("utf-8")))
