from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lit.storage import read_json, write_json

OperationKind = Literal["merge", "rebase"]


@dataclass(frozen=True)
class MergeState:
    head_ref: str
    base_commit: str
    current_commit: str
    target_commit: str
    target_ref: str | None = None
    conflicts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "base_commit": self.base_commit,
            "conflicts": list(self.conflicts),
            "current_commit": self.current_commit,
            "head_ref": self.head_ref,
            "target_commit": self.target_commit,
        }
        if self.target_ref is not None:
            data["target_ref"] = self.target_ref
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MergeState":
        return cls(
            head_ref=str(data["head_ref"]),
            base_commit=str(data["base_commit"]),
            current_commit=str(data["current_commit"]),
            target_commit=str(data["target_commit"]),
            target_ref=(
                None if data.get("target_ref") is None else str(data["target_ref"])
            ),
            conflicts=tuple(str(path) for path in data.get("conflicts", [])),
        )


@dataclass(frozen=True)
class RebaseState:
    head_ref: str
    original_head: str
    onto: str
    pending_commits: tuple[str, ...] = ()
    applied_commits: tuple[str, ...] = ()
    current_commit: str | None = None
    conflicts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "applied_commits": list(self.applied_commits),
            "conflicts": list(self.conflicts),
            "head_ref": self.head_ref,
            "onto": self.onto,
            "original_head": self.original_head,
            "pending_commits": list(self.pending_commits),
        }
        if self.current_commit is not None:
            data["current_commit"] = self.current_commit
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RebaseState":
        return cls(
            head_ref=str(data["head_ref"]),
            original_head=str(data["original_head"]),
            onto=str(data["onto"]),
            pending_commits=tuple(str(commit) for commit in data.get("pending_commits", [])),
            applied_commits=tuple(str(commit) for commit in data.get("applied_commits", [])),
            current_commit=(
                None if data.get("current_commit") is None else str(data["current_commit"])
            ),
            conflicts=tuple(str(path) for path in data.get("conflicts", [])),
        )


@dataclass(frozen=True)
class OperationState:
    kind: OperationKind
    state: MergeState | RebaseState


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


def active_operation(
    merge_state: MergeState | None,
    rebase_state: RebaseState | None,
) -> OperationState | None:
    if merge_state is not None and rebase_state is not None:
        raise RuntimeError("multiple operations are in progress")
    if merge_state is not None:
        return OperationState(kind="merge", state=merge_state)
    if rebase_state is not None:
        return OperationState(kind="rebase", state=rebase_state)
    return None
