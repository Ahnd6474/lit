from __future__ import annotations

import argparse

from lit.backend_api import (
    CreateLineageRequest,
    DiscardLineageRequest,
    PreviewPromotionRequest,
    PromoteLineageRequest,
)
from lit.commands.common import add_json_flag, backend, current_repository, emit, short_id


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "lineage",
        help="Inspect and manage isolated lineages for parallel local work.",
    )
    lineage_subparsers = parser.add_subparsers(dest="lineage_command", required=True)

    list_parser = lineage_subparsers.add_parser("list", help="List known lineages.")
    list_parser.add_argument(
        "--active-only",
        action="store_true",
        help="Hide promoted or discarded lineages.",
    )
    add_json_flag(list_parser)
    list_parser.set_defaults(handler=run_list)

    show_parser = lineage_subparsers.add_parser("show", help="Inspect one lineage.")
    show_parser.add_argument("lineage_id", help="Lineage identifier.")
    add_json_flag(show_parser)
    show_parser.set_defaults(handler=run_show)

    create_parser = lineage_subparsers.add_parser("create", help="Create a new lineage.")
    create_parser.add_argument("lineage_id", help="Lineage identifier.")
    create_parser.add_argument("--forked-from", help="Revision or branch to fork from.")
    create_parser.add_argument("--base-checkpoint", help="Explicit base checkpoint.")
    create_parser.add_argument(
        "--owned-path",
        action="append",
        default=[],
        help="Path reservation owned by the lineage. May be repeated.",
    )
    create_parser.add_argument(
        "--allow-overlap",
        action="append",
        default=[],
        help="Lineage id allowed to overlap owned paths. May be repeated.",
    )
    create_parser.add_argument("--title", default="", help="Human title.")
    create_parser.add_argument("--description", default="", help="Human description.")
    add_json_flag(create_parser)
    create_parser.set_defaults(handler=run_create)

    promote_parser = lineage_subparsers.add_parser(
        "promote",
        help="Preview or perform a lineage promotion into another lineage.",
    )
    promote_parser.add_argument("lineage_id", help="Source lineage identifier.")
    promote_parser.add_argument("--destination", help="Destination lineage.")
    promote_parser.add_argument(
        "--expected-head",
        help="Fail if the source lineage head moved.",
    )
    promote_parser.add_argument(
        "--preview",
        action="store_true",
        help="Show promotion conflicts without mutating repository state.",
    )
    add_json_flag(promote_parser)
    promote_parser.set_defaults(handler=run_promote)

    discard_parser = lineage_subparsers.add_parser("discard", help="Discard an inactive lineage.")
    discard_parser.add_argument("lineage_id", help="Lineage identifier.")
    add_json_flag(discard_parser)
    discard_parser.set_defaults(handler=run_discard)


def run_list(args: argparse.Namespace) -> int:
    repo = current_repository()
    current = repo.current_branch_name()
    lineages = backend().list_lineages(repo.root, include_inactive=not args.active_only)
    emit(
        args,
        {"current_lineage_id": current, "lineages": lineages},
        lambda payload: _render_lineage_list(
            payload["lineages"],
            current_lineage_id=payload["current_lineage_id"],
        ),
    )
    return 0


def run_show(args: argparse.Namespace) -> int:
    lineage = backend().get_lineage(current_repository().root, args.lineage_id)
    emit(args, lineage, _render_lineage_details)
    return 0


def run_create(args: argparse.Namespace) -> int:
    repo = current_repository()
    operation = backend().create_lineage(
        CreateLineageRequest(
            root=repo.root,
            lineage_id=args.lineage_id,
            forked_from=args.forked_from,
            base_checkpoint_id=args.base_checkpoint,
            owned_paths=tuple(args.owned_path),
            allow_owned_path_overlap_with=tuple(args.allow_overlap),
            title=args.title,
            description=args.description,
        )
    )
    lineage = backend().get_lineage(repo.root, args.lineage_id)
    emit(
        args,
        {"operation": operation, "lineage": lineage},
        lambda payload: (
            f"created lineage {payload['lineage'].lineage_id} "
            f"at {short_id(payload['lineage'].head_revision)}"
        ),
    )
    return 0


def run_promote(args: argparse.Namespace) -> int:
    repo = current_repository()
    service = backend()
    if args.preview:
        preview = service.preview_lineage_promotion(
            PreviewPromotionRequest(
                root=repo.root,
                lineage_id=args.lineage_id,
                destination_lineage_id=args.destination,
            )
        )
        emit(args, preview, _render_promotion_preview)
        return 0 if preview.can_promote else 1

    operation = service.promote_lineage(
        PromoteLineageRequest(
            root=repo.root,
            lineage_id=args.lineage_id,
            destination_lineage_id=args.destination,
            expected_head_revision=args.expected_head,
        )
    )
    emit(
        args,
        operation,
        lambda payload: payload.message or f"promoted {args.lineage_id}",
    )
    return 0


def run_discard(args: argparse.Namespace) -> int:
    lineage = backend().discard_lineage(
        DiscardLineageRequest(
            root=current_repository().root,
            lineage_id=args.lineage_id,
        )
    )
    emit(args, lineage, lambda payload: f"discarded lineage {payload.lineage_id}")
    return 0


def _render_lineage_list(lineages, *, current_lineage_id: str | None) -> str:
    if not lineages:
        return "No lineages recorded."
    lines = []
    for lineage in lineages:
        marker = "*" if lineage.lineage_id == current_lineage_id else " "
        owned = ",".join(lineage.owned_paths) or "-"
        lines.append(
            f"{marker} {lineage.lineage_id} [{lineage.status}] "
            f"head={short_id(lineage.head_revision)} base={lineage.base_checkpoint_id or '-'} "
            f"owned={owned}"
        )
    return "\n".join(lines)


def _render_lineage_details(lineage) -> str:
    return "\n".join(
        (
            f"lineage: {lineage.lineage_id}",
            f"status: {lineage.status}",
            f"head: {lineage.head_revision or '-'}",
            f"base_checkpoint: {lineage.base_checkpoint_id or '-'}",
            f"forked_from: {lineage.forked_from or '-'}",
            f"promoted_from: {lineage.promoted_from or '-'}",
            f"promoted_to: {lineage.promoted_to or '-'}",
            f"title: {lineage.title or '-'}",
            f"description: {lineage.description or '-'}",
            f"owned_paths: {', '.join(lineage.owned_paths) or '-'}",
            f"allow_overlap_with: {', '.join(lineage.allow_owned_path_overlap_with) or '-'}",
            f"checkpoints: {', '.join(lineage.checkpoint_ids) or '-'}",
        )
    )


def _render_promotion_preview(preview) -> str:
    lines = [
        f"source: {preview.source_lineage_id}",
        f"destination: {preview.destination_lineage_id}",
        f"can_promote: {preview.can_promote}",
        f"baseline: {preview.baseline_revision or '-'}",
        f"source_head: {preview.source_head_revision or '-'}",
        f"destination_head: {preview.destination_head_revision or '-'}",
        f"source_paths: {', '.join(preview.source_changed_paths) or '-'}",
        f"destination_paths: {', '.join(preview.destination_changed_paths) or '-'}",
    ]
    if preview.conflicts:
        lines.append("conflicts:")
        for conflict in preview.conflicts:
            lines.append(
                f"  {conflict.conflict_type.value}: {conflict.path or '-'} "
                f"{conflict.related_lineage_id or ''} {conflict.detail}".rstrip()
            )
    return "\n".join(lines)
