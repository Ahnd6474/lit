from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("log", help="Show commit history.")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    history = repository.iter_history()
    if not history:
        print("No commits yet.")
        return 0
    for commit_id, record in history:
        print(f"commit {commit_id}")
        print(f"    {record.summary}")
    return 0
