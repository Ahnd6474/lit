from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "checkout",
        help="Switch HEAD to a branch or commit and update the working tree.",
    )
    parser.add_argument("revision", help="Branch name or commit to check out.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    checkout = repository.checkout(args.revision)
    if checkout.branch_name is not None:
        print(f"switched to branch {checkout.branch_name}")
    else:
        target = "unborn" if checkout.commit_id is None else checkout.commit_id[:12]
        print(f"detached HEAD at {target}")
    return 0
