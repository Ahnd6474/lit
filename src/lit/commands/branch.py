from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("branch", help="List local branches or create a new branch.")
    parser.add_argument("name", nargs="?", help="Branch name to create.")
    parser.add_argument(
        "--start-point",
        default="HEAD",
        help="Revision where the new branch should point.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Replace an existing branch ref.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    if args.name:
        branch = repository.create_branch(
            args.name,
            start_point=args.start_point,
            force=args.force,
        )
        target = branch.commit_id[:12] if branch.commit_id is not None else "unborn"
        print(f"{branch.name} -> {target}")
        return 0

    for branch in repository.list_branches():
        marker = "*" if branch.current else " "
        target = branch.commit_id[:12] if branch.commit_id is not None else "unborn"
        print(f"{marker} {branch.name} {target}")
    return 0
