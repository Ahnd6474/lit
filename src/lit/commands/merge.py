from __future__ import annotations

import argparse
from pathlib import Path

from lit.merge_ops import merge_revision
from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("merge", help="Merge another local revision into the current branch.")
    parser.add_argument("revision", nargs="?", help="Branch or commit to merge.")
    parser.add_argument(
        "--abort",
        action="store_true",
        help="Abort the current merge state and restore the pre-merge tree.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    state = repository.read_merge_state()
    if args.abort:
        if state is None:
            print("No merge in progress.")
            return 1
        repository.apply_commit(state.current_commit, baseline_commit=repository.current_commit_id())
        repository.clear_merge()
        print("Merge state cleared.")
        return 0

    if args.revision:
        try:
            result = merge_revision(repository, args.revision)
        except ValueError as error:
            print(str(error))
            return 1
        print(result.message)
        if result.conflicts:
            print("conflicts:")
            for path in result.conflicts:
                print(f"  {path}")
            return 1
        return 0

    if state is None:
        print("No merge in progress.")
        return 1

    target = state.target_ref or state.target_commit
    print(f"merge in progress: {state.current_commit[:12]} + {target}")
    if state.conflicts:
        print("conflicts:")
        for path in state.conflicts:
            print(f"  {path}")
    return 0
