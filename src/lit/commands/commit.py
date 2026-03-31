from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("commit", help="Create a commit from the index.")
    parser.add_argument("-m", "--message", required=True, help="Commit message.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())

    index = repository.read_index()
    paths = [entry.path for entry in index.entries]
    try:
        repository.validate_ownership(paths)
    except ValueError as error:
        print(f"error: {error}")
        return 1

    commit_id = repository.commit(args.message)
    print(f"[{repository.current_branch_name()} {commit_id[:12]}] {args.message}")
    return 0
