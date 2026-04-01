from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.config import (
    LitConfig,
    OperationPolicy,
    SafeRollbackPreference,
    VerificationPolicy,
    write_lit_config,
)
from lit.domain import ProvenanceRecord, VerificationStatus
from lit.merge_ops import merge_revision
from lit.refs import branch_ref
from lit.repository import Repository
from lit.rebase_ops import rebase_onto
from lit.storage import write_json
from lit.workflows import WorkflowService
from lit.backend_api import LitBackendService, VerifyRevisionRequest


def test_workflow_service_continues_conflicted_merge(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"

    base_commit = _commit_story(repo, story, "base\n", "base", "main")
    repo.create_branch("feature", start_point=base_commit)

    main_commit = _commit_story(repo, story, "main change\n", "main", "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    feature_commit = _commit_story(repo, story, "feature change\n", "feature", "feature")

    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(main_commit, baseline_commit=feature_commit)

    result = merge_revision(repo, "feature")

    assert result.status == "conflict"
    story.write_text("resolved merge\n", encoding="utf-8")

    continued = WorkflowService(repo).continue_merge()

    assert continued.status == "merged"
    assert repo.read_merge_state() is None
    assert repo.read_commit(repo.current_commit_id() or "").parents == (main_commit, feature_commit)
    assert story.read_text(encoding="utf-8") == "resolved merge\n"


def test_workflow_service_continues_conflicted_rebase(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"

    base_commit = _commit_story(repo, story, "base\n", "base", "main")
    repo.create_branch("feature", start_point=base_commit)

    main_commit = _commit_story(repo, story, "main change\n", "main", "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    original_feature = _commit_story(repo, story, "feature change\n", "feature", "feature")

    result = rebase_onto(repo, "main")

    assert result.status == "conflict"
    story.write_text("resolved rebase\n", encoding="utf-8")

    continued = WorkflowService(repo).continue_rebase()
    rebased_head = repo.current_commit_id()

    assert continued.status == "rebased"
    assert repo.read_rebase_state() is None
    assert rebased_head is not None
    assert rebased_head != original_feature
    assert repo.read_commit(rebased_head).parents == (main_commit,)
    assert story.read_text(encoding="utf-8") == "resolved rebase\n"


def test_backend_snapshot_uses_policy_selected_safe_rollback_target(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repo = Repository.create(root)
    story = root / "story.txt"

    base_commit = _commit_story(repo, story, "base\n", "base", "main")
    repo.create_checkpoint(revision_id=base_commit, name="base-safe")
    repo.create_branch("feature", start_point=base_commit)

    repo.set_head_ref(branch_ref("feature"))
    feature_commit = _commit_story(repo, story, "feature\n", "feature", "feature")
    feature_checkpoint = repo.create_checkpoint(revision_id=feature_commit, name="feature-safe")

    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(base_commit, baseline_commit=feature_commit)
    main_commit = _commit_story(repo, story, "main\n", "main", "main")
    main_checkpoint = repo.create_checkpoint(revision_id=main_commit, name="main-safe")

    write_lit_config(
        repo.layout,
        LitConfig(
            operations=OperationPolicy(
                safe_rollback_preference=SafeRollbackPreference.REPOSITORY
            )
        ),
    )

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(feature_commit, baseline_commit=main_commit)

    snapshot = LitBackendService().get_repository_snapshot(root)

    assert feature_checkpoint.checkpoint_id != main_checkpoint.checkpoint_id
    assert snapshot.current_branch == "feature"
    assert snapshot.safe_rollback_checkpoint_id == main_checkpoint.checkpoint_id
    assert snapshot.latest_safe_checkpoint_id == main_checkpoint.checkpoint_id


def test_workflow_resume_policy_and_backend_verification_defaults(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repo = Repository.create(root)
    story = root / "story.txt"

    base_commit = _commit_story(repo, story, "base\n", "base", "main")
    repo.create_branch("feature", start_point=base_commit)

    main_commit = _commit_story(repo, story, "main change\n", "main", "main")
    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    _commit_story(repo, story, "feature change\n", "feature", "feature")
    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(main_commit)

    write_lit_config(
        repo.layout,
        LitConfig(
            verification=VerificationPolicy(default_definition_name="smoke"),
            operations=OperationPolicy(allow_resume=False),
        ),
    )
    write_json(
        repo.layout.config,
        {
            "default_branch": "main",
            "policies": {
                "verification": {"default_definition_name": "smoke"},
                "operations": {"allow_resume": False},
            },
            "verification_commands": [
                {
                    "name": "smoke",
                    "command": [sys.executable, "-c", "print('ok')"],
                    "command_identity": "smoke-default",
                }
            ],
            "schema_version": 1,
        },
    )

    workflow = WorkflowService(repo)
    result = workflow.merge_revision("feature")
    assert result.status == "conflict"

    with pytest.raises(ValueError, match="disabled by policy"):
        workflow.resume_operation()

    verification = LitBackendService().record_verification(
        VerifyRevisionRequest(
            root=root,
            revision_id=main_commit,
            environment_fingerprint="env-test",
        )
    )

    assert verification.status is VerificationStatus.PASSED
    assert verification.command_identity == "smoke-default"


def _commit_story(
    repository: Repository,
    story: Path,
    content: str,
    message: str,
    lineage_id: str,
) -> str:
    story.write_text(content, encoding="utf-8")
    repository.stage(["story.txt"])
    return repository.commit(
        message,
        provenance=ProvenanceRecord(
            actor_role="executor",
            actor_id=f"agent-{lineage_id}",
            lineage_id=lineage_id,
        ),
    )
