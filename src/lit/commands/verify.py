from __future__ import annotations

import argparse
import platform
import sys

from lit.backend_api import VerificationStatusRequest, VerifyRevisionRequest
from lit.commands.common import add_json_flag, backend, current_repository, emit, short_id
from lit.domain import VerificationStatus


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "verify",
        help="Record or inspect repository verification results.",
    )
    verify_subparsers = parser.add_subparsers(dest="verify_command", required=True)

    run_parser = verify_subparsers.add_parser(
        "run",
        help="Run verification for a revision using a configured definition or an explicit command.",
    )
    run_parser.add_argument(
        "revision",
        nargs="?",
        default="HEAD",
        help="Revision to verify. Defaults to HEAD.",
    )
    run_parser.add_argument("--definition", help="Configured verification command name.")
    run_parser.add_argument(
        "--command",
        nargs=argparse.REMAINDER,
        default=(),
        help="Explicit verification command to run after this flag.",
    )
    run_parser.add_argument(
        "--command-identity",
        help="Stable command identity used for cache replay.",
    )
    run_parser.add_argument(
        "--environment-fingerprint",
        help="Explicit environment fingerprint. Defaults to the current Python and platform tuple.",
    )
    run_parser.add_argument(
        "--state-fingerprint",
        help="Explicit state fingerprint. Defaults to the revision tree digest.",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable verification cache replay.",
    )
    add_json_flag(run_parser)
    run_parser.set_defaults(handler=run_verify)

    status_parser = verify_subparsers.add_parser(
        "status",
        help="Inspect the current verification status for a revision, checkpoint, or lineage head.",
    )
    status_target = status_parser.add_mutually_exclusive_group()
    status_target.add_argument("--revision", help="Revision to inspect. Defaults to HEAD.")
    status_target.add_argument("--checkpoint", help="Checkpoint to inspect.")
    status_target.add_argument("--lineage", help="Lineage whose head revision should be inspected.")
    status_parser.add_argument(
        "--command-identity",
        help="Command identity used to resolve cached or stale status.",
    )
    status_parser.add_argument("--environment-fingerprint", help="Environment fingerprint override.")
    status_parser.add_argument("--state-fingerprint", help="State fingerprint override.")
    add_json_flag(status_parser)
    status_parser.set_defaults(handler=run_status)


def run_verify(args: argparse.Namespace) -> int:
    repo = current_repository()
    revision_id = repo.resolve_revision(args.revision)
    if revision_id is None:
        raise FileNotFoundError(f"revision not found: {args.revision}")

    record = backend().record_verification(
        VerifyRevisionRequest(
            root=repo.root,
            revision_id=revision_id,
            definition_name=args.definition,
            command=tuple(args.command),
            allow_cache=not args.no_cache,
            state_fingerprint=args.state_fingerprint,
            environment_fingerprint=args.environment_fingerprint or _default_environment_fingerprint(),
            command_identity=args.command_identity,
        )
    )
    emit(args, record, _render_verification_record)
    return _verification_exit_code(record.status)


def run_status(args: argparse.Namespace) -> int:
    repo = current_repository()
    service = backend()
    owner_kind = "revision"
    owner_id = repo.resolve_revision(args.revision or "HEAD")
    linked_verification_id = None
    state_fingerprint = args.state_fingerprint

    if args.checkpoint:
        checkpoint = service.get_checkpoint(repo.root, args.checkpoint)
        owner_kind = "checkpoint"
        owner_id = checkpoint.checkpoint_id
        linked_verification_id = checkpoint.verification_id
        if state_fingerprint is None:
            state_fingerprint = checkpoint.revision_id
    elif args.lineage:
        lineage = service.get_lineage(repo.root, args.lineage)
        owner_kind = "revision"
        owner_id = lineage.head_revision
        if owner_id is None:
            raise FileNotFoundError(f"lineage has no head revision: {args.lineage}")
        revision = service.get_revision(repo.root, owner_id)
        linked_verification_id = revision.verification_id
        if state_fingerprint is None:
            state_fingerprint = revision.tree
    else:
        if owner_id is None:
            raise FileNotFoundError("revision not found: HEAD")
        revision = service.get_revision(repo.root, owner_id)
        linked_verification_id = revision.verification_id
        if state_fingerprint is None:
            state_fingerprint = revision.tree

    summary = service.get_verification_status(
        VerificationStatusRequest(
            root=repo.root,
            owner_kind=owner_kind,
            owner_id=owner_id,
            linked_verification_id=linked_verification_id,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=args.environment_fingerprint,
            command_identity=args.command_identity,
        )
    )
    emit(args, summary, _render_verification_summary)
    return 0


def _render_verification_record(record) -> str:
    return (
        f"{record.status.value}: {record.summary or '-'}\n"
        f"verification: {record.verification_id}\n"
        f"owner: {record.owner_kind}:{record.owner_id or '-'}\n"
        f"command: {record.command_identity or '-'}\n"
        f"artifacts: {', '.join(record.output_artifact_ids) or '-'}"
    )


def _render_verification_summary(summary) -> str:
    return (
        f"{summary.status.value}: {summary.summary or '-'}\n"
        f"verification: {summary.verification_id or '-'}\n"
        f"owner: {summary.owner_kind}:{summary.owner_id or '-'}\n"
        f"command: {summary.command_identity or '-'}\n"
        f"state: {short_id(summary.state_fingerprint)}\n"
        f"environment: {summary.environment_fingerprint or '-'}"
    )


def _verification_exit_code(status: VerificationStatus) -> int:
    if status in {VerificationStatus.PASSED, VerificationStatus.CACHED_PASS}:
        return 0
    return 1


def _default_environment_fingerprint() -> str:
    return (
        f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro};"
        f"platform={platform.system()}-{platform.machine()}"
    )
