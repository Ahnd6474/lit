from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.domain import ApprovalState, ProvenanceRecord
from lit.merge_ops import merge_revision
from lit.rebase_ops import rebase_onto
from lit.refs import branch_ref
from lit.repository import Repository


def test_safe_checkpoints_support_listing_metadata_and_selected_rollback(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"

    base_commit = _commit_story(
        repo,
        story,
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    first_checkpoint = repo.create_checkpoint(
        revision_id=base_commit,
        name="base-safe",
        note="known good",
        safe=True,
        pinned=True,
        approval_state=ApprovalState.PENDING,
        approval_note="needs review",
        provenance=ProvenanceRecord(actor_role="reviewer", actor_id="human", lineage_id="main"),
    )

    head_commit = _commit_story(
        repo,
        story,
        "head\n",
        "head",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    second_checkpoint = repo.create_checkpoint(
        revision_id=head_commit,
        name="head-safe",
        safe=True,
        provenance=ProvenanceRecord(actor_role="reviewer", actor_id="human", lineage_id="main"),
    )

    only_safe = repo.list_checkpoints(only_safe=True)
    assert [checkpoint.checkpoint_id for checkpoint in only_safe] == [
        first_checkpoint.checkpoint_id,
        second_checkpoint.checkpoint_id,
    ]
    assert repo.latest_safe_checkpoint_id() == second_checkpoint.checkpoint_id

    updated = repo.unpin_checkpoint(first_checkpoint.checkpoint_id or "")
    assert updated.pinned is False
    approved = repo.set_checkpoint_approval(
        first_checkpoint.checkpoint_id or "",
        state=ApprovalState.APPROVED,
        note="verified",
    )
    assert approved.approval_state is ApprovalState.APPROVED
    assert approved.approval_note == "verified"

    story.write_text("drift\n", encoding="utf-8")
    rollback = repo.rollback_to_checkpoint(
        checkpoint_id=first_checkpoint.checkpoint_id,
        use_latest_safe=False,
    )

    assert rollback.revision_id == base_commit
    assert repo.current_commit_id() == base_commit
    assert story.read_text(encoding="utf-8") == "base\n"


def test_merge_and_rebase_write_structured_revision_provenance(tmp_path: Path) -> None:
    merge_root = tmp_path / "merge"
    merge_root.mkdir()
    merge_repo = Repository.create(merge_root)
    merge_story = merge_root / "story.txt"

    base_commit = _commit_story(
        merge_repo,
        merge_story,
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    merge_repo.create_branch("feature", start_point=base_commit)
    main_commit = _commit_story(
        merge_repo,
        merge_story,
        "main\n",
        "main",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    merge_repo.set_head_ref(branch_ref("feature"))
    merge_repo.apply_commit(base_commit, baseline_commit=main_commit)
    feature_only = merge_root / "feature.txt"
    feature_only.write_text("feature\n", encoding="utf-8")
    merge_repo.stage(["feature.txt"])
    feature_commit = merge_repo.commit(
        "feature",
        provenance=ProvenanceRecord(actor_role="executor", actor_id="agent-feature", lineage_id="feature"),
    )
    merge_repo.set_head_ref(branch_ref("main"))
    merge_repo.apply_commit(main_commit, baseline_commit=feature_commit)

    merged = merge_revision(merge_repo, "feature")
    merged_revision = merge_repo.get_revision(merged.commit_id or "")

    assert merged_revision.provenance.actor_role == "merge"
    assert merged_revision.provenance.lineage_id == "main"
    assert merged_revision.provenance.origin_commit == main_commit

    rebase_root = tmp_path / "rebase"
    rebase_root.mkdir()
    rebase_repo = Repository.create(rebase_root)
    rebase_story = rebase_root / "story.txt"
    rebase_base = _commit_story(
        rebase_repo,
        rebase_story,
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    rebase_repo.create_branch("feature", start_point=rebase_base)
    main_tip = _commit_story(
        rebase_repo,
        rebase_story,
        "main\n",
        "main",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    rebase_repo.set_head_ref(branch_ref("feature"))
    rebase_repo.apply_commit(rebase_base, baseline_commit=main_tip)
    feature_file = rebase_root / "feature.txt"
    feature_file.write_text("feature\n", encoding="utf-8")
    rebase_repo.stage(["feature.txt"])
    original_feature = rebase_repo.commit(
        "feature",
        provenance=ProvenanceRecord(actor_role="executor", actor_id="agent-feature", lineage_id="feature"),
    )

    rebased = rebase_onto(rebase_repo, "main")
    rebased_revision = rebase_repo.get_revision(rebased.commit_id or "")

    assert rebased_revision.provenance.actor_role == "rebase"
    assert rebased_revision.provenance.lineage_id == "feature"
    assert rebased_revision.provenance.origin_commit == original_feature
    assert rebased_revision.provenance.rewritten_from == original_feature


def _commit_story(
    repository: Repository,
    story: Path,
    content: str,
    message: str,
    provenance: ProvenanceRecord,
) -> str:
    story.write_text(content, encoding="utf-8")
    repository.stage(["story.txt"])
    return repository.commit(message, provenance=provenance)

