"""Machine-facing lit CLI and backend surfaces serialize through typed contracts here. JSON keys, exit codes, provenance input fields, workspace identity fields, step policy fields, and operation projection fields are stable automation interfaces; commands may add human rendering, but they must not invent divergent shapes or infer workspace state from filesystem layout alone."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from lit.config import LitConfig, read_lit_config
from lit.commits import CommitMetadata, CommitRecord, serialize_commit
from lit.doctor import DoctorReport, run_doctor
from lit.domain import (
    ApprovalState,
    CheckpointRecord,
    LineageScopeKind,
    LineageScopeRecord,
    OperationKind,
    OperationRecord,
    OperationStatus,
    ProvenanceRecord,
    RepositoryBlockageReason,
    RepositorySnapshotRecord,
    RevisionRecord,
    ResumeOperationRecord,
    StepPolicyRecord,
    StepRecord,
    VerificationRecord,
    WorkspaceRecord,
)
from lit.export_git import GitExportPlan, build_git_export_plan
from lit.layout import LitLayout
from lit.refs import branch_name_from_ref
from lit.state import OperationState
from lit.storage import write_json
from lit.transactions import next_identifier, utc_now
from lit.verification import VerificationStatusSummary
from lit.workflows import MergeResult, RebaseResult, WorkflowService


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
    policy: LitConfig = field(default_factory=LitConfig)
    snapshot: RepositorySnapshotRecord | None = None

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
        policy: LitConfig | None = None,
        snapshot: RepositorySnapshotRecord | None = None,
    ) -> "RepositoryHandle":
        resolved = root.expanduser().resolve()
        effective_policy = policy or LitConfig(default_branch=default_branch)
        effective_snapshot = snapshot or RepositorySnapshotRecord(
            repository_root=resolved.as_posix(),
            dot_lit_dir=LitLayout(resolved).dot_lit.as_posix(),
            is_initialized=is_initialized,
            default_branch=effective_policy.default_branch,
            current_branch=current_branch,
            current_lineage_id=current_lineage_id,
            head_revision=head_revision,
            latest_safe_checkpoint_id=latest_safe_checkpoint_id,
            safe_rollback_checkpoint_id=latest_safe_checkpoint_id,
            affected_lineage_scope=LineageScopeRecord(
                scope_kind=LineageScopeKind.CURRENT
                if current_lineage_id is not None
                else LineageScopeKind.NONE,
                primary_lineage_id=current_lineage_id,
                lineage_ids=()
                if current_lineage_id is None
                else (current_lineage_id,),
            ),
        )
        return cls(
            root=resolved,
            layout=LitLayout(resolved),
            default_branch=effective_snapshot.default_branch,
            current_branch=effective_snapshot.current_branch,
            head_revision=effective_snapshot.head_revision,
            current_lineage_id=effective_snapshot.current_lineage_id,
            latest_safe_checkpoint_id=effective_snapshot.latest_safe_checkpoint_id,
            is_initialized=effective_snapshot.is_initialized,
            policy=effective_policy,
            snapshot=effective_snapshot,
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
class WorkspaceHandle:
    workspace_id: str | None = None
    lineage_id: str | None = None
    repository_root: Path | None = None
    workspace_root: Path | None = None
    head_revision: str | None = None
    materialized_revision_id: str | None = None
    base_checkpoint_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_record(cls, record: WorkspaceRecord) -> "WorkspaceHandle":
        return cls(
            workspace_id=record.workspace_id,
            lineage_id=record.lineage_id,
            repository_root=None if record.repository_root is None else Path(record.repository_root),
            workspace_root=None if record.workspace_root is None else Path(record.workspace_root),
            head_revision=record.head_revision,
            materialized_revision_id=record.materialized_revision_id,
            base_checkpoint_id=record.base_checkpoint_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


@dataclass(frozen=True, slots=True)
class StepHandle:
    step_id: str | None = None
    run_id: str | None = None
    block_id: str | None = None
    lineage_id: str | None = None
    workspace_id: str | None = None
    head_revision: str | None = None
    checkpoint_id: str | None = None
    operation_ids: tuple[str, ...] = ()
    policy: StepPolicyRecord = field(default_factory=StepPolicyRecord)

    @classmethod
    def from_record(cls, record: StepRecord) -> "StepHandle":
        return cls(
            step_id=record.step_id,
            run_id=record.run_id,
            block_id=record.block_id,
            lineage_id=record.lineage_id,
            workspace_id=record.workspace_id,
            head_revision=record.head_revision,
            checkpoint_id=record.checkpoint_id,
            operation_ids=record.operation_ids,
            policy=record.policy,
        )


@dataclass(frozen=True, slots=True)
class OperationProjection:
    operation_id: str | None = None
    kind: OperationKind = OperationKind.COMMIT
    status: OperationStatus = OperationStatus.QUEUED
    repository_root: Path | None = None
    workspace_id: str | None = None
    step_id: str | None = None
    lineage_id: str | None = None
    revision_id: str | None = None
    checkpoint_id: str | None = None
    verification_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    journal_path: Path | None = None
    journal_dir: Path | None = None
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None

    @classmethod
    def from_record(cls, record: OperationRecord) -> "OperationProjection":
        return cls(
            operation_id=record.operation_id,
            kind=record.kind,
            status=record.status,
            repository_root=None if record.repository_root is None else Path(record.repository_root),
            workspace_id=record.workspace_id,
            step_id=record.step_id,
            lineage_id=record.lineage_id,
            revision_id=record.revision_id,
            checkpoint_id=record.checkpoint_id,
            verification_id=record.verification_id,
            artifact_ids=record.artifact_ids,
            journal_path=None if record.journal_path is None else Path(record.journal_path),
            journal_dir=None if record.journal_dir is None else Path(record.journal_dir),
            started_at=record.started_at,
            finished_at=record.finished_at,
            message=record.message,
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
    def get_repository_snapshot(self, root: Path) -> RepositorySnapshotRecord:
        """Return the canonical repository snapshot for CLI, GUI, and orchestration surfaces."""

    @abstractmethod
    def get_resume_state(self, root: Path) -> ResumeOperationRecord | None:
        """Return the resumable merge/rebase descriptor when work is blocked or in progress."""

    @abstractmethod
    def get_repository_policy(self, root: Path) -> LitConfig:
        """Load the explicit `.lit/config.json` policy contract."""

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
    def merge_revision(self, root: Path, revision: str) -> MergeResult:
        """Start a merge or continue the active merge when the repository is resumable."""

    @abstractmethod
    def abort_merge(self, root: Path) -> str:
        """Abort the active merge and return the restored revision identifier."""

    @abstractmethod
    def rebase_onto(self, root: Path, revision: str) -> RebaseResult:
        """Start a rebase or continue the active rebase when the repository is resumable."""

    @abstractmethod
    def abort_rebase(self, root: Path) -> str:
        """Abort the active rebase and return the restored revision identifier."""

    @abstractmethod
    def resume_operation(self, root: Path) -> MergeResult | RebaseResult:
        """Resume the active merge or rebase through the shared workflow boundary."""

    @abstractmethod
    def abort_operation(self, root: Path) -> str:
        """Abort the active merge or rebase through the shared workflow boundary."""

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
    def switch_lineage(self, root: Path, lineage_id: str) -> LineageHandle:
        """Switch the working tree and HEAD to an active lineage."""

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
                policy=LitConfig(default_branch=request.default_branch),
                snapshot=self._uninitialized_snapshot(
                    root,
                    default_branch=request.default_branch,
                ),
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

    def get_repository_snapshot(self, root: Path) -> RepositorySnapshotRecord:
        resolved = root.expanduser().resolve()
        if not (resolved / ".lit").is_dir():
            return self._uninitialized_snapshot(resolved)
        return self._snapshot_for_repository(self._repository(resolved))

    def get_resume_state(self, root: Path) -> ResumeOperationRecord | None:
        resolved = root.expanduser().resolve()
        if not (resolved / ".lit").is_dir():
            return None
        return self._resume_state_for_repository(self._repository(resolved))

    def get_repository_policy(self, root: Path) -> LitConfig:
        resolved = root.expanduser().resolve()
        if not (resolved / ".lit").is_dir():
            return LitConfig()
        return read_lit_config(LitLayout(resolved))

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
        checkpoint = WorkflowService(repo).create_checkpoint(
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
        checkpoint = WorkflowService(repo).rollback_to_checkpoint(
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

    def merge_revision(self, root: Path, revision: str) -> MergeResult:
        repo = self._repository(root)
        workflow = WorkflowService(repo)
        resume_state = self._resume_state_for_repository(repo)
        if resume_state is not None and resume_state.kind is OperationKind.MERGE:
            return workflow.resume_operation()
        return workflow.merge_revision(revision)

    def abort_merge(self, root: Path) -> str:
        repo = self._repository(root)
        workflow = WorkflowService(repo)
        resume_state = self._resume_state_for_repository(repo)
        if resume_state is not None and resume_state.kind is not OperationKind.MERGE:
            raise ValueError("Cannot abort merge while rebase is in progress.")
        return workflow.abort_merge()

    def rebase_onto(self, root: Path, revision: str) -> RebaseResult:
        repo = self._repository(root)
        workflow = WorkflowService(repo)
        resume_state = self._resume_state_for_repository(repo)
        if resume_state is not None and resume_state.kind is OperationKind.REBASE:
            return workflow.resume_operation()
        return workflow.rebase_onto(revision)

    def abort_rebase(self, root: Path) -> str:
        repo = self._repository(root)
        workflow = WorkflowService(repo)
        resume_state = self._resume_state_for_repository(repo)
        if resume_state is not None and resume_state.kind is not OperationKind.REBASE:
            raise ValueError("Cannot abort rebase while merge is in progress.")
        return workflow.abort_rebase()

    def resume_operation(self, root: Path) -> MergeResult | RebaseResult:
        return WorkflowService(self._repository(root)).resume_operation()

    def abort_operation(self, root: Path) -> str:
        return WorkflowService(self._repository(root)).abort_operation()

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

    def switch_lineage(self, root: Path, lineage_id: str) -> LineageHandle:
        lineage = self._repository(root).switch_lineage(lineage_id)
        return LineageHandle.from_managed(lineage)

    def preview_lineage_promotion(self, request: PreviewPromotionRequest) -> object:
        return self._repository(request.root).preview_promotion_conflicts(
            request.lineage_id,
            request.destination_lineage_id,
        )

    def promote_lineage(self, request: PromoteLineageRequest) -> OperationRecord:
        repo = self._repository(request.root)
        result = WorkflowService(repo).promote_lineage(
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
        return WorkflowService(repo).record_verification(
            revision_id=request.revision_id,
            definition_name=request.definition_name,
            command=request.command,
            command_identity=request.command_identity,
            state_fingerprint=request.state_fingerprint,
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
        policy = read_lit_config(repo.layout)
        snapshot = self._snapshot_for_repository(repo, policy=policy)
        return RepositoryHandle.for_root(
            repo.root,
            policy=policy,
            snapshot=snapshot,
        )

    def _uninitialized_snapshot(
        self,
        root: Path,
        *,
        default_branch: str = "main",
    ) -> RepositorySnapshotRecord:
        layout = LitLayout(root)
        return RepositorySnapshotRecord(
            repository_root=root.as_posix(),
            dot_lit_dir=layout.dot_lit.as_posix(),
            is_initialized=False,
            default_branch=default_branch,
            blockage_reason=RepositoryBlockageReason.REPOSITORY_UNINITIALIZED,
            blockage_detail="Repository has not been initialized.",
        )

    def _snapshot_for_repository(
        self,
        repo,
        *,
        policy: LitConfig | None = None,
    ) -> RepositorySnapshotRecord:
        resolved_policy = policy or read_lit_config(repo.layout)
        current_branch = repo.current_branch_name()
        workflow = WorkflowService(repo)
        latest_safe_checkpoint_id = workflow.safe_rollback_checkpoint_id(
            lineage_id=current_branch
        )
        resume_operation = self._resume_state_for_repository(
            repo,
            safe_rollback_checkpoint_id=latest_safe_checkpoint_id,
        )
        blockage_reason = (
            resume_operation.blockage_reason
            if resume_operation is not None
            else RepositoryBlockageReason.NONE
        )
        blockage_detail = resume_operation.blockage_detail if resume_operation is not None else None
        affected_lineage_scope = (
            resume_operation.affected_lineage_scope
            if resume_operation is not None
            else self._lineage_scope(current_branch)
        )
        return RepositorySnapshotRecord(
            repository_root=repo.root.as_posix(),
            dot_lit_dir=repo.layout.dot_lit.as_posix(),
            is_initialized=True,
            default_branch=resolved_policy.default_branch,
            current_branch=current_branch,
            current_lineage_id=current_branch,
            head_ref=repo.current_head_ref(),
            head_revision=repo.current_commit_id(),
            latest_safe_checkpoint_id=latest_safe_checkpoint_id,
            safe_rollback_checkpoint_id=latest_safe_checkpoint_id,
            blockage_reason=blockage_reason,
            blockage_detail=blockage_detail,
            affected_lineage_scope=affected_lineage_scope,
            resume_operation=resume_operation,
        )

    def _resume_state_for_repository(
        self,
        repo,
        *,
        safe_rollback_checkpoint_id: str | None = None,
    ) -> ResumeOperationRecord | None:
        operation = repo.current_operation()
        if operation is None:
            return None
        rollback_target = safe_rollback_checkpoint_id
        if rollback_target is None:
            rollback_target = WorkflowService(repo).safe_rollback_checkpoint_id(
                lineage_id=repo.current_branch_name()
            )
        if operation.kind == "merge":
            return self._merge_resume_record(
                repo,
                operation,
                safe_rollback_checkpoint_id=rollback_target,
            )
        return self._rebase_resume_record(
            repo,
            operation,
            safe_rollback_checkpoint_id=rollback_target,
        )

    def _merge_resume_record(
        self,
        repo,
        operation: OperationState,
        *,
        safe_rollback_checkpoint_id: str | None,
    ) -> ResumeOperationRecord:
        state = operation.state
        target_lineage = branch_name_from_ref(state.target_ref) if state.target_ref else None
        affected_lineage_scope = self._lineage_scope(
            repo.current_branch_name(),
            target_lineage,
        )
        blockage_reason = (
            RepositoryBlockageReason.MERGE_CONFLICTS
            if state.conflicts
            else RepositoryBlockageReason.MERGE_IN_PROGRESS
        )
        return ResumeOperationRecord(
            kind=OperationKind.MERGE,
            state_path=repo.layout.resume_state_path("merge").as_posix(),
            head_ref=state.head_ref,
            current_revision_id=state.current_commit,
            base_revision_id=state.base_commit,
            target_revision_id=state.target_commit,
            target_ref=state.target_ref,
            pending_revision_ids=(state.target_commit,),
            conflict_paths=state.conflicts,
            blockage_reason=blockage_reason,
            blockage_detail=self._blockage_detail("merge", state.conflicts),
            safe_rollback_checkpoint_id=safe_rollback_checkpoint_id,
            affected_lineage_scope=affected_lineage_scope,
        )

    def _rebase_resume_record(
        self,
        repo,
        operation: OperationState,
        *,
        safe_rollback_checkpoint_id: str | None,
    ) -> ResumeOperationRecord:
        state = operation.state
        current_lineage = repo.current_branch_name()
        blockage_reason = (
            RepositoryBlockageReason.REBASE_CONFLICTS
            if state.conflicts
            else RepositoryBlockageReason.REBASE_IN_PROGRESS
        )
        return ResumeOperationRecord(
            kind=OperationKind.REBASE,
            state_path=repo.layout.resume_state_path("rebase").as_posix(),
            head_ref=state.head_ref,
            current_revision_id=state.current_commit or state.original_head,
            onto_revision_id=state.onto,
            original_head_revision_id=state.original_head,
            pending_revision_ids=state.pending_commits,
            applied_revision_ids=state.applied_commits,
            conflict_paths=state.conflicts,
            blockage_reason=blockage_reason,
            blockage_detail=self._blockage_detail("rebase", state.conflicts),
            safe_rollback_checkpoint_id=safe_rollback_checkpoint_id,
            affected_lineage_scope=self._lineage_scope(current_lineage),
        )

    def _lineage_scope(
        self,
        primary_lineage_id: str | None,
        *related_lineage_ids: str | None,
    ) -> LineageScopeRecord:
        ordered: list[str] = []
        for lineage_id in (primary_lineage_id, *related_lineage_ids):
            if lineage_id is None or lineage_id in ordered:
                continue
            ordered.append(lineage_id)
        if not ordered:
            return LineageScopeRecord()
        scope_kind = (
            LineageScopeKind.CURRENT
            if len(ordered) == 1
            else LineageScopeKind.EXPLICIT
        )
        return LineageScopeRecord(
            scope_kind=scope_kind,
            primary_lineage_id=ordered[0],
            lineage_ids=tuple(ordered),
        )

    def _blockage_detail(self, kind: str, conflicts: tuple[str, ...]) -> str:
        if conflicts:
            listed = ", ".join(conflicts[:3])
            suffix = "" if len(conflicts) <= 3 else ", ..."
            return f"{kind} blocked by conflicts: {listed}{suffix}"
        return f"{kind} can be resumed"

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
        operation_id = next_identifier(kind.value)
        record = OperationRecord(
            operation_id=operation_id,
            kind=kind,
            status=OperationStatus.SUCCEEDED,
            repository_root=repo.root.as_posix(),
            lineage_id=lineage_id,
            revision_id=revision_id,
            checkpoint_id=checkpoint_id,
            verification_id=verification_id,
            artifact_ids=artifact_ids,
            journal_path=repo.layout.journal_path(operation_id).as_posix(),
            journal_dir=repo.layout.journal_dir(operation_id).as_posix(),
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
    "OperationProjection",
    "PreviewPromotionRequest",
    "PromoteLineageRequest",
    "RepositoryHandle",
    "RollbackRequest",
    "StepHandle",
    "VerificationStatusRequest",
    "VerifyRevisionRequest",
    "WorkspaceHandle",
]
