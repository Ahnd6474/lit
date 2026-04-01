from __future__ import annotations

import argparse
from pathlib import Path

from lit.workflows import WorkflowService


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("rebase", help="Rebase the current branch onto another local revision.")
    parser.add_argument("revision", nargs="?", help="Branch or commit to rebase onto.")
    parser.add_argument(
        "--continue",
        dest="continue_rebase",
        action="store_true",
        help="Continue a rebase after resolving conflicts.",
    )
    parser.add_argument(
        "--abort",
        action="store_true",
        help="Abort the current rebase state and restore the original branch tip.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    workflow = WorkflowService.open(Path.cwd())
    repository = workflow.repository
    state = repository.read_rebase_state()
    if args.continue_rebase and args.revision:
        print("Specify either a revision or --continue.")
        return 1
    if args.abort:
        if state is None:
            print("No rebase in progress.")
            return 1
        workflow.abort_rebase()
        print("Rebase state cleared.")
        return 0

    if args.continue_rebase:
        try:
            result = workflow.continue_rebase()
        except ValueError as error:
            print(str(error))
            return 1
        print(result.message)
        return 0

    if args.revision:
        try:
            result = workflow.rebase_onto(args.revision)
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
