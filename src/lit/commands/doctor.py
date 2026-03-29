from __future__ import annotations

import argparse

from lit.backend_api import DoctorRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "doctor",
        help="Inspect repository health, locks, and unfinished transactions.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Recover unfinished transactions when possible.",
    )
    add_json_flag(parser)
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    report = backend().doctor(DoctorRequest(root=current_repository().root, repair=args.repair))
    emit(
        args,
        {
            "repository_root": report.repository_root,
            "is_initialized": report.is_initialized,
            "current_branch": report.current_branch,
            "head_revision": report.head_revision,
            "latest_safe_checkpoint_id": report.latest_safe_checkpoint_id,
            "recovered_operations": report.recovered_operations,
            "findings": report.findings,
            "stats": report.stats,
            "healthy": report.healthy,
        },
        lambda payload: _render_report(report),
    )
    return 0 if report.healthy else 1


def _render_report(report) -> str:
    lines = [
        f"repository: {report.repository_root}",
        f"initialized: {report.is_initialized}",
        f"healthy: {report.healthy}",
        f"current_branch: {report.current_branch or '-'}",
        f"head_revision: {report.head_revision or '-'}",
        f"latest_safe_checkpoint: {report.latest_safe_checkpoint_id or '-'}",
        (
            "stats: "
            f"revisions={report.stats.revisions} "
            f"checkpoints={report.stats.checkpoints} "
            f"lineages={report.stats.lineages} "
            f"verifications={report.stats.verifications} "
            f"artifacts={report.stats.artifacts} "
            f"operations={report.stats.operations}"
        ),
    ]
    if report.findings:
        lines.append("findings:")
        for finding in report.findings:
            suffix = f" ({finding.path})" if finding.path else ""
            lines.append(f"  {finding.severity} {finding.code}: {finding.message}{suffix}")
    return "\n".join(lines)
