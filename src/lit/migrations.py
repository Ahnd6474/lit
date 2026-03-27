from __future__ import annotations

from pathlib import Path

from lit.commits import deserialize_commit
from lit.domain import CheckpointRecord, LineageRecord, RevisionRecord
from lit.layout import LitLayout
from lit.refs import iter_ref_names, read_ref, write_head, write_ref
from lit.storage import read_json, write_json
from lit.transactions import JournaledTransaction, recover_pending_transactions, utc_now


def bootstrap_repository(layout: LitLayout, *, default_branch: str = "main") -> tuple[str, ...]:
    config = read_json(layout.config, default={}) or {}
    resolved_branch = str(config.get("default_branch", default_branch))
    recovered = recover_pending_transactions(layout)

    if not _requires_migration(layout, default_branch=resolved_branch):
        return recovered

    with JournaledTransaction(layout, kind="migration", message="upgrade repository layout") as tx:
        _ensure_directories(layout)
        _ensure_core_files(layout, default_branch=resolved_branch, mutation=tx)
        _migrate_revisions(layout, mutation=tx)
        _migrate_lineages(layout, default_branch=resolved_branch, mutation=tx)
        _rebuild_checkpoint_refs(layout, mutation=tx)
    return recovered


def _requires_migration(layout: LitLayout, *, default_branch: str) -> bool:
    required_files = (
        layout.config,
        layout.head,
        layout.index,
        layout.branch_path(default_branch),
        layout.merge_state,
        layout.rebase_state,
    )
    if any(not directory.exists() for directory in layout.managed_directories()):
        return True
    if any(not path.exists() for path in required_files):
        return True
    branch_names = iter_ref_names(layout.heads)
    if not branch_names:
        branch_names = (default_branch,)
    if any(not layout.lineage_path(branch).exists() for branch in branch_names):
        return True
    for commit_path in layout.commits.glob("*"):
        if commit_path.is_file() and not layout.revision_path(commit_path.name).exists():
            return True
    safe_checkpoints = [record for record in _iter_checkpoint_records(layout) if record.safe]
    if safe_checkpoints and not layout.latest_safe_checkpoint_ref.exists():
        return True
    if any(
        not layout.safe_checkpoint_ref_path(record.checkpoint_id or "").exists()
        for record in safe_checkpoints
        if record.checkpoint_id
    ):
        return True
    return False


def _ensure_directories(layout: LitLayout) -> None:
    for directory in layout.managed_directories():
        directory.mkdir(parents=True, exist_ok=True)


def _ensure_core_files(
    layout: LitLayout,
    *,
    default_branch: str,
    mutation: JournaledTransaction,
) -> None:
    config = read_json(layout.config, default=None)
    if config is None:
        write_json(
            layout.config,
            {"default_branch": default_branch, "schema_version": 1},
            mutation=mutation,
        )
    if not layout.head.exists():
        write_head(layout.head, f"refs/heads/{default_branch}", mutation=mutation)
    if not layout.index.exists():
        write_json(layout.index, {"entries": []}, mutation=mutation)
    if not layout.branch_path(default_branch).exists():
        write_ref(layout.branch_path(default_branch), None, mutation=mutation)
    if not layout.merge_state.exists():
        write_json(layout.merge_state, None, mutation=mutation)
    if not layout.rebase_state.exists():
        write_json(layout.rebase_state, None, mutation=mutation)


def _migrate_revisions(layout: LitLayout, *, mutation: JournaledTransaction) -> None:
    for commit_path in sorted(layout.commits.glob("*")):
        if not commit_path.is_file():
            continue
        revision_id = commit_path.name
        target_path = layout.revision_path(revision_id)
        if target_path.exists():
            continue
        commit = deserialize_commit(commit_path.read_bytes())
        revision = RevisionRecord(
            revision_id=revision_id,
            tree=commit.tree,
            parents=commit.parents,
            message=commit.message,
            provenance=commit.metadata.to_provenance(),
        )
        write_json(target_path, revision.to_dict(), mutation=mutation)


def _migrate_lineages(
    layout: LitLayout,
    *,
    default_branch: str,
    mutation: JournaledTransaction,
) -> None:
    now = utc_now()
    branch_names = iter_ref_names(layout.heads)
    if not branch_names:
        branch_names = (default_branch,)
    for branch_name in branch_names:
        lineage_path = layout.lineage_path(branch_name)
        if lineage_path.exists():
            continue
        head_revision = read_ref(layout.branch_path(branch_name))
        record = LineageRecord(
            lineage_id=branch_name,
            head_revision=head_revision,
            created_at=now,
            updated_at=now,
            title=branch_name,
        )
        write_json(lineage_path, record.to_dict(), mutation=mutation)


def _iter_checkpoint_records(layout: LitLayout) -> tuple[CheckpointRecord, ...]:
    records: list[CheckpointRecord] = []
    for checkpoint_path in sorted(layout.checkpoints.glob("*.json")):
        records.append(CheckpointRecord.from_dict(read_json(checkpoint_path, default=None)))
    return tuple(record for record in records if record.checkpoint_id is not None)


def _rebuild_checkpoint_refs(layout: LitLayout, *, mutation: JournaledTransaction) -> None:
    latest_checkpoint: CheckpointRecord | None = None
    for record in _iter_checkpoint_records(layout):
        if record.checkpoint_id is None:
            continue
        ref_path = layout.safe_checkpoint_ref_path(record.checkpoint_id)
        if record.safe:
            write_ref(ref_path, record.revision_id, mutation=mutation)
            if latest_checkpoint is None or (record.created_at or "", record.checkpoint_id) > (
                latest_checkpoint.created_at or "",
                latest_checkpoint.checkpoint_id or "",
            ):
                latest_checkpoint = record
            continue
        mutation.delete_path(ref_path)
    write_ref(
        layout.latest_safe_checkpoint_ref,
        None if latest_checkpoint is None else latest_checkpoint.checkpoint_id,
        mutation=mutation,
    )


__all__ = ["bootstrap_repository"]
