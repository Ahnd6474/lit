from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "restore",
        help="Restore tracked files from a revision without moving HEAD.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to restore. Restores the whole tree when omitted.",
    )
    parser.add_argument(
        "--source",
        default="HEAD",
        help="Revision to restore from.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    restored = repository.restore(args.paths, source=args.source)
    print(f"restored {len(restored)} path(s) from {args.source}")
    return 0
