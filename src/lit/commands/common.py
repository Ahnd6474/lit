"""Machine-facing lit CLI and backend surfaces serialize through typed contracts here. JSON keys, exit codes, provenance input fields, workspace identity fields, step policy fields, and operation projection fields are stable automation interfaces; commands may add human rendering, but they must not invent divergent shapes or infer workspace state from filesystem layout alone."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from lit.backend_api import LitBackendService
from lit.domain import ProvenanceInput, ProvenanceRecord, VerificationStatus
from lit.repository import Repository


class CliExitCode(IntEnum):
    SUCCESS = 0
    ERROR = 1
    USAGE_ERROR = 2
    NOT_FOUND = 3
    VERIFICATION_FAILED = 4
    CONFLICT = 5


CLI_EXIT_CODE_MAP = MappingProxyType(
    {
        "success": CliExitCode.SUCCESS,
        "error": CliExitCode.ERROR,
        "usage_error": CliExitCode.USAGE_ERROR,
        "not_found": CliExitCode.NOT_FOUND,
        "verification_failed": CliExitCode.VERIFICATION_FAILED,
        "conflict": CliExitCode.CONFLICT,
    }
)

PROVENANCE_INPUT_ENV_VARS = MappingProxyType(
    {
        "actor_role": "LIT_PROVENANCE_ACTOR_ROLE",
        "actor_id": "LIT_PROVENANCE_ACTOR_ID",
        "prompt_template": "LIT_PROVENANCE_PROMPT_TEMPLATE",
        "agent_family": "LIT_PROVENANCE_AGENT_FAMILY",
        "run_id": "LIT_PROVENANCE_RUN_ID",
        "block_id": "LIT_PROVENANCE_BLOCK_ID",
        "step_id": "LIT_PROVENANCE_STEP_ID",
        "lineage_id": "LIT_PROVENANCE_LINEAGE_ID",
        "committed_at": "LIT_PROVENANCE_COMMITTED_AT",
        "origin_commit": "LIT_PROVENANCE_ORIGIN_COMMIT",
        "rewritten_from": "LIT_PROVENANCE_REWRITTEN_FROM",
        "promoted_from": "LIT_PROVENANCE_PROMOTED_FROM",
    }
)

_PROVENANCE_ARGUMENT_SPECS = (
    ("actor_role", "--provenance-actor-role", "Stable actor role for automation provenance."),
    ("actor_id", "--provenance-actor-id", "Stable actor identifier for automation provenance."),
    ("prompt_template", "--provenance-prompt-template", "Prompt or policy template identifier."),
    ("agent_family", "--provenance-agent-family", "Agent family recorded in provenance."),
    ("run_id", "--provenance-run-id", "Workflow run identifier."),
    ("block_id", "--provenance-block-id", "Workflow block identifier."),
    ("step_id", "--provenance-step-id", "Workflow step identifier."),
    ("lineage_id", "--provenance-lineage-id", "Lineage identifier to stamp into provenance."),
    ("committed_at", "--provenance-committed-at", "Explicit commit/checkpoint timestamp."),
    ("origin_commit", "--provenance-origin-commit", "Origin Git or lit revision identifier."),
    ("rewritten_from", "--provenance-rewritten-from", "Prior revision rewritten by this action."),
    ("promoted_from", "--provenance-promoted-from", "Source lineage or revision promoted here."),
)


@dataclass(frozen=True, slots=True)
class AutomationError:
    code: str
    message: str
    details: Any = None

    def to_dict(self) -> dict[str, object]:
        payload = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            payload["details"] = _json_ready(self.details)
        return payload


@dataclass(frozen=True, slots=True)
class AutomationResultEnvelope:
    result: Any
    command: str | None = None
    exit_code: CliExitCode = CliExitCode.SUCCESS
    ok: bool = True

    def to_dict(self) -> dict[str, object]:
        payload = {
            "ok": self.ok,
            "exit_code": int(self.exit_code),
            "result": _json_ready(self.result),
        }
        if self.command is not None:
            payload["command"] = self.command
        return payload


@dataclass(frozen=True, slots=True)
class AutomationErrorEnvelope:
    error: AutomationError
    command: str | None = None
    exit_code: CliExitCode = CliExitCode.ERROR
    ok: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = {
            "ok": self.ok,
            "exit_code": int(self.exit_code),
            "error": self.error.to_dict(),
        }
        if self.command is not None:
            payload["command"] = self.command
        return payload


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )


def add_provenance_arguments(parser: argparse.ArgumentParser) -> None:
    for field_name, flag, help_text in _PROVENANCE_ARGUMENT_SPECS:
        parser.add_argument(
            flag,
            dest=f"provenance_{field_name}",
            help=help_text,
        )


def current_repository() -> Repository:
    return Repository.discover(Path.cwd())


def current_root() -> Path:
    return current_repository().root


def backend() -> LitBackendService:
    return LitBackendService()


def short_id(value: str | None) -> str:
    if not value:
        return "none"
    return value[:12]


def provenance_input_from_args(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
) -> ProvenanceInput:
    source_env = os.environ if env is None else env
    payload: dict[str, object] = {}
    for field_name, env_name in PROVENANCE_INPUT_ENV_VARS.items():
        value = getattr(args, f"provenance_{field_name}", None)
        if value in (None, ""):
            value = source_env.get(env_name)
        if value in (None, ""):
            continue
        payload[field_name] = value
    return ProvenanceInput.from_dict(payload)


def provenance_record_from_args(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
    fallback: ProvenanceRecord | None = None,
) -> ProvenanceRecord:
    return provenance_input_from_args(args, env=env).to_record(fallback=fallback)


def exit_code_for_exception(error: BaseException) -> CliExitCode:
    if isinstance(error, FileNotFoundError):
        return CliExitCode.NOT_FOUND
    if isinstance(error, ValueError):
        return CliExitCode.USAGE_ERROR
    return CliExitCode.ERROR


def exit_code_for_verification_status(status: VerificationStatus | str) -> CliExitCode:
    normalized = VerificationStatus.coerce(status)
    if normalized in {VerificationStatus.PASSED, VerificationStatus.CACHED_PASS}:
        return CliExitCode.SUCCESS
    return CliExitCode.VERIFICATION_FAILED


def emit(args: argparse.Namespace, payload: Any, render_human) -> None:
    if getattr(args, "json", False):
        json.dump(_json_ready(payload), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    text = render_human(payload)
    if text:
        print(text)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if is_dataclass(value):
        return {
            field.name: _json_ready(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    return str(value)


__all__ = [
    "AutomationError",
    "AutomationErrorEnvelope",
    "AutomationResultEnvelope",
    "CLI_EXIT_CODE_MAP",
    "CliExitCode",
    "add_json_flag",
    "add_provenance_arguments",
    "backend",
    "current_repository",
    "current_root",
    "emit",
    "exit_code_for_exception",
    "exit_code_for_verification_status",
    "provenance_input_from_args",
    "provenance_record_from_args",
    "short_id",
]
