from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("diff", help="Show diff against the last commit.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    diff_output = repository.diff()
    if diff_output:
        print(diff_output)
    return 0
