from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.artifact_store import ArtifactStore
from lit.backend_api import (
    CreateCheckpointRequest,
    CreateLineageRequest,
    CreateRevisionRequest,
    DiscardLineageRequest,
    DoctorRequest,
    GitExportRequest,
    LitBackendService,
    OpenRepositoryRequest,
    PreviewPromotionRequest,
    PromoteLineageRequest,
    RollbackRequest,
    VerificationStatusRequest,
    VerifyRevisionRequest,
)
from lit.domain import ApprovalState, ProvenanceRecord, VerificationStatus
from lit.repository import Repository


def test_backend_service_unifies_revision_checkpoint_verification_and_artifact_linkage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    service = LitBackendService()

    handle = service.open_repository(OpenRepositoryRequest(root=root, create_if_missing=True))

    assert handle.is_initialized is True
    assert handle.current_branch == "main"

    artifact_store = ArtifactStore(tmp_path / "artifact-home")
    manifest = artifact_store.store_bytes(
        b"bundle-data",
        repository_root=root,
        kind="checkpoint-bundle",
        relative_path="bundles/base.tar",
    )
    artifact_id = manifest.artifact_id or ""

    story = root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    repo = Repository.open(root)
    repo.stage(["story.txt"])

    commit = service.create_revision(
        CreateRevisionRequest(
            root=root,
            message="base",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-main",
                lineage_id="main",
            ),
            artifact_ids=(artifact_id,),
        )
    )
    revision = service.get_current_revision(root)

    assert revision is not None
    assert revision.revision_id == commit.revision_id
    assert revision.provenance.actor_id == "agent-main"
    assert service.list_changed_files(root, revision.revision_id) == ("story.txt",)

    revision_artifacts = service.list_artifacts(
        root,
        owner_kind="revision",
        owner_id=revision.revision_id,
    )
    assert [artifact.artifact_id for artifact in revision_artifacts] == [artifact_id]
    assert revision_artifacts[0].links[0].owner_kind == "revision"
    assert revision_artifacts[0].links[0].owner_id == revision.revision_id

    verification = service.record_verification(
        VerifyRevisionRequest(
            root=root,
            revision_id=revision.revision_id or "",
            command=(sys.executable, "-c", "print('ok')"),
            command_identity="smoke",
        )
    )
    updated_revision = service.get_revision(root, revision.revision_id or "")
    summary = service.get_verification_status(
        VerificationStatusRequest(
            root=root,
            owner_kind="revision",
            owner_id=updated_revision.revision_id,
            linked_verification_id=updated_revision.verification_id,
            state_fingerprint=updated_revision.tree,
            command_identity="smoke",
        )
    )

    assert verification.status is VerificationStatus.PASSED
    assert updated_revision.verification_id == verification.verification_id
    assert updated_revision.provenance.verification_status is VerificationStatus.PASSED
    assert summary.status is VerificationStatus.PASSED
    assert summary.verification_id == verification.verification_id

    checkpoint = service.create_checkpoint(
        CreateCheckpointRequest(
            root=root,
            revision_id=updated_revision.revision_id or "",
            name="safe-base",
            approval_state=ApprovalState.APPROVED,
            approval_note="reviewed",
            artifact_ids=(artifact_id,),
        )
    )
    safe_checkpoint = service.get_latest_safe_checkpoint(root, lineage_id="main")

    assert safe_checkpoint is not None
    assert safe_checkpoint.checkpoint_id == checkpoint.checkpoint_id
    assert safe_checkpoint.approval_note == "reviewed"
    checkpoint_artifacts = service.list_artifacts(
        root,
        owner_kind="checkpoint",
        owner_id=safe_checkpoint.checkpoint_id,
    )
    assert [artifact.artifact_id for artifact in checkpoint_artifacts] == [artifact_id]

    story.write_text("changed\n", encoding="utf-8")
    repo = Repository.open(root)
    repo.stage(["story.txt"])
    changed_commit = service.create_revision(
        CreateRevisionRequest(
            root=root,
            message="change",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-main",
                lineage_id="main",
            ),
        )
    )

    rollback = service.rollback_to_checkpoint(
        RollbackRequest(
            root=root,
            checkpoint_id=safe_checkpoint.checkpoint_id,
            use_latest_safe=False,
        )
    )

    assert changed_commit.revision_id != updated_revision.revision_id
    assert rollback.revision_id == updated_revision.revision_id
    reopened = Repository.open(root)
    assert reopened.current_commit_id() == updated_revision.revision_id
    assert story.read_text(encoding="utf-8") == "base\n"


