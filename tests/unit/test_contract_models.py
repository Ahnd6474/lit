from __future__ import annotations

from pathlib import Path

from lit.config import (
    LitConfig,
    OperationPolicy,
    SafeRollbackPreference,
    read_lit_config,
    write_lit_config,
)
from lit.domain import (
    LineageScopeKind,
    LineageScopeRecord,
    OperationKind,
    RepositoryBlockageReason,
    RepositorySnapshotRecord,
    ResumeOperationRecord,
)
from lit.layout import LitLayout


def test_snapshot_json_round_trips_resume_and_rollback_contracts(tmp_path: Path) -> None:
    layout = LitLayout(tmp_path)
    resume = ResumeOperationRecord(
        kind=OperationKind.MERGE,
        state_path=layout.resume_state_path("merge").as_posix(),
        target_ref="refs/heads/feature",
        conflict_paths=("story.txt",),
        blockage_reason=RepositoryBlockageReason.MERGE_CONFLICTS,
        blockage_detail="merge blocked by conflicts: story.txt",
        safe_rollback_checkpoint_id="cp-safe",
        affected_lineage_scope=LineageScopeRecord(
            scope_kind=LineageScopeKind.EXPLICIT,
            primary_lineage_id="main",
            lineage_ids=("main", "feature"),
        ),
    )
    snapshot = RepositorySnapshotRecord(
        repository_root=tmp_path.as_posix(),
        dot_lit_dir=(tmp_path / ".lit").as_posix(),
        is_initialized=True,
        default_branch="main",
        current_branch="main",
        current_lineage_id="main",
        latest_safe_checkpoint_id="cp-latest",
        safe_rollback_checkpoint_id="cp-safe",
        blockage_reason=RepositoryBlockageReason.MERGE_CONFLICTS,
        blockage_detail="merge blocked by conflicts: story.txt",
        affected_lineage_scope=resume.affected_lineage_scope,
        resume_operation=resume,
    )

    payload = snapshot.to_dict()
    round_tripped = RepositorySnapshotRecord.from_dict(payload)

    assert payload["safe_rollback_checkpoint_id"] == "cp-safe"
    assert payload["resume_operation"]["kind"] == "merge"
    assert payload["resume_operation"]["affected_lineage_scope"]["lineage_ids"] == [
        "main",
        "feature",
    ]
    assert round_tripped == snapshot


def test_policy_loading_reads_explicit_config_json_contract(tmp_path: Path) -> None:
    layout = LitLayout(tmp_path)
    write_lit_config(
        layout,
        LitConfig(
            default_branch="trunk",
            operations=OperationPolicy(
                allow_resume=False,
                safe_rollback_preference=SafeRollbackPreference.REPOSITORY,
                expose_blockage_reason=True,
            ),
        ),
    )

    config = read_lit_config(layout)

    assert config.default_branch == "trunk"
    assert config.operations.allow_resume is False
    assert config.operations.safe_rollback_preference is SafeRollbackPreference.REPOSITORY
    assert layout.policy_config.name == "config.json"
