from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lit.storage import read_json, write_json


@dataclass(frozen=True)
class IndexEntry:
    path: str
    digest: str
    size: int
    executable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "executable": self.executable,
            "path": self.path,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "IndexEntry":
        return cls(
            path=str(data["path"]),
            digest=str(data["digest"]),
            size=int(data["size"]),
            executable=bool(data.get("executable", False)),
        )


@dataclass(frozen=True)
class IndexState:
    entries: tuple[IndexEntry, ...] = ()

    def to_dict(self) -> dict[str, object]:
        ordered_entries = sorted(self.entries, key=lambda entry: entry.path)
        return {"entries": [entry.to_dict() for entry in ordered_entries]}

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "IndexState":
        if not data:
            return cls()
        entries = tuple(
            IndexEntry.from_dict(entry) for entry in data.get("entries", [])
        )
        return cls(entries=tuple(sorted(entries, key=lambda entry: entry.path)))


def read_index(path: Path) -> IndexState:
    return IndexState.from_dict(read_json(path, default={"entries": []}))


def write_index(path: Path, state: IndexState) -> None:
    write_json(path, state.to_dict())