def test_backend_service_exposes_lineage_preview_doctor_and_git_export_plan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    service = LitBackendService()
    service.initialize_repository(OpenRepositoryRequest(root=root))

    base_file = root / "base.txt"
    base_file.write_text("base\n", encoding="utf-8")
    repo = Repository.open(root)
    repo.stage(["base.txt"])
    base_commit = service.create_revision(
        CreateRevisionRequest(
            root=root,
            message="base",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-main",
                lineage_id="main",
            ),
        )
    )
    base_revision_id = base_commit.revision_id or ""
    base_checkpoint = service.create_checkpoint(
        CreateCheckpointRequest(
            root=root,
            revision_id=base_revision_id,
            name="base-safe",
            approval_state=ApprovalState.APPROVED,
            approval_note="human-reviewed",
            provenance=ProvenanceRecord(
                actor_role="reviewer",
                actor_id="human",
                lineage_id="main",
            ),
        )
    )

    service.create_lineage(
        CreateLineageRequest(
            root=root,
            lineage_id="feature",
            owned_paths=("feature.txt",),
            title="Feature",
            description="parallel work",
        )
    )
    feature_lineage = service.get_lineage(root, "feature")
    assert feature_lineage.base_checkpoint_id == base_checkpoint.checkpoint_id
    assert feature_lineage.owned_paths == ("feature.txt",)

    repo = Repository.open(root)
    repo.checkout("feature")
    feature_file = root / "feature.txt"
    feature_file.write_text("feature\n", encoding="utf-8")
    repo.stage(["feature.txt"])
    feature_commit = service.create_revision(
        CreateRevisionRequest(
            root=root,
            message="feature update",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-feature",
                lineage_id="feature",
            ),
        )
    )
    repo = Repository.open(root)
    repo.checkout("main")

    preview = service.preview_lineage_promotion(
        PreviewPromotionRequest(
            root=root,
            lineage_id="feature",
            destination_lineage_id="main",
        )
    )
    promoted = service.promote_lineage(
        PromoteLineageRequest(
            root=root,
            lineage_id="feature",
            destination_lineage_id="main",
        )
    )

    assert preview.can_promote is True
    assert promoted.revision_id == feature_commit.revision_id

    promoted_feature = service.get_lineage(root, "feature")
    promoted_main = service.get_lineage(root, "main")
    assert promoted_feature.status == "promoted"
    assert promoted_main.promoted_from == "feature"

    service.create_lineage(CreateLineageRequest(root=root, lineage_id="scratch"))
    discarded = service.discard_lineage(
        DiscardLineageRequest(root=root, lineage_id="scratch")
    )
    assert discarded.status == "discarded"

    doctor = service.doctor(DoctorRequest(root=root))
    export = service.export_git(GitExportRequest(root=root))

    assert doctor.is_initialized is True
    assert doctor.current_branch == "main"
    assert doctor.healthy is True
    assert doctor.stats.lineages == 3

    assert any(
        ref.ref_name == "refs/heads/main" and ref.revision_id == (feature_commit.revision_id or "")
        for ref in export.refs
    )
    assert any(
        ref.ref_name.startswith("refs/tags/lit/checkpoints/")
        and ref.revision_id == base_revision_id
        for ref in export.refs
    )
    feature_export = next(
        commit for commit in export.commits if commit.revision_id == (feature_commit.revision_id or "")
    )
    assert ("Lit-Actor-Id", "agent-feature") in feature_export.trailers
    assert ("Lit-Lineage-Id", "feature") in feature_export.trailers
