from __future__ import annotations

import argparse

from lit.backend_api import GitExportRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "export",
        help="Build a Git-facing export plan. This is a bridge, not Git parity.",
    )
    parser.add_argument(
        "--start-revision",
        help="Start the export walk from a specific revision.",
    )
    parser.add_argument(
        "--lineage",
        help="Export the reachable history for one lineage head.",
    )
    add_json_flag(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    plan = backend().export_git(
        GitExportRequest(
            root=current_repository().root,
            start_revision=args.start_revision,
            lineage_id=args.lineage,
        )
    )
    emit(args, plan, _render_plan)
    return 0


def _render_plan(plan) -> str:
    lines = [
        f"repository: {plan.repository_root}",
        f"default_branch: {plan.default_branch}",
        f"current_branch: {plan.current_branch or '-'}",
        f"head_revision: {plan.head_revision or '-'}",
        f"refs: {len(plan.refs)}",
        f"commits: {len(plan.commits)}",
    ]
    for ref in plan.refs:
        lines.append(f"  {ref.ref_name} -> {ref.revision_id}")
    return "\n".join(lines)
