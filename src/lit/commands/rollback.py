from __future__ import annotations

import argparse

from lit.backend_api import RollbackRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit, short_id


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "rollback",
        help="Restore the working tree to the latest safe checkpoint or a selected checkpoint.",
    )
    parser.add_argument(
        "checkpoint_id",
        nargs="?",
        help="Checkpoint identifier to restore. Defaults to the latest safe checkpoint.",
    )
    parser.add_argument(
        "--lineage",
        help="Prefer checkpoints from a lineage when resolving the rollback target.",
    )
    add_json_flag(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repo = current_repository()
    service = backend()
    operation = service.rollback_to_checkpoint(
        RollbackRequest(
            root=repo.root,
            checkpoint_id=args.checkpoint_id,
            use_latest_safe=args.checkpoint_id is None,
            lineage_id=args.lineage,
        )
    )
    checkpoint = service.get_checkpoint(repo.root, operation.checkpoint_id or "")
    emit(
        args,
        {"operation": operation, "checkpoint": checkpoint},
        lambda payload: (
            f"Rolled back to {payload['checkpoint'].checkpoint_id} "
            f"at {short_id(payload['checkpoint'].revision_id)}"
        ),
    )
    return 0
