from __future__ import annotations

import argparse
from pathlib import Path

from lit.rebase_ops import rebase_onto
from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("rebase", help="Rebase the current branch onto another local revision.")
    parser.add_argument("revision", nargs="?", help="Branch or commit to rebase onto.")
    parser.add_argument(
        "--abort",
        action="store_true",
        help="Abort the current rebase state and restore the original branch tip.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    repository = Repository.discover(Path.cwd())
    state = repository.read_rebase_state()
    if args.abort:
        if state is None:
            print("No rebase in progress.")
            return 1
        branch_name = repository.current_branch_name()
        if branch_name is not None:
            repository.write_branch(branch_name, state.original_head)
        repository.apply_commit(state.original_head, baseline_commit=repository.current_commit_id())
        repository.clear_rebase()
        print("Rebase state cleared.")
        return 0

    if args.revision:
        try:
            result = rebase_onto(repository, args.revision)
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
        print("No rebase in progress.")
        return 1

    print(f"rebase in progress onto {state.onto[:12]}")
    print(f"pending commits: {len(state.pending_commits)}")
    if state.conflicts:
        print("conflicts:")
        for path in state.conflicts:
            print(f"  {path}")
    return 0
