from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "checkout",
        help="Restore the full tree from a revision without changing HEAD.",
    )
    parser.add_argument("revision", help="Revision to restore from.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    restored = repository.apply_commit(repository.resolve_revision(args.revision))
    print(f"checked out {len(restored)} path(s) from {args.revision}")
    return 0
