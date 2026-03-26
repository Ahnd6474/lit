from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lit.storage import read_json, write_json


@dataclass(frozen=True)
class MergeState:
    base_commit: str
    current_commit: str
    target_commit: str
    conflicts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "base_commit": self.base_commit,
            "conflicts": list(self.conflicts),
            "current_commit": self.current_commit,
            "target_commit": self.target_commit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MergeState":
        return cls(
            base_commit=str(data["base_commit"]),
            current_commit=str(data["current_commit"]),
            target_commit=str(data["target_commit"]),
            conflicts=tuple(str(path) for path in data.get("conflicts", [])),
        )


@dataclass(frozen=True)
class RebaseState:
    original_head: str
    onto: str
    pending_commits: tuple[str, ...] = ()
    applied_commits: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "applied_commits": list(self.applied_commits),
            "onto": self.onto,
            "original_head": self.original_head,
            "pending_commits": list(self.pending_commits),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RebaseState":
        return cls(
            original_head=str(data["original_head"]),
            onto=str(data["onto"]),
            pending_commits=tuple(str(commit) for commit in data.get("pending_commits", [])),
            applied_commits=tuple(str(commit) for commit in data.get("applied_commits", [])),
        )


def read_merge_state(path: Path) -> MergeState | None:
    data = read_json(path, default=None)
    if data is None:
        return None
    return MergeState.from_dict(data)


def write_merge_state(path: Path, state: MergeState | None) -> None:
    write_json(path, None if state is None else state.to_dict())


def read_rebase_state(path: Path) -> RebaseState | None:
    data = read_json(path, default=None)
    if data is None:
        return None
    return RebaseState.from_dict(data)


def write_rebase_state(path: Path, state: RebaseState | None) -> None:
    write_json(path, None if state is None else state.to_dict())
