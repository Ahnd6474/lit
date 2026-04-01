from __future__ import annotations

from lit.backend_api import (
    CreateCheckpointRequest,
    CreateRevisionRequest,
    DoctorRequest,
    LitBackendService,
    RollbackRequest,
)
from lit.domain import ApprovalState, ProvenanceRecord, RepositoryBlockageReason
from lit.repository import Repository


def test_shared_workflow_path_covers_resume_rollback_and_diagnostics(
    tmp_path,
    prepare_merge_conflict,
    prepare_rebase_conflict,
) -> None:
    service = LitBackendService()

    merge_root = tmp_path / "merge"
    merge_repo = Repository.create(merge_root)
    prepare_merge_conflict(merge_repo, merge_root)

    merge_result = service.merge_revision(merge_root, "feature")
    merge_resume = service.get_resume_state(merge_root)
    merge_snapshot = service.get_repository_snapshot(merge_root)

    assert merge_result.status == "conflict"
    assert merge_resume is not None
    assert merge_snapshot.resume_operation == merge_resume
    assert merge_snapshot.blockage_reason is RepositoryBlockageReason.MERGE_CONFLICTS

    (merge_root / "story.txt").write_text("resolved merge\n", encoding="utf-8")
    assert service.merge_revision(merge_root, "feature").status == "merged"
    assert service.get_resume_state(merge_root) is None

    rebase_root = tmp_path / "rebase"
    rebase_repo = Repository.create(rebase_root)
    prepare_rebase_conflict(rebase_repo, rebase_root)

    rebase_result = service.rebase_onto(rebase_root, "main")
    rebase_resume = service.get_resume_state(rebase_root)

    assert rebase_result.status == "conflict"
    assert rebase_resume is not None
    assert rebase_resume.blockage_reason is RepositoryBlockageReason.REBASE_CONFLICTS

    (rebase_root / "story.txt").write_text("resolved rebase\n", encoding="utf-8")
    assert service.rebase_onto(rebase_root, "main").status == "rebased"
    assert service.get_resume_state(rebase_root) is None

    rollback_root = tmp_path / "rollback"
    rollback_repo = Repository.create(rollback_root)
    story = rollback_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    rollback_repo.stage(["story.txt"])
    base_revision = service.create_revision(
        CreateRevisionRequest(
            root=rollback_root,
            message="base",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-main",
                lineage_id="main",
            ),
        )
    )
    checkpoint = service.create_checkpoint(
        CreateCheckpointRequest(
            root=rollback_root,
            revision_id=base_revision.revision_id or "",
            name="safe-base",
            approval_state=ApprovalState.APPROVED,
        )
    )

    story.write_text("unsafe\n", encoding="utf-8")
    rollback_repo = Repository.open(rollback_root)
    rollback_repo.stage(["story.txt"])
    service.create_revision(
        CreateRevisionRequest(
            root=rollback_root,
            message="unsafe",
            provenance=ProvenanceRecord(
                actor_role="executor",
                actor_id="agent-main",
                lineage_id="main",
            ),
        )
    )

    rolled_back = service.rollback_to_checkpoint(
        RollbackRequest(
            root=rollback_root,
            checkpoint_id=checkpoint.checkpoint_id,
            use_latest_safe=False,
        )
    )
    doctor = service.doctor(DoctorRequest(root=rollback_root))

    assert rolled_back.revision_id == base_revision.revision_id
    assert story.read_text(encoding="utf-8") == "base\n"
    assert doctor.healthy is True
    assert doctor.latest_safe_checkpoint_id == checkpoint.checkpoint_id
    assert doctor.current_branch == "main"
