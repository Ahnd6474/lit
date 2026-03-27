"""Canonical lit v1 contracts for autonomous local workflows. Persisted revision, checkpoint, lineage, verification, artifact, and operation records serialize only through these versioned dataclasses and layout helpers; readers must tolerate legacy v0 commit JSON and absent fields. CLI, GUI, export, and future Jakal Flow adapters talk to a narrow backend API and must not hardcode .lit paths or invent metadata keys independently."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from lit.domain import (
    ApprovalState,
    ArtifactRecord,
    CheckpointRecord,
    LineageRecord,
    OperationRecord,
    ProvenanceRecord,
    RevisionRecord,
    VerificationRecord,
)
from lit.layout import LitLayout


@dataclass(frozen=True, slots=True)
class OpenRepositoryRequest:
    root: Path
    default_branch: str = "main"
    create_if_missing: bool = False


@dataclass(frozen=True, slots=True)
class RepositoryHandle:
    root: Path
    layout: LitLayout
    default_branch: str = "main"
    current_branch: str | None = None
    head_revision: str | None = None
    current_lineage_id: str | None = None
    latest_safe_checkpoint_id: str | None = None
    is_initialized: bool = False

    @classmethod
    def for_root(
        cls,
        root: Path,
        *,
        default_branch: str = "main",
        current_branch: str | None = None,
        head_revision: str | None = None,
        current_lineage_id: str | None = None,
        latest_safe_checkpoint_id: str | None = None,
        is_initialized: bool = False,
    ) -> "RepositoryHandle":
        resolved = root.expanduser().resolve()
        return cls(
            root=resolved,
            layout=LitLayout(resolved),
            default_branch=default_branch,
            current_branch=current_branch,
            head_revision=head_revision,
            current_lineage_id=current_lineage_id,
            latest_safe_checkpoint_id=latest_safe_checkpoint_id,
            is_initialized=is_initialized,
        )


@dataclass(frozen=True, slots=True)
class CreateRevisionRequest:
    root: Path
    message: str
    tree: str | None = None
    parents: tuple[str, ...] = ()
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateCheckpointRequest:
    root: Path
    revision_id: str
    name: str | None = None
    note: str | None = None
    safe: bool = True
    pinned: bool = False
    approval_state: ApprovalState = ApprovalState.NOT_REQUESTED
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateLineageRequest:
    root: Path
    lineage_id: str
    forked_from: str | None = None
    title: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class VerifyRevisionRequest:
    root: Path
    revision_id: str
    command: tuple[str, ...] = ()
    allow_cache: bool = True
    state_fingerprint: str | None = None
    environment_fingerprint: str | None = None
    command_identity: str | None = None


@dataclass(frozen=True, slots=True)
class RollbackRequest:
    root: Path
    checkpoint_id: str | None = None
    use_latest_safe: bool = True


@dataclass(frozen=True, slots=True)
class PromoteLineageRequest:
    root: Path
    lineage_id: str
    destination_lineage_id: str | None = None
    expected_head_revision: str | None = None


class BackendService(ABC):
    @abstractmethod
    def open_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        """Open repository state without mutating storage."""

    @abstractmethod
    def initialize_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        """Create repository metadata and return the initialized handle."""

    @abstractmethod
    def get_repository_state(self, root: Path) -> RepositoryHandle:
        """Return the current repository, branch, revision, and checkpoint pointers."""

    @abstractmethod
    def list_revisions(
        self,
        root: Path,
        *,
        start_revision: str | None = None,
        lineage_id: str | None = None,
    ) -> tuple[RevisionRecord, ...]:
        """List visible revisions for history, export, or orchestration surfaces."""

    @abstractmethod
    def get_revision(self, root: Path, revision_id: str) -> RevisionRecord:
        """Load a single revision record by stable identifier."""

    @abstractmethod
    def create_revision(self, request: CreateRevisionRequest) -> OperationRecord:
        """Persist a revision and any journaled bookkeeping for the operation."""

    @abstractmethod
    def list_checkpoints(
        self,
        root: Path,
        *,
        lineage_id: str | None = None,
        only_safe: bool = False,
    ) -> tuple[CheckpointRecord, ...]:
        """List checkpoint records, optionally filtering to the safe set."""

    @abstractmethod
    def get_checkpoint(self, root: Path, checkpoint_id: str) -> CheckpointRecord:
        """Load one checkpoint by stable identifier."""

    @abstractmethod
    def create_checkpoint(self, request: CreateCheckpointRequest) -> OperationRecord:
        """Create or update a checkpoint record for a revision boundary."""

    @abstractmethod
    def rollback_to_checkpoint(self, request: RollbackRequest) -> OperationRecord:
        """Restore repository state to a selected or latest safe checkpoint."""

    @abstractmethod
    def list_lineages(self, root: Path) -> tuple[LineageRecord, ...]:
        """List all persisted lineages for local parallel work."""

    @abstractmethod
    def get_lineage(self, root: Path, lineage_id: str) -> LineageRecord:
        """Load one lineage record by identifier."""

    @abstractmethod
    def create_lineage(self, request: CreateLineageRequest) -> OperationRecord:
        """Fork a new lineage boundary for isolated autonomous work."""

    @abstractmethod
    def promote_lineage(self, request: PromoteLineageRequest) -> OperationRecord:
        """Promote one lineage into another with journaled provenance."""

    @abstractmethod
    def record_verification(self, request: VerifyRevisionRequest) -> VerificationRecord:
        """Run or replay verification and persist the canonical verification record."""

    @abstractmethod
    def get_verification(self, root: Path, verification_id: str) -> VerificationRecord:
        """Load a previously recorded verification result."""

    @abstractmethod
    def list_artifacts(
        self,
        root: Path,
        *,
        owner_id: str | None = None,
    ) -> tuple[ArtifactRecord, ...]:
        """List artifact metadata for revisions, checkpoints, or verifications."""

    @abstractmethod
    def get_artifact(self, root: Path, artifact_id: str) -> ArtifactRecord:
        """Load a single artifact descriptor without assuming its payload path."""


__all__ = [
    "BackendService",
    "CreateCheckpointRequest",
    "CreateLineageRequest",
    "CreateRevisionRequest",
    "OpenRepositoryRequest",
    "PromoteLineageRequest",
    "RepositoryHandle",
    "RollbackRequest",
    "VerifyRevisionRequest",
]
