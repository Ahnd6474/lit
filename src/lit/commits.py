from __future__ import annotations

import json
from dataclasses import dataclass, field

from lit.domain import ProvenanceRecord, VerificationStatus
from lit.storage import hash_bytes


@dataclass(frozen=True)
class CommitMetadata:
    author: str = "lit"
    committed_at: str | None = None
    actor_role: str | None = None
    actor_id: str | None = None
    prompt_template: str | None = None
    agent_family: str | None = None
    run_id: str | None = None
    block_id: str | None = None
    step_id: str | None = None
    lineage_id: str | None = None
    verification_status: str | None = None
    verification_summary: str | None = None
    origin_commit: str | None = None
    rewritten_from: str | None = None
    promoted_from: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"author": self.author}
        if self.committed_at is not None:
            data["committed_at"] = self.committed_at
        if self.actor_role is not None:
            data["actor_role"] = self.actor_role
        if self.actor_id is not None:
            data["actor_id"] = self.actor_id
        if self.prompt_template is not None:
            data["prompt_template"] = self.prompt_template
        if self.agent_family is not None:
            data["agent_family"] = self.agent_family
        if self.run_id is not None:
            data["run_id"] = self.run_id
        if self.block_id is not None:
            data["block_id"] = self.block_id
        if self.step_id is not None:
            data["step_id"] = self.step_id
        if self.lineage_id is not None:
            data["lineage_id"] = self.lineage_id
        if self.verification_status is not None:
            data["verification_status"] = self.verification_status
        if self.verification_summary is not None:
            data["verification_summary"] = self.verification_summary
        if self.origin_commit is not None:
            data["origin_commit"] = self.origin_commit
        if self.rewritten_from is not None:
            data["rewritten_from"] = self.rewritten_from
        if self.promoted_from is not None:
            data["promoted_from"] = self.promoted_from
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
            actor_role=(
                None if data.get("actor_role") is None else str(data["actor_role"])
            ),
            actor_id=(
                None if data.get("actor_id") is None else str(data["actor_id"])
            ),
            prompt_template=(
                None if data.get("prompt_template") is None else str(data["prompt_template"])
            ),
            agent_family=(
                None if data.get("agent_family") is None else str(data["agent_family"])
            ),
            run_id=None if data.get("run_id") is None else str(data["run_id"]),
            block_id=None if data.get("block_id") is None else str(data["block_id"]),
            step_id=None if data.get("step_id") is None else str(data["step_id"]),
            lineage_id=(
                None if data.get("lineage_id") is None else str(data["lineage_id"])
            ),
            verification_status=(
                None
                if data.get("verification_status") is None
                else str(data["verification_status"])
            ),
            verification_summary=(
                None
                if data.get("verification_summary") is None
                else str(data["verification_summary"])
            ),
            origin_commit=(
                None if data.get("origin_commit") is None else str(data["origin_commit"])
            ),
            rewritten_from=(
                None
                if data.get("rewritten_from") is None
                else str(data["rewritten_from"])
            ),
            promoted_from=(
                None
                if data.get("promoted_from") is None
                else str(data["promoted_from"])
            ),
        )

    @classmethod
    def from_provenance(cls, provenance: ProvenanceRecord) -> "CommitMetadata":
        return cls(
            author=provenance.actor_id,
            committed_at=provenance.committed_at,
            actor_role=provenance.actor_role,
            actor_id=provenance.actor_id,
            prompt_template=provenance.prompt_template,
            agent_family=provenance.agent_family,
            run_id=provenance.run_id,
            block_id=provenance.block_id,
            step_id=provenance.step_id,
            lineage_id=provenance.lineage_id,
            verification_status=provenance.verification_status.value,
            verification_summary=provenance.verification_summary,
            origin_commit=provenance.origin_commit,
            rewritten_from=provenance.rewritten_from,
            promoted_from=provenance.promoted_from,
        )

    def to_provenance(self) -> ProvenanceRecord:
        is_legacy = not any(
            value is not None
            for value in (
                self.actor_role,
                self.actor_id,
                self.prompt_template,
                self.agent_family,
                self.run_id,
                self.block_id,
                self.step_id,
                self.lineage_id,
                self.verification_status,
                self.verification_summary,
                self.origin_commit,
                self.rewritten_from,
                self.promoted_from,
            )
        )
        if is_legacy:
            return ProvenanceRecord.from_legacy_commit_metadata(self.to_dict())
        return ProvenanceRecord(
            actor_role=self.actor_role or "unknown",
            actor_id=self.actor_id or self.author,
            prompt_template=self.prompt_template,
            agent_family=self.agent_family,
            run_id=self.run_id,
            block_id=self.block_id,
            step_id=self.step_id,
            lineage_id=self.lineage_id,
            verification_status=VerificationStatus.coerce(self.verification_status),
            verification_summary=self.verification_summary,
            committed_at=self.committed_at,
            origin_commit=self.origin_commit,
            rewritten_from=self.rewritten_from,
            promoted_from=self.promoted_from,
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
