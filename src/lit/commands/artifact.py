from __future__ import annotations

import argparse

from lit.artifact_store import ArtifactStore
from lit.backend_api import ArtifactLinkRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "artifact",
        help="Inspect artifact manifests, usage, and ownership links.",
    )
    artifact_subparsers = parser.add_subparsers(dest="artifact_command", required=True)

    list_parser = artifact_subparsers.add_parser("list", help="List artifact manifests.")
    list_parser.add_argument("--owner-kind", help="Restrict results to an owner kind.")
    list_parser.add_argument("--owner-id", help="Restrict results to an owner id.")
    add_json_flag(list_parser)
    list_parser.set_defaults(handler=run_list)

    show_parser = artifact_subparsers.add_parser("show", help="Inspect one artifact manifest.")
    show_parser.add_argument("artifact_id", help="Artifact identifier.")
    add_json_flag(show_parser)
    show_parser.set_defaults(handler=run_show)

    link_parser = artifact_subparsers.add_parser("link", help="Attach an existing artifact to an owner.")
    link_parser.add_argument("artifact_id", help="Artifact identifier.")
    link_parser.add_argument("--owner-kind", required=True, help="Owner kind.")
    link_parser.add_argument("--owner-id", required=True, help="Owner identifier.")
    link_parser.add_argument("--relationship", default="attached", help="Link relationship.")
    link_parser.add_argument("--note", help="Link note.")
    pin_group = link_parser.add_mutually_exclusive_group()
    pin_group.add_argument("--pin", action="store_true", help="Pin the artifact after linking.")
    pin_group.add_argument("--unpin", action="store_true", help="Unpin the artifact after linking.")
    add_json_flag(link_parser)
    link_parser.set_defaults(handler=run_link)

    usage_parser = artifact_subparsers.add_parser(
        "usage",
        help="Show local artifact storage usage for the current repository.",
    )
    add_json_flag(usage_parser)
    usage_parser.set_defaults(handler=run_usage)


def run_list(args: argparse.Namespace) -> int:
    artifacts = backend().list_artifacts(
        current_repository().root,
        owner_kind=args.owner_kind,
        owner_id=args.owner_id,
    )
    emit(args, artifacts, _render_artifact_list)
    return 0


def run_show(args: argparse.Namespace) -> int:
    artifact = backend().get_artifact(current_repository().root, args.artifact_id)
    emit(args, artifact, _render_artifact_details)
    return 0


def run_link(args: argparse.Namespace) -> int:
    if args.pin:
        pinned = True
    elif args.unpin:
        pinned = False
    else:
        pinned = None
    artifact = backend().link_artifact(
        ArtifactLinkRequest(
            root=current_repository().root,
            artifact_id=args.artifact_id,
            owner_kind=args.owner_kind,
            owner_id=args.owner_id,
            relationship=args.relationship,
            note=args.note,
            pinned=pinned,
        )
    )
    emit(
        args,
        artifact,
        lambda payload: (
            f"linked {payload.artifact_id} to {args.owner_kind}:{args.owner_id} "
            f"as {args.relationship}"
        ),
    )
    return 0


def run_usage(args: argparse.Namespace) -> int:
    repo = current_repository()
    report = ArtifactStore().usage_report([repo.root])
    emit(args, report, _render_usage)
    return 0


def _render_artifact_list(artifacts) -> str:
    if not artifacts:
        return "No artifacts recorded."
    return "\n".join(
        (
            f"{artifact.artifact_id} {artifact.kind} "
            f"{artifact.owner_kind}:{artifact.owner_id or '-'} "
            f"{artifact.relative_path or '-'}"
        )
        for artifact in artifacts
    )


def _render_artifact_details(artifact) -> str:
    return "\n".join(
        (
            f"artifact: {artifact.artifact_id}",
            f"owner: {artifact.owner_kind}:{artifact.owner_id or '-'}",
            f"kind: {artifact.kind}",
            f"path: {artifact.relative_path or '-'}",
            f"content_type: {artifact.content_type or '-'}",
            f"digest: {artifact.digest or '-'}",
            f"size_bytes: {artifact.size_bytes or 0}",
            f"created_at: {artifact.created_at or '-'}",
            f"pinned: {artifact.pinned}",
            f"links: {', '.join(f'{link.owner_kind}:{link.owner_id}' for link in artifact.links) or '-'}",
        )
    )


def _render_usage(report) -> str:
    return "\n".join(
        (
            f"total_objects: {report.total_objects}",
            f"total_bytes: {report.total_bytes}",
            f"linked_objects: {report.linked_objects}",
            f"linked_bytes: {report.linked_bytes}",
            f"pinned_objects: {report.pinned_objects}",
            f"pinned_bytes: {report.pinned_bytes}",
            f"reclaimable_objects: {report.reclaimable_objects}",
            f"reclaimable_bytes: {report.reclaimable_bytes}",
            f"quota_bytes: {report.quota_bytes if report.quota_bytes is not None else '-'}",
            f"over_quota: {report.over_quota}",
        )
    )
