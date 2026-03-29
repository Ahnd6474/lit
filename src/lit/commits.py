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
        for key in _OPTIONAL_METADATA_FIELDS:
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "CommitMetadata":
        if not data:
            return cls()
        metadata = {"author": str(data.get("author", "lit"))}
        metadata.update(
            (key, None if data.get(key) is None else str(data[key]))
            for key in _OPTIONAL_METADATA_FIELDS
        )
        return cls(**metadata)

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


_OPTIONAL_METADATA_FIELDS = (
    "committed_at",
    "actor_role",
    "actor_id",
    "prompt_template",
    "agent_family",
    "run_id",
    "block_id",
    "step_id",
    "lineage_id",
    "verification_status",
    "verification_summary",
    "origin_commit",
    "rewritten_from",
    "promoted_from",
)
