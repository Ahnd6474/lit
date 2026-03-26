from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("status", help="Show working tree status.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    status = repository.status()
    if status.is_clean():
        print("nothing to commit, working tree clean")
        return 0

    print("Changes to be committed:")
    for path in status.staged_added:
        print(f"  added: {path}")
    for path in status.staged_modified:
        print(f"  modified: {path}")
    for path in status.staged_deleted:
        print(f"  deleted: {path}")

    print("Changes not staged for commit:")
    for path in status.modified:
        print(f"  modified: {path}")
    for path in status.deleted:
        print(f"  deleted: {path}")

    print("Untracked files:")
    for path in status.untracked:
        print(f"  {path}")
    return 0
