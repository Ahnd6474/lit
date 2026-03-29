from __future__ import annotations

import argparse

from lit.artifact_store import ArtifactStore
from lit.commands.common import add_json_flag, current_repository, emit


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "gc",
        help="Inspect or collect reclaimable global artifact objects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything.",
    )
    parser.add_argument(
        "--keep-digest",
        action="append",
        default=[],
        help="Extra digest to retain. May be repeated.",
    )
    add_json_flag(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repo = current_repository()
    store = ArtifactStore()
    inputs = store.artifact_gc_inputs([repo.root], keep_digests=args.keep_digest)
    result = store.collect_garbage(
        [repo.root],
        keep_digests=args.keep_digest,
        dry_run=args.dry_run,
    )
    emit(
        args,
        {"inputs": inputs, "result": result},
        lambda payload: _render_gc(payload["inputs"], payload["result"]),
    )
    return 0


def _render_gc(inputs, result) -> str:
    lines = [
        f"dry_run: {result.dry_run}",
        f"removed_objects: {len(result.removed_digests)}",
        f"removed_bytes: {result.removed_bytes}",
        f"retained_objects: {len(result.retained_digests)}",
        f"retained_bytes: {result.retained_bytes}",
    ]
    if inputs.candidate_digests:
        lines.append(f"candidates: {', '.join(inputs.candidate_digests)}")
    return "\n".join(lines)
