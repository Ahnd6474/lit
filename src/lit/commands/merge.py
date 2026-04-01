from __future__ import annotations

import argparse
from pathlib import Path

from lit.workflows import WorkflowService


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("merge", help="Merge another local revision into the current branch.")
    parser.add_argument("revision", nargs="?", help="Branch or commit to merge.")
    parser.add_argument(
        "--continue",
        dest="continue_merge",
        action="store_true",
        help="Continue a merge after resolving conflicts.",
    )
    parser.add_argument(
        "--abort",
        action="store_true",
        help="Abort the current merge state and restore the pre-merge tree.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    workflow = WorkflowService.open(Path.cwd())
    if args.continue_merge and args.revision:
        print("Specify either a revision or --continue.")
        return 1
    if args.abort:
        return _abort_merge(workflow)

    if args.continue_merge:
        return _continue_merge(workflow)

    if args.revision:
        return _merge_revision(workflow, args.revision)

    state = workflow.repository.read_merge_state()
    if state is None:
        print("No merge in progress.")
        return 1

    target = state.target_ref or state.target_commit
    print(f"merge in progress: {state.current_commit[:12]} + {target}")
    _print_conflicts(state.conflicts)
    return 0


def _abort_merge(workflow: WorkflowService) -> int:
    if workflow.repository.read_merge_state() is None:
        print("No merge in progress.")
        return 1
    workflow.abort_merge()
    print("Merge state cleared.")
    return 0


def _continue_merge(workflow: WorkflowService) -> int:
    try:
        result = workflow.continue_merge()
    except ValueError as error:
        print(str(error))
        return 1
    print(result.message)
    return 0


def _merge_revision(workflow: WorkflowService, revision: str) -> int:
    try:
        result = workflow.merge_revision(revision)
    except ValueError as error:
        print(str(error))
        return 1
    print(result.message)
    _print_conflicts(result.conflicts)
    return 1 if result.conflicts else 0


def _print_conflicts(conflicts: tuple[str, ...]) -> None:
    if not conflicts:
        return
    print("conflicts:")
    for path in conflicts:
        print(f"  {path}")
