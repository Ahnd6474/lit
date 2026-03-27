"""Canonical lit v1 contracts for autonomous local workflows. Persisted revision, checkpoint, lineage, verification, artifact, and operation records serialize only through these versioned dataclasses and layout helpers; readers must tolerate legacy v0 commit JSON and absent fields. CLI, GUI, export, and future Jakal Flow adapters talk to a narrow backend API and must not hardcode .lit paths or invent metadata keys independently."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

DOMAIN_SCHEMA_VERSION = 1
LEGACY_COMMIT_SCHEMA_VERSION = 0

_PROVENANCE_FIELD_NAMES = frozenset(
    {
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
        "committed_at",
        "origin_commit",
        "rewritten_from",
        "promoted_from",
    }
)


def _string(value: object | None, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Path)):
        return (str(value),)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def _optional_int(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _default_schema_version(data: Mapping[str, object]) -> int:
    if "schema_version" in data:
        return int(data["schema_version"])
    if "metadata" in data and "provenance" not in data:
        return LEGACY_COMMIT_SCHEMA_VERSION
    return DOMAIN_SCHEMA_VERSION


def _serialize_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return {
            field_info.name: _serialize_value(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    return value


class VerificationStatus(StrEnum):
    NEVER_VERIFIED = "never_verified"
    PASSED = "passed"
    FAILED = "failed"
    CACHED_PASS = "cached_pass"
    CACHED_FAIL = "cached_fail"
    STALE = "stale"

    @classmethod
    def coerce(cls, value: object | None) -> "VerificationStatus":
        if value is None:
            return cls.NEVER_VERIFIED
        try:
            return cls(str(value))
        except ValueError:
            return cls.NEVER_VERIFIED


class ApprovalState(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    @classmethod
    def coerce(cls, value: object | None) -> "ApprovalState":
        if value is None:
            return cls.NOT_REQUESTED
        try:
            return cls(str(value))
        except ValueError:
            return cls.NOT_REQUESTED


class OperationKind(StrEnum):
    COMMIT = "commit"
    CHECKPOINT = "checkpoint"
    ROLLBACK = "rollback"
    MERGE = "merge"
    REBASE = "rebase"
    PROMOTE_LINEAGE = "promote_lineage"
    VERIFY = "verify"
    CREATE_LINEAGE = "create_lineage"

    @classmethod
    def coerce(cls, value: object | None) -> "OperationKind":
        if value is None:
            return cls.COMMIT
        try:
            return cls(str(value))
        except ValueError:
            return cls.COMMIT


class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def coerce(cls, value: object | None) -> "OperationStatus":
        if value is None:
            return cls.QUEUED
        try:
            return cls(str(value))
        except ValueError:
            return cls.QUEUED


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    actor_role: str = "unknown"
    actor_id: str = "lit"
    prompt_template: str | None = None
    agent_family: str | None = None
    run_id: str | None = None
    block_id: str | None = None
    step_id: str | None = None
    lineage_id: str | None = None
    verification_status: VerificationStatus = VerificationStatus.NEVER_VERIFIED
    verification_summary: str | None = None
    committed_at: str | None = None
    origin_commit: str | None = None
    rewritten_from: str | None = None
    promoted_from: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ProvenanceRecord":
        if not data:
            return cls()
        return cls(
            actor_role=_string(data.get("actor_role"), default="unknown"),
            actor_id=_string(data.get("actor_id"), default="lit"),
            prompt_template=_optional_string(data.get("prompt_template")),
            agent_family=_optional_string(data.get("agent_family")),
            run_id=_optional_string(data.get("run_id")),
            block_id=_optional_string(data.get("block_id")),
            step_id=_optional_string(data.get("step_id")),
            lineage_id=_optional_string(data.get("lineage_id")),
            verification_status=VerificationStatus.coerce(data.get("verification_status")),
            verification_summary=_optional_string(data.get("verification_summary")),
            committed_at=_optional_string(data.get("committed_at")),
            origin_commit=_optional_string(data.get("origin_commit")),
            rewritten_from=_optional_string(data.get("rewritten_from")),
            promoted_from=_optional_string(data.get("promoted_from")),
        )

    @classmethod
    def from_legacy_commit_metadata(
        cls,
        data: Mapping[str, object] | None,
    ) -> "ProvenanceRecord":
        if not data:
            return cls(actor_role="legacy", actor_id="lit")
        return cls(
            actor_role="legacy",
            actor_id=_string(data.get("author"), default="lit"),
            committed_at=_optional_string(data.get("committed_at")),
        )


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    revision_id: str | None = None
    tree: str = ""
    parents: tuple[str, ...] = ()
    message: str = ""
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    verification_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RevisionRecord":
        if not data:
            return cls()
        raw_provenance = data.get("provenance")
        if isinstance(raw_provenance, Mapping):
            provenance = ProvenanceRecord.from_dict(raw_provenance)
        elif any(name in data for name in _PROVENANCE_FIELD_NAMES):
            provenance = ProvenanceRecord.from_dict(data)
        else:
            legacy_metadata = data.get("metadata")
            provenance = ProvenanceRecord.from_legacy_commit_metadata(
                legacy_metadata if isinstance(legacy_metadata, Mapping) else None
            )
        return cls(
            schema_version=_default_schema_version(data),
            revision_id=_optional_string(data.get("revision_id")),
            tree=_string(data.get("tree"), default=_string(data.get("tree_id"))),
            parents=_string_tuple(data.get("parents")),
            message=_string(data.get("message")),
            provenance=provenance,
            verification_id=_optional_string(data.get("verification_id")),
            artifact_ids=_string_tuple(data.get("artifact_ids")),
            checkpoint_ids=_string_tuple(data.get("checkpoint_ids")),
        )


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    checkpoint_id: str | None = None
    revision_id: str | None = None
    name: str | None = None
    note: str | None = None
    created_at: str | None = None
    safe: bool = False
    pinned: bool = False
    approval_state: ApprovalState = ApprovalState.NOT_REQUESTED
    approval_note: str | None = None
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    verification_id: str | None = None
    artifact_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "CheckpointRecord":
        if not data:
            return cls()
        raw_provenance = data.get("provenance")
        return cls(
            schema_version=_default_schema_version(data),
            checkpoint_id=_optional_string(data.get("checkpoint_id")),
            revision_id=_optional_string(data.get("revision_id")),
            name=_optional_string(data.get("name")),
            note=_optional_string(data.get("note")),
            created_at=_optional_string(data.get("created_at")),
            safe=bool(data.get("safe", False)),
            pinned=bool(data.get("pinned", False)),
            approval_state=ApprovalState.coerce(data.get("approval_state")),
            approval_note=_optional_string(data.get("approval_note")),
            provenance=ProvenanceRecord.from_dict(
                raw_provenance if isinstance(raw_provenance, Mapping) else data
            ),
            verification_id=_optional_string(data.get("verification_id")),
            artifact_ids=_string_tuple(data.get("artifact_ids")),
        )


@dataclass(frozen=True, slots=True)
class LineageRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    lineage_id: str = "main"
    head_revision: str | None = None
    forked_from: str | None = None
    promoted_from: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    title: str = ""
    description: str = ""
    checkpoint_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "LineageRecord":
        if not data:
            return cls()
        return cls(
            schema_version=_default_schema_version(data),
            lineage_id=_string(data.get("lineage_id"), default="main"),
            head_revision=_optional_string(data.get("head_revision")),
            forked_from=_optional_string(data.get("forked_from")),
            promoted_from=_optional_string(data.get("promoted_from")),
            created_at=_optional_string(data.get("created_at")),
            updated_at=_optional_string(data.get("updated_at")),
            title=_string(data.get("title")),
            description=_string(data.get("description")),
            checkpoint_ids=_string_tuple(data.get("checkpoint_ids")),
        )


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    verification_id: str | None = None
    owner_kind: str = "revision"
    owner_id: str | None = None
    status: VerificationStatus = VerificationStatus.NEVER_VERIFIED
    summary: str | None = None
    state_fingerprint: str | None = None
    environment_fingerprint: str | None = None
    command_identity: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    output_artifact_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "VerificationRecord":
        if not data:
            return cls()
        return cls(
            schema_version=_default_schema_version(data),
            verification_id=_optional_string(data.get("verification_id")),
            owner_kind=_string(data.get("owner_kind"), default="revision"),
            owner_id=_optional_string(data.get("owner_id")),
            status=VerificationStatus.coerce(data.get("status")),
            summary=_optional_string(data.get("summary")),
            state_fingerprint=_optional_string(data.get("state_fingerprint")),
            environment_fingerprint=_optional_string(data.get("environment_fingerprint")),
            command_identity=_optional_string(data.get("command_identity")),
            started_at=_optional_string(data.get("started_at")),
            finished_at=_optional_string(data.get("finished_at")),
            return_code=_optional_int(data.get("return_code")),
            output_artifact_ids=_string_tuple(data.get("output_artifact_ids")),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    artifact_id: str | None = None
    owner_kind: str = "revision"
    owner_id: str | None = None
    kind: str = "generic"
    relative_path: str = ""
    content_type: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactRecord":
        if not data:
            return cls()
        return cls(
            schema_version=_default_schema_version(data),
            artifact_id=_optional_string(data.get("artifact_id")),
            owner_kind=_string(data.get("owner_kind"), default="revision"),
            owner_id=_optional_string(data.get("owner_id")),
            kind=_string(data.get("kind"), default="generic"),
            relative_path=_string(data.get("relative_path")),
            content_type=_optional_string(data.get("content_type")),
            digest=_optional_string(data.get("digest")),
            size_bytes=_optional_int(data.get("size_bytes")),
            created_at=_optional_string(data.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class OperationRecord:
    schema_version: int = DOMAIN_SCHEMA_VERSION
    operation_id: str | None = None
    kind: OperationKind = OperationKind.COMMIT
    status: OperationStatus = OperationStatus.QUEUED
    repository_root: str | None = None
    lineage_id: str | None = None
    revision_id: str | None = None
    checkpoint_id: str | None = None
    verification_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    journal_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return _serialize_value(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "OperationRecord":
        if not data:
            return cls()
        return cls(
            schema_version=_default_schema_version(data),
            operation_id=_optional_string(data.get("operation_id")),
            kind=OperationKind.coerce(data.get("kind")),
            status=OperationStatus.coerce(data.get("status")),
            repository_root=_optional_string(data.get("repository_root")),
            lineage_id=_optional_string(data.get("lineage_id")),
            revision_id=_optional_string(data.get("revision_id")),
            checkpoint_id=_optional_string(data.get("checkpoint_id")),
            verification_id=_optional_string(data.get("verification_id")),
            artifact_ids=_string_tuple(data.get("artifact_ids")),
            journal_path=_optional_string(data.get("journal_path")),
            started_at=_optional_string(data.get("started_at")),
            finished_at=_optional_string(data.get("finished_at")),
            message=_optional_string(data.get("message")),
        )


__all__ = [
    "DOMAIN_SCHEMA_VERSION",
    "LEGACY_COMMIT_SCHEMA_VERSION",
    "ApprovalState",
    "ArtifactRecord",
    "CheckpointRecord",
    "LineageRecord",
    "OperationKind",
    "OperationRecord",
    "OperationStatus",
    "ProvenanceRecord",
    "RevisionRecord",
    "VerificationRecord",
    "VerificationStatus",
]
