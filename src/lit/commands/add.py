from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("add", help="Stage files or directories.")
    parser.add_argument("paths", nargs="+", help="Paths to stage.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())

    try:
        repository.validate_ownership(args.paths)
    except ValueError as error:
        print(f"error: {error}")
        return 1

    staged = repository.stage(args.paths)
    print(f"staged {len(staged)} path(s)")
    return 0
