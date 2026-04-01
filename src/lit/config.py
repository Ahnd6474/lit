"""Machine-facing lit CLI and backend surfaces serialize through typed contracts here. JSON keys, exit codes, provenance input fields, workspace identity fields, step policy fields, and operation projection fields are stable automation interfaces; commands may add human rendering, but they must not invent divergent shapes or infer workspace state from filesystem layout alone."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lit.domain import DOMAIN_SCHEMA_VERSION, LineageScopeKind
from lit.layout import LitLayout
from lit.refs import normalize_branch_name
from lit.storage import FileMutationWriter, read_json, write_json

CONFIG_SCHEMA_VERSION = DOMAIN_SCHEMA_VERSION


def _string(value: object | None, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Path)):
        return (str(value),)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


class SafeRollbackPreference(StrEnum):
    LINEAGE = "lineage"
    REPOSITORY = "repository"
    LINEAGE_THEN_REPOSITORY = "lineage_then_repository"

    @classmethod
    def coerce(cls, value: object | None) -> "SafeRollbackPreference":
        if value is None:
            return cls.LINEAGE_THEN_REPOSITORY
        try:
            return cls(str(value))
        except ValueError:
            return cls.LINEAGE_THEN_REPOSITORY


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    schema_version: int = CONFIG_SCHEMA_VERSION
    default_definition_name: str | None = None
    default_command: tuple[str, ...] = ()
    allow_cache: bool = True
    require_before_commit: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_definition_name": self.default_definition_name,
            "default_command": list(self.default_command),
            "allow_cache": self.allow_cache,
            "require_before_commit": self.require_before_commit,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "VerificationPolicy":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            default_definition_name=_optional_string(data.get("default_definition_name")),
            default_command=_string_tuple(data.get("default_command")),
            allow_cache=bool(data.get("allow_cache", True)),
            require_before_commit=bool(data.get("require_before_commit", False)),
        )


@dataclass(frozen=True, slots=True)
class CheckpointPolicy:
    schema_version: int = CONFIG_SCHEMA_VERSION
    safe_by_default: bool = True
    require_approval_for_safe: bool = False
    auto_pin_safe: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "safe_by_default": self.safe_by_default,
            "require_approval_for_safe": self.require_approval_for_safe,
            "auto_pin_safe": self.auto_pin_safe,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "CheckpointPolicy":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            safe_by_default=bool(data.get("safe_by_default", True)),
            require_approval_for_safe=bool(data.get("require_approval_for_safe", False)),
            auto_pin_safe=bool(data.get("auto_pin_safe", False)),
        )


@dataclass(frozen=True, slots=True)
class ArtifactPolicy:
    schema_version: int = CONFIG_SCHEMA_VERSION
    storage_dir: str = ".lit/v1/artifacts"
    preserve_on_rollback: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "storage_dir": self.storage_dir,
            "preserve_on_rollback": self.preserve_on_rollback,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactPolicy":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            storage_dir=_string(data.get("storage_dir"), default=".lit/v1/artifacts"),
            preserve_on_rollback=bool(data.get("preserve_on_rollback", True)),
        )


@dataclass(frozen=True, slots=True)
class LineagePolicy:
    schema_version: int = CONFIG_SCHEMA_VERSION
    default_base_checkpoint_strategy: str = "latest_safe"
    enforce_owned_paths: bool = False
    default_overlap_allowlist: tuple[str, ...] = ()
    default_affected_scope: LineageScopeKind = LineageScopeKind.CURRENT

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_base_checkpoint_strategy": self.default_base_checkpoint_strategy,
            "enforce_owned_paths": self.enforce_owned_paths,
            "default_overlap_allowlist": list(self.default_overlap_allowlist),
            "default_affected_scope": self.default_affected_scope.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "LineagePolicy":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            default_base_checkpoint_strategy=_string(
                data.get("default_base_checkpoint_strategy"),
                default="latest_safe",
            ),
            enforce_owned_paths=bool(data.get("enforce_owned_paths", False)),
            default_overlap_allowlist=_string_tuple(data.get("default_overlap_allowlist")),
            default_affected_scope=LineageScopeKind.coerce(
                data.get("default_affected_scope")
            ),
        )


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    schema_version: int = CONFIG_SCHEMA_VERSION
    allow_resume: bool = True
    safe_rollback_preference: SafeRollbackPreference = (
        SafeRollbackPreference.LINEAGE_THEN_REPOSITORY
    )
    expose_blockage_reason: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allow_resume": self.allow_resume,
            "safe_rollback_preference": self.safe_rollback_preference.value,
            "expose_blockage_reason": self.expose_blockage_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "OperationPolicy":
        if not data:
            return cls()
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            allow_resume=bool(data.get("allow_resume", True)),
            safe_rollback_preference=SafeRollbackPreference.coerce(
                data.get("safe_rollback_preference")
            ),
            expose_blockage_reason=bool(data.get("expose_blockage_reason", True)),
        )


@dataclass(frozen=True, slots=True)
class LitConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    default_branch: str = "main"
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    checkpoints: CheckpointPolicy = field(default_factory=CheckpointPolicy)
    artifacts: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    lineage: LineagePolicy = field(default_factory=LineagePolicy)
    operations: OperationPolicy = field(default_factory=OperationPolicy)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_branch": self.default_branch,
            "policies": {
                "verification": self.verification.to_dict(),
                "checkpoints": self.checkpoints.to_dict(),
                "artifacts": self.artifacts.to_dict(),
                "lineage": self.lineage.to_dict(),
                "operations": self.operations.to_dict(),
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "LitConfig":
        if not data:
            return cls()
        raw_policies = data.get("policies")
        policies = raw_policies if isinstance(raw_policies, Mapping) else {}
        return cls(
            schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
            default_branch=normalize_branch_name(
                _string(data.get("default_branch"), default="main")
            ),
            verification=VerificationPolicy.from_dict(
                policies.get("verification")
                if isinstance(policies.get("verification"), Mapping)
                else None
            ),
            checkpoints=CheckpointPolicy.from_dict(
                policies.get("checkpoints")
                if isinstance(policies.get("checkpoints"), Mapping)
                else None
            ),
            artifacts=ArtifactPolicy.from_dict(
                policies.get("artifacts")
                if isinstance(policies.get("artifacts"), Mapping)
                else None
            ),
            lineage=LineagePolicy.from_dict(
                policies.get("lineage")
                if isinstance(policies.get("lineage"), Mapping)
                else None
            ),
            operations=OperationPolicy.from_dict(
                policies.get("operations")
                if isinstance(policies.get("operations"), Mapping)
                else None
            ),
        )


def _layout_for(source: LitLayout | Path) -> LitLayout:
    if isinstance(source, LitLayout):
        return source
    return LitLayout(Path(source).expanduser().resolve())


def read_lit_config(source: LitLayout | Path) -> LitConfig:
    layout = _layout_for(source)
    return LitConfig.from_dict(read_json(layout.policy_config, default=None))


def write_lit_config(
    source: LitLayout | Path,
    config: LitConfig,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    layout = _layout_for(source)
    write_json(layout.policy_config, config.to_dict(), mutation=mutation)


__all__ = [
    "ArtifactPolicy",
    "CheckpointPolicy",
    "CONFIG_SCHEMA_VERSION",
    "LineagePolicy",
    "LitConfig",
    "OperationPolicy",
    "SafeRollbackPreference",
    "VerificationPolicy",
    "read_lit_config",
    "write_lit_config",
]
