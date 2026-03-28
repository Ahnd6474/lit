"""Canonical lit v1 contracts for autonomous local workflows. Persisted revision, checkpoint, lineage, verification, artifact, and operation records serialize only through these versioned dataclasses and layout helpers; readers must tolerate legacy v0 commit JSON and absent fields. CLI, GUI, export, and future Jakal Flow adapters talk to a narrow backend API and must not hardcode .lit paths or invent metadata keys independently."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from lit.commits import CommitMetadata, CommitRecord, serialize_commit
from lit.doctor import DoctorReport, run_doctor
from lit.domain import (
    ApprovalState,
    CheckpointRecord,
    OperationKind,
    OperationRecord,
    OperationStatus,
    ProvenanceRecord,
    RevisionRecord,
    VerificationRecord,
)
from lit.export_git import GitExportPlan, build_git_export_plan
from lit.layout import LitLayout
from lit.storage import write_json
from lit.transactions import next_identifier, utc_now
from lit.verification import VerificationStatusSummary


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
class LineageHandle:
    lineage_id: str
    head_revision: str | None = None
    base_checkpoint_id: str | None = None
    forked_from: str | None = None
    promoted_from: str | None = None
    promoted_to: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    promoted_at: str | None = None
    discarded_at: str | None = None
    last_switched_at: str | None = None
    title: str = ""
    description: str = ""
    status: str = "active"
    checkpoint_ids: tuple[str, ...] = ()
    owned_paths: tuple[str, ...] = ()
    allow_owned_path_overlap_with: tuple[str, ...] = ()

    @classmethod
    def from_managed(cls, lineage: object) -> "LineageHandle":
        return cls(
            lineage_id=lineage.lineage_id,
            head_revision=lineage.head_revision,
            base_checkpoint_id=lineage.base_checkpoint_id,
            forked_from=lineage.forked_from,
            promoted_from=lineage.promoted_from,
            promoted_to=lineage.promoted_to,
            created_at=lineage.created_at,
            updated_at=lineage.updated_at,
            promoted_at=lineage.promoted_at,
            discarded_at=lineage.discarded_at,
            last_switched_at=lineage.last_switched_at,
            title=lineage.title,
            description=lineage.description,
            status=lineage.status.value,
            checkpoint_ids=lineage.checkpoint_ids,
            owned_paths=lineage.owned_paths,
            allow_owned_path_overlap_with=lineage.allow_owned_path_overlap_with,
        )


@dataclass(frozen=True, slots=True)
class ArtifactLinkHandle:
    owner_kind: str
    owner_id: str
    relationship: str = "attached"
    note: str | None = None
    linked_at: str | None = None

    @classmethod
    def from_link(cls, link: object) -> "ArtifactLinkHandle":
        return cls(
            owner_kind=link.owner_kind,
            owner_id=link.owner_id,
            relationship=link.relationship,
            note=link.note,
            linked_at=link.linked_at,
        )


@dataclass(frozen=True, slots=True)
class ArtifactHandle:
    artifact_id: str | None = None
    owner_kind: str = "revision"
    owner_id: str | None = None
    kind: str = "generic"
    relative_path: str = ""
    content_type: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None
    pinned: bool = False
    links: tuple[ArtifactLinkHandle, ...] = ()

    @classmethod
    def from_manifest(cls, manifest: object) -> "ArtifactHandle":
        return cls(
            artifact_id=manifest.artifact_id,
            owner_kind=manifest.owner_kind,
            owner_id=manifest.owner_id,
            kind=manifest.kind,
            relative_path=manifest.relative_path,
            content_type=manifest.content_type,
            digest=manifest.digest,
            size_bytes=manifest.size_bytes,
            created_at=manifest.created_at,
            pinned=manifest.pinned,
            links=tuple(ArtifactLinkHandle.from_link(link) for link in manifest.all_links),
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
    approval_note: str | None = None
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CreateLineageRequest:
    root: Path
    lineage_id: str
    forked_from: str | None = None
    base_checkpoint_id: str | None = None
    owned_paths: tuple[str, ...] = ()
    allow_owned_path_overlap_with: tuple[str, ...] = ()
    title: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class VerifyRevisionRequest:
    root: Path
    revision_id: str
    definition_name: str | None = None
    command: tuple[str, ...] = ()
    allow_cache: bool = True
    state_fingerprint: str | None = None
    environment_fingerprint: str | None = None
    command_identity: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationStatusRequest:
    root: Path
    owner_kind: str
    owner_id: str | None
    linked_verification_id: str | None = None
    state_fingerprint: str | None = None
    environment_fingerprint: str | None = None
    command_identity: str | None = None


@dataclass(frozen=True, slots=True)
class RollbackRequest:
    root: Path
    checkpoint_id: str | None = None
    use_latest_safe: bool = True
    lineage_id: str | None = None


@dataclass(frozen=True, slots=True)
class PromoteLineageRequest:
    root: Path
    lineage_id: str
    destination_lineage_id: str | None = None
    expected_head_revision: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewPromotionRequest:
    root: Path
    lineage_id: str
    destination_lineage_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiscardLineageRequest:
    root: Path
    lineage_id: str


@dataclass(frozen=True, slots=True)
class ArtifactLinkRequest:
    root: Path
    artifact_id: str
    owner_kind: str
    owner_id: str
    relationship: str = "attached"
    note: str | None = None
    pinned: bool | None = None


@dataclass(frozen=True, slots=True)
class DoctorRequest:
    root: Path
    repair: bool = False


@dataclass(frozen=True, slots=True)
class GitExportRequest:
    root: Path
    start_revision: str | None = None
    lineage_id: str | None = None


class BackendService(ABC):
    @abstractmethod
    def open_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        """Open repository state, optionally creating the repository when requested."""

    @abstractmethod
    def initialize_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        """Create repository metadata and return the initialized handle."""

    @abstractmethod
    def get_repository_state(self, root: Path) -> RepositoryHandle:
        """Return the current repository, branch, revision, and checkpoint pointers."""

    @abstractmethod
    def get_current_revision(self, root: Path) -> RevisionRecord | None:
        """Resolve the currently checked out revision record."""

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
    def list_changed_files(
        self,
        root: Path,
        revision_id: str | None,
        *,
        since_revision: str | None = None,
    ) -> tuple[str, ...]:
        """List the files changed by a revision compared with its baseline."""

    @abstractmethod
    def create_revision(self, request: CreateRevisionRequest) -> OperationRecord:
        """Persist a revision and any bookkeeping for the operation."""

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
    def get_latest_safe_checkpoint(
        self,
        root: Path,
        *,
        lineage_id: str | None = None,
    ) -> CheckpointRecord | None:
        """Resolve the most recent safe checkpoint, optionally scoped to a lineage."""

    @abstractmethod
    def create_checkpoint(self, request: CreateCheckpointRequest) -> OperationRecord:
        """Create or update a checkpoint record for a revision boundary."""

    @abstractmethod
    def rollback_to_checkpoint(self, request: RollbackRequest) -> OperationRecord:
        """Restore repository state to a selected or latest safe checkpoint."""

    @abstractmethod
    def list_lineages(
        self,
        root: Path,
        *,
        include_inactive: bool = True,
    ) -> tuple[LineageHandle, ...]:
        """List all persisted lineages for local parallel work."""

    @abstractmethod
    def get_lineage(self, root: Path, lineage_id: str) -> LineageHandle:
        """Load one lineage record by identifier."""

    @abstractmethod
    def create_lineage(self, request: CreateLineageRequest) -> OperationRecord:
        """Fork a new lineage boundary for isolated autonomous work."""

    @abstractmethod
    def preview_lineage_promotion(self, request: PreviewPromotionRequest) -> object:
        """Preview conflicts before a lineage promotion mutates repository state."""

    @abstractmethod
    def promote_lineage(self, request: PromoteLineageRequest) -> OperationRecord:
        """Promote one lineage into another with provenance-aware bookkeeping."""

    @abstractmethod
    def discard_lineage(self, request: DiscardLineageRequest) -> LineageHandle:
        """Discard an inactive lineage and remove its branch reservation."""

    @abstractmethod
    def record_verification(self, request: VerifyRevisionRequest) -> VerificationRecord:
        """Run or replay verification and persist the canonical verification record."""

    @abstractmethod
    def get_verification(self, root: Path, verification_id: str) -> VerificationRecord:
        """Load a previously recorded verification result."""

    @abstractmethod
    def get_verification_status(self, request: VerificationStatusRequest) -> VerificationStatusSummary:
        """Summarize verification state for a revision, checkpoint, or lineage boundary."""

    @abstractmethod
    def list_artifacts(
        self,
        root: Path,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[ArtifactHandle, ...]:
        """List artifact metadata and linkage without exposing storage internals."""

    @abstractmethod
    def get_artifact(self, root: Path, artifact_id: str) -> ArtifactHandle:
        """Load a single artifact descriptor without assuming its payload path."""

    @abstractmethod
    def link_artifact(self, request: ArtifactLinkRequest) -> ArtifactHandle:
        """Attach an existing artifact to a revision, checkpoint, lineage, or verification."""

    @abstractmethod
    def doctor(self, request: DoctorRequest) -> DoctorReport:
        """Inspect repository health and optionally repair unfinished transactions."""

    @abstractmethod
    def export_git(self, request: GitExportRequest) -> GitExportPlan:
        """Project the current lit history onto Git-facing refs and provenance trailers."""


class LitBackendService(BackendService):
    def open_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        from lit.repository import Repository

        root = request.root.expanduser().resolve()
        if request.create_if_missing and not (root / ".lit").is_dir():
            return self.initialize_repository(request)
        if not (root / ".lit").is_dir():
            return RepositoryHandle.for_root(
                root,
                default_branch=request.default_branch,
                is_initialized=False,
            )
        return self._handle_for_repository(Repository.open(root))

    def initialize_repository(self, request: OpenRepositoryRequest) -> RepositoryHandle:
        from lit.repository import Repository

        repo = Repository.create(
            request.root.expanduser().resolve(),
            default_branch=request.default_branch,
        )
        return self._handle_for_repository(repo)

    def get_repository_state(self, root: Path) -> RepositoryHandle:
        from lit.repository import Repository

        return self._handle_for_repository(Repository.open(root))

    def get_current_revision(self, root: Path) -> RevisionRecord | None:
        return self._repository(root).current_revision()

    def list_revisions(
        self,
        root: Path,
        *,
        start_revision: str | None = None,
        lineage_id: str | None = None,
    ) -> tuple[RevisionRecord, ...]:
        return self._repository(root).list_revisions(
            start_revision=start_revision,
            lineage_id=lineage_id,
        )

    def get_revision(self, root: Path, revision_id: str) -> RevisionRecord:
        return self._repository(root).get_revision(revision_id)

    def list_changed_files(
        self,
        root: Path,
        revision_id: str | None,
        *,
        since_revision: str | None = None,
    ) -> tuple[str, ...]:
        return self._repository(root).changed_files(
            revision_id,
            since_revision=since_revision,
        )

    def create_revision(self, request: CreateRevisionRequest) -> OperationRecord:
        repo = self._repository(request.root)
        if request.tree is None:
            revision_id = repo.commit(
                request.message,
                parents=request.parents or None,
                provenance=request.provenance,
                artifact_ids=request.artifact_ids,
            )
        else:
            revision_id = self._commit_tree(repo, request)
        self._link_artifacts(
            repo,
            owner_kind="revision",
            owner_id=revision_id,
            artifact_ids=request.artifact_ids,
        )
        revision = repo.get_revision(revision_id)
        return self._persist_operation(
            repo,
            kind=OperationKind.COMMIT,
            revision_id=revision_id,
            artifact_ids=request.artifact_ids,
            lineage_id=revision.provenance.lineage_id,
            message=request.message,
        )

    def list_checkpoints(
        self,
        root: Path,
        *,
        lineage_id: str | None = None,
        only_safe: bool = False,
    ) -> tuple[CheckpointRecord, ...]:
        return self._repository(root).list_checkpoints(
            lineage_id=lineage_id,
            only_safe=only_safe,
        )

    def get_checkpoint(self, root: Path, checkpoint_id: str) -> CheckpointRecord:
        return self._repository(root).get_checkpoint(checkpoint_id)

    def get_latest_safe_checkpoint(
        self,
        root: Path,
        *,
        lineage_id: str | None = None,
    ) -> CheckpointRecord | None:
        return self._repository(root).latest_safe_checkpoint(lineage_id=lineage_id)

    def create_checkpoint(self, request: CreateCheckpointRequest) -> OperationRecord:
        repo = self._repository(request.root)
        checkpoint = repo.create_checkpoint(
            revision_id=request.revision_id,
            name=request.name,
            note=request.note,
            safe=request.safe,
            pinned=request.pinned,
            approval_state=request.approval_state,
            approval_note=request.approval_note,
            provenance=request.provenance,
            artifact_ids=request.artifact_ids,
        )
        self._link_artifacts(
            repo,
            owner_kind="checkpoint",
            owner_id=checkpoint.checkpoint_id or "",
            artifact_ids=request.artifact_ids,
        )
        return self._persist_operation(
            repo,
            kind=OperationKind.CHECKPOINT,
            revision_id=checkpoint.revision_id,
            checkpoint_id=checkpoint.checkpoint_id,
            verification_id=checkpoint.verification_id,
            artifact_ids=request.artifact_ids,
            lineage_id=checkpoint.provenance.lineage_id,
            message=checkpoint.name or checkpoint.note or "created checkpoint",
        )

    def rollback_to_checkpoint(self, request: RollbackRequest) -> OperationRecord:
        repo = self._repository(request.root)
        checkpoint = repo.rollback_to_checkpoint(
            request.checkpoint_id,
            use_latest_safe=request.use_latest_safe,
            lineage_id=request.lineage_id,
        )
        return self._persist_operation(
            repo,
            kind=OperationKind.ROLLBACK,
            revision_id=checkpoint.revision_id,
            checkpoint_id=checkpoint.checkpoint_id,
            verification_id=checkpoint.verification_id,
            artifact_ids=checkpoint.artifact_ids,
            lineage_id=checkpoint.provenance.lineage_id,
            message=checkpoint.name or checkpoint.note or "rolled back to checkpoint",
        )

    def list_lineages(
        self,
        root: Path,
        *,
        include_inactive: bool = True,
    ) -> tuple[LineageHandle, ...]:
        repo = self._repository(root)
        return tuple(
            LineageHandle.from_managed(lineage)
            for lineage in repo.list_managed_lineages(include_inactive=include_inactive)
        )

    def get_lineage(self, root: Path, lineage_id: str) -> LineageHandle:
        return LineageHandle.from_managed(self._repository(root).get_managed_lineage(lineage_id))

    def create_lineage(self, request: CreateLineageRequest) -> OperationRecord:
        repo = self._repository(request.root)
        lineage = repo.create_lineage(
            request.lineage_id,
            forked_from=request.forked_from,
            base_checkpoint_id=request.base_checkpoint_id,
            owned_paths=request.owned_paths,
            allow_owned_path_overlap_with=request.allow_owned_path_overlap_with,
            title=request.title,
            description=request.description,
        )
        return self._persist_operation(
            repo,
            kind=OperationKind.CREATE_LINEAGE,
            revision_id=lineage.head_revision,
            checkpoint_id=lineage.base_checkpoint_id,
            lineage_id=lineage.lineage_id,
            message=request.description or request.title or f"created lineage {request.lineage_id}",
        )

    def preview_lineage_promotion(self, request: PreviewPromotionRequest) -> object:
        return self._repository(request.root).preview_promotion_conflicts(
            request.lineage_id,
            request.destination_lineage_id,
        )

    def promote_lineage(self, request: PromoteLineageRequest) -> OperationRecord:
        repo = self._repository(request.root)
        result = repo.promote_lineage(
            request.lineage_id,
            destination_lineage_id=request.destination_lineage_id,
            expected_head_revision=request.expected_head_revision,
        )
        return self._persist_operation(
            repo,
            kind=OperationKind.PROMOTE_LINEAGE,
            revision_id=result.destination.head_revision,
            checkpoint_id=result.destination.base_checkpoint_id,
            lineage_id=result.destination.lineage_id,
            message=f"promoted {result.source.lineage_id} to {result.destination.lineage_id}",
        )

    def discard_lineage(self, request: DiscardLineageRequest) -> LineageHandle:
        lineage = self._repository(request.root).discard_lineage(request.lineage_id)
        return LineageHandle.from_managed(lineage)

    def record_verification(self, request: VerifyRevisionRequest) -> VerificationRecord:
        repo = self._repository(request.root)
        revision = repo.get_revision(request.revision_id)
        state_fingerprint = request.state_fingerprint or revision.tree
        return repo.run_verification(
            owner_kind="revision",
            owner_id=revision.revision_id,
            definition_name=request.definition_name,
            command=request.command,
            command_identity=request.command_identity,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=request.environment_fingerprint,
            allow_cache=request.allow_cache,
        )

    def get_verification(self, root: Path, verification_id: str) -> VerificationRecord:
        return self._repository(root).get_verification(verification_id)

    def get_verification_status(self, request: VerificationStatusRequest) -> VerificationStatusSummary:
        return self._repository(request.root).verification_status(
            owner_kind=request.owner_kind,
            owner_id=request.owner_id,
            linked_verification_id=request.linked_verification_id,
            state_fingerprint=request.state_fingerprint,
            environment_fingerprint=request.environment_fingerprint,
            command_identity=request.command_identity,
        )

    def list_artifacts(
        self,
        root: Path,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[ArtifactHandle, ...]:
        repo = self._repository(root)
        return tuple(
            ArtifactHandle.from_manifest(manifest)
            for manifest in repo.list_artifact_manifests(
                owner_kind=owner_kind,
                owner_id=owner_id,
            )
        )

    def get_artifact(self, root: Path, artifact_id: str) -> ArtifactHandle:
        manifest = self._repository(root).get_artifact_manifest(artifact_id)
        return ArtifactHandle.from_manifest(manifest)

    def link_artifact(self, request: ArtifactLinkRequest) -> ArtifactHandle:
        manifest = self._repository(request.root).link_artifact(
            request.artifact_id,
            owner_kind=request.owner_kind,
            owner_id=request.owner_id,
            relationship=request.relationship,
            note=request.note,
            pinned=request.pinned,
        )
        return ArtifactHandle.from_manifest(manifest)

    def doctor(self, request: DoctorRequest) -> DoctorReport:
        return run_doctor(request.root, repair=request.repair)

    def export_git(self, request: GitExportRequest) -> GitExportPlan:
        return build_git_export_plan(
            request.root,
            start_revision=request.start_revision,
            lineage_id=request.lineage_id,
        )

    def _repository(self, root: Path):
        from lit.repository import Repository

        return Repository.open(root.expanduser().resolve())

    def _handle_for_repository(self, repo) -> RepositoryHandle:
        current_branch = repo.current_branch_name()
        return RepositoryHandle.for_root(
            repo.root,
            default_branch=repo.config.default_branch,
            current_branch=current_branch,
            head_revision=repo.current_commit_id(),
            current_lineage_id=current_branch,
            latest_safe_checkpoint_id=repo.latest_safe_checkpoint_id(lineage_id=current_branch)
            or repo.latest_safe_checkpoint_id(),
            is_initialized=True,
        )

    def _link_artifacts(
        self,
        repo,
        *,
        owner_kind: str,
        owner_id: str,
        artifact_ids: tuple[str, ...],
    ) -> None:
        if not artifact_ids:
            return
        for artifact_id in artifact_ids:
            repo.link_artifact(
                artifact_id,
                owner_kind=owner_kind,
                owner_id=owner_id,
            )

    def _commit_tree(self, repo, request: CreateRevisionRequest) -> str:
        if not request.tree:
            raise ValueError("tree object id is required for direct revision creation")
        repo.read_object("trees", request.tree)
        normalized = repo._normalize_provenance(request.provenance)
        head_revision = repo.current_commit_id()
        parents = request.parents or (() if head_revision is None else (head_revision,))
        record = CommitRecord(
            tree=request.tree,
            parents=parents,
            message=request.message,
            metadata=CommitMetadata.from_provenance(normalized),
        )
        revision_id = repo.store_object("commits", serialize_commit(record))
        write_json(
            repo.layout.revision_path(revision_id),
            RevisionRecord(
                revision_id=revision_id,
                tree=request.tree,
                parents=parents,
                message=request.message,
                provenance=normalized,
                artifact_ids=request.artifact_ids,
            ).to_dict(),
        )
        branch_name = repo.current_branch_name()
        if branch_name is None:
            raise RuntimeError("revisions require HEAD to point to a branch")
        repo.write_branch(branch_name, revision_id)
        if normalized.lineage_id is not None:
            repo._ensure_lineage(normalized.lineage_id, head_revision=revision_id)
        return revision_id

    def _persist_operation(
        self,
        repo,
        *,
        kind: OperationKind,
        revision_id: str | None = None,
        checkpoint_id: str | None = None,
        verification_id: str | None = None,
        artifact_ids: tuple[str, ...] = (),
        lineage_id: str | None = None,
        message: str | None = None,
    ) -> OperationRecord:
        now = utc_now()
        record = OperationRecord(
            operation_id=next_identifier(kind.value),
            kind=kind,
            status=OperationStatus.SUCCEEDED,
            repository_root=repo.root.as_posix(),
            lineage_id=lineage_id,
            revision_id=revision_id,
            checkpoint_id=checkpoint_id,
            verification_id=verification_id,
            artifact_ids=artifact_ids,
            started_at=now,
            finished_at=now,
            message=message,
        )
        write_json(repo.layout.operation_path(record.operation_id or ""), record.to_dict())
        return record


__all__ = [
    "ArtifactHandle",
    "ArtifactLinkHandle",
    "ArtifactLinkRequest",
    "BackendService",
    "CreateCheckpointRequest",
    "CreateLineageRequest",
    "CreateRevisionRequest",
    "DiscardLineageRequest",
    "DoctorRequest",
    "GitExportRequest",
    "LineageHandle",
    "LitBackendService",
    "OpenRepositoryRequest",
    "PreviewPromotionRequest",
    "PromoteLineageRequest",
    "RepositoryHandle",
    "RollbackRequest",
    "VerificationStatusRequest",
    "VerifyRevisionRequest",
]
