from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lit.storage import hash_bytes


def normalize_repo_path(path: str | Path) -> str:
    raw = Path(path).as_posix()
    if raw.startswith("./"):
        return raw[2:]
    return raw


@dataclass(frozen=True)
class FileSnapshot:
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
    def from_dict(cls, data: dict[str, object]) -> "FileSnapshot":
        return cls(
            path=str(data["path"]),
            digest=str(data["digest"]),
            size=int(data["size"]),
            executable=bool(data.get("executable", False)),
        )


def snapshot_file(repository_root: Path, file_path: Path) -> FileSnapshot:
    relative_path = normalize_repo_path(file_path.relative_to(repository_root))
    content = file_path.read_bytes()
    return FileSnapshot(
        path=relative_path,
        digest=hash_bytes(content),
        size=len(content),
        executable=file_path.stat().st_mode & 0o111 != 0,
    )


def sort_snapshots(entries: Iterable[FileSnapshot]) -> tuple[FileSnapshot, ...]:
    return tuple(sorted(entries, key=lambda entry: entry.path))


def scan_working_tree(repository_root: Path) -> tuple[FileSnapshot, ...]:
    snapshots: list[FileSnapshot] = []
    for candidate in sorted(repository_root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate == repository_root / ".lit":
            continue
        if (repository_root / ".lit") in candidate.parents:
            continue
        snapshots.append(snapshot_file(repository_root, candidate))
    return sort_snapshots(snapshots)
