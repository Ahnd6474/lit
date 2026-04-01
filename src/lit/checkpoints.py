from __future__ import annotations

from pathlib import Path

from lit.domain import CheckpointRecord
from lit.layout import LitLayout
from lit.refs import delete_ref, read_ref, write_ref
from lit.storage import FileMutationWriter, read_json, write_json


def load_checkpoint(layout: LitLayout, checkpoint_id: str) -> CheckpointRecord:
    path = layout.checkpoint_path(checkpoint_id)
    if not path.exists():
        raise FileNotFoundError(f"checkpoint not found: {checkpoint_id}")
    return CheckpointRecord.from_dict(read_json(path, default=None))


def list_checkpoints(layout: LitLayout) -> tuple[CheckpointRecord, ...]:
    records = [
        CheckpointRecord.from_dict(read_json(path, default=None))
        for path in sorted(layout.checkpoints.glob("*.json"))
    ]
    materialized = [record for record in records if record.checkpoint_id is not None]
    materialized.sort(key=lambda record: (record.created_at or "", record.checkpoint_id or ""))
    return tuple(materialized)


def write_checkpoint(
    layout: LitLayout,
    record: CheckpointRecord,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    checkpoint_id = record.checkpoint_id
    if checkpoint_id is None:
        raise ValueError("checkpoint record requires an identifier")
    write_json(layout.checkpoint_path(checkpoint_id), record.to_dict(), mutation=mutation)
    _sync_safe_checkpoint_ref(layout, record, mutation=mutation)


def latest_safe_checkpoint_id(layout: LitLayout) -> str | None:
    checkpoint_id = read_ref(layout.latest_safe_checkpoint_ref)
    if checkpoint_id:
        return checkpoint_id
    safe_records = [record for record in list_checkpoints(layout) if record.safe]
    if not safe_records:
        return None
    safe_records.sort(key=lambda record: (record.created_at or "", record.checkpoint_id or ""))
    return safe_records[-1].checkpoint_id


def latest_safe_checkpoint(layout: LitLayout) -> CheckpointRecord | None:
    checkpoint_id = latest_safe_checkpoint_id(layout)
    if checkpoint_id is None:
        return None
    return load_checkpoint(layout, checkpoint_id)


def _sync_safe_checkpoint_ref(
    layout: LitLayout,
    record: CheckpointRecord,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    checkpoint_id = record.checkpoint_id
    if checkpoint_id is None:
        return
    ref_path = layout.safe_checkpoint_ref_path(checkpoint_id)
    if record.safe:
        write_ref(ref_path, record.revision_id, mutation=mutation)
        current_latest = latest_safe_checkpoint_id(layout)
        if current_latest is None:
            write_ref(layout.latest_safe_checkpoint_ref, checkpoint_id, mutation=mutation)
            return
        current_record = load_checkpoint(layout, current_latest)
        current_key = (current_record.created_at or "", current_record.checkpoint_id or "")
        incoming_key = (record.created_at or "", checkpoint_id)
        if incoming_key >= current_key:
            write_ref(layout.latest_safe_checkpoint_ref, checkpoint_id, mutation=mutation)
        return
    delete_ref(ref_path, mutation=mutation)
    if read_ref(layout.latest_safe_checkpoint_ref) == checkpoint_id:
        remaining = [candidate for candidate in list_checkpoints(layout) if candidate.safe]
        if remaining:
            remaining.sort(key=lambda candidate: (candidate.created_at or "", candidate.checkpoint_id or ""))
            write_ref(
                layout.latest_safe_checkpoint_ref,
                remaining[-1].checkpoint_id,
                mutation=mutation,
            )
        else:
            delete_ref(layout.latest_safe_checkpoint_ref, mutation=mutation)


__all__ = [
    "latest_safe_checkpoint",
    "latest_safe_checkpoint_id",
    "list_checkpoints",
    "load_checkpoint",
    "write_checkpoint",
]
