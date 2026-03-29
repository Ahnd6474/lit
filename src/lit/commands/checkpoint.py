from __future__ import annotations

import argparse

from lit.backend_api import CreateCheckpointRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit, short_id
from lit.domain import ApprovalState


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "checkpoint",
        help="Manage safe checkpoints for rollback, review, and lineage boundaries.",
    )
    checkpoint_subparsers = parser.add_subparsers(dest="checkpoint_command", required=True)

    create_parser = checkpoint_subparsers.add_parser(
        "create",
        help="Create a checkpoint for a revision boundary.",
    )
    create_parser.add_argument(
        "--revision",
        default="HEAD",
        help="Revision to checkpoint. Defaults to HEAD.",
    )
    create_parser.add_argument("--name", help="Checkpoint name.")
    create_parser.add_argument("--note", help="Checkpoint note.")
    create_parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Create the checkpoint without marking it safe.",
    )
    create_parser.add_argument(
        "--pin",
        action="store_true",
        help="Pin the checkpoint as a long-lived rollback anchor.",
    )
    create_parser.add_argument(
        "--approval-state",
        choices=[state.value for state in ApprovalState],
        default=ApprovalState.NOT_REQUESTED.value,
        help="Checkpoint approval state.",
    )
    create_parser.add_argument("--approval-note", help="Approval or review note.")
    add_json_flag(create_parser)
    create_parser.set_defaults(handler=run_create)

    list_parser = checkpoint_subparsers.add_parser(
        "list",
        help="List checkpoints in the current repository.",
    )
    list_parser.add_argument(
        "--lineage",
        help="Restrict results to a lineage.",
    )
    list_parser.add_argument(
        "--safe",
        action="store_true",
        help="Show only safe checkpoints.",
    )
    add_json_flag(list_parser)
    list_parser.set_defaults(handler=run_list)

    show_parser = checkpoint_subparsers.add_parser(
        "show",
        help="Inspect one checkpoint.",
    )
    show_parser.add_argument("checkpoint_id", help="Checkpoint identifier.")
    add_json_flag(show_parser)
    show_parser.set_defaults(handler=run_show)

    latest_parser = checkpoint_subparsers.add_parser(
        "latest",
        help="Resolve the latest safe checkpoint.",
    )
    latest_parser.add_argument("--lineage", help="Restrict the search to one lineage.")
    add_json_flag(latest_parser)
    latest_parser.set_defaults(handler=run_latest)


def run_create(args: argparse.Namespace) -> int:
    repo = current_repository()
    revision_id = repo.resolve_revision(args.revision)
    if revision_id is None:
        raise FileNotFoundError(f"revision not found: {args.revision}")

    service = backend()
    operation = service.create_checkpoint(
        CreateCheckpointRequest(
            root=repo.root,
            revision_id=revision_id,
            name=args.name,
            note=args.note,
            safe=not args.unsafe,
            pinned=args.pin,
            approval_state=ApprovalState(args.approval_state),
            approval_note=args.approval_note,
        )
    )
    checkpoint = service.get_checkpoint(repo.root, operation.checkpoint_id or "")
    emit(
        args,
        {"operation": operation, "checkpoint": checkpoint},
        lambda payload: _render_checkpoint(payload["checkpoint"]),
    )
    return 0


def run_list(args: argparse.Namespace) -> int:
    repo = current_repository()
    service = backend()
    checkpoints = service.list_checkpoints(
        repo.root,
        lineage_id=args.lineage,
        only_safe=args.safe,
    )
    latest_safe = service.get_latest_safe_checkpoint(repo.root, lineage_id=args.lineage)
    emit(
        args,
        {
            "checkpoints": checkpoints,
            "latest_safe_checkpoint_id": None
            if latest_safe is None
            else latest_safe.checkpoint_id,
        },
        lambda payload: _render_checkpoint_list(
            payload["checkpoints"],
            latest_safe_checkpoint_id=payload["latest_safe_checkpoint_id"],
        ),
    )
    return 0


def run_show(args: argparse.Namespace) -> int:
    repo = current_repository()
    checkpoint = backend().get_checkpoint(repo.root, args.checkpoint_id)
    emit(args, checkpoint, _render_checkpoint_details)
    return 0


def run_latest(args: argparse.Namespace) -> int:
    repo = current_repository()
    checkpoint = backend().get_latest_safe_checkpoint(repo.root, lineage_id=args.lineage)
    if checkpoint is None:
        raise FileNotFoundError("no safe checkpoint is available")
    emit(args, checkpoint, _render_checkpoint_details)
    return 0


def _render_checkpoint(checkpoint) -> str:
    tags = ["safe" if checkpoint.safe else "unsafe"]
    if checkpoint.pinned:
        tags.append("pinned")
    if checkpoint.approval_state is not ApprovalState.NOT_REQUESTED:
        tags.append(checkpoint.approval_state.value)
    label = checkpoint.name or checkpoint.note or "checkpoint"
    return (
        f"{checkpoint.checkpoint_id} -> {short_id(checkpoint.revision_id)} "
        f"[{', '.join(tags)}] {label}"
    )


def _render_checkpoint_list(
    checkpoints,
    *,
    latest_safe_checkpoint_id: str | None,
) -> str:
    if not checkpoints:
        return "No checkpoints recorded."
    lines = []
    for checkpoint in checkpoints:
        marker = "*" if checkpoint.checkpoint_id == latest_safe_checkpoint_id else " "
        lines.append(f"{marker} {_render_checkpoint(checkpoint)}")
    return "\n".join(lines)


def _render_checkpoint_details(checkpoint) -> str:
    lines = [
        f"checkpoint: {checkpoint.checkpoint_id}",
        f"revision: {checkpoint.revision_id}",
        f"name: {checkpoint.name or '-'}",
        f"note: {checkpoint.note or '-'}",
        f"safe: {checkpoint.safe}",
        f"pinned: {checkpoint.pinned}",
        f"approval: {checkpoint.approval_state.value}",
        f"verification: {checkpoint.verification_id or '-'}",
        f"lineage: {checkpoint.provenance.lineage_id or '-'}",
        f"created_at: {checkpoint.created_at or '-'}",
        f"artifacts: {', '.join(checkpoint.artifact_ids) or '-'}",
    ]
    return "\n".join(lines)
