from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lit.domain import (
    ArtifactRecord,
    CheckpointRecord,
    RevisionRecord,
    VerificationRecord,
    VerificationStatus,
)
from lit.layout import LitLayout
from lit.storage import hash_bytes, read_json, write_bytes, write_json
from lit.transactions import next_identifier, utc_now


@dataclass(frozen=True, slots=True)
class VerificationDefinition:
    name: str
    command: tuple[str, ...]
    command_identity: str | None = None

    @property
    def identity(self) -> str | None:
        if self.command_identity:
            return self.command_identity
        if not self.command:
            return None
        return " ".join(self.command)


@dataclass(frozen=True, slots=True)
class VerificationExecution:
    return_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    started_at: str | None = None
    finished_at: str | None = None
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationStatusSummary:
    owner_kind: str
    owner_id: str | None = None
    verification_id: str | None = None
    status: VerificationStatus = VerificationStatus.NEVER_VERIFIED
    summary: str | None = None
    command_identity: str | None = None
    state_fingerprint: str | None = None
    environment_fingerprint: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    output_artifact_ids: tuple[str, ...] = ()


class VerificationExecutor(Protocol):
    def execute(
        self,
        definition: VerificationDefinition,
        *,
        cwd: Path,
    ) -> VerificationExecution: ...


class VerificationDefinitionService:
    def __init__(self, layout: LitLayout) -> None:
        self.layout = layout

    def list_definitions(self) -> tuple[VerificationDefinition, ...]:
        raw = self._load_raw_definitions()
        if raw is None:
            return ()
        if isinstance(raw, Mapping):
            return tuple(
                self._definition_from_mapping(
                    {"name": str(name), **candidate}
                    if isinstance(candidate, Mapping)
                    else {"name": str(name), "command": candidate}
                )
                for name, candidate in raw.items()
            )
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return tuple(
                self._definition_from_candidate(candidate, index)
                for index, candidate in enumerate(raw, start=1)
            )
        raise ValueError("verification_commands must be a sequence or mapping")

    def get_definition(self, name: str | None = None) -> VerificationDefinition:
        definitions = self.list_definitions()
        if name is not None:
            for definition in definitions:
                if definition.name == name:
                    return definition
            raise KeyError(f"verification command not found: {name}")
        if len(definitions) == 1:
            return definitions[0]
        if not definitions:
            raise KeyError("repository does not define any verification commands")
        raise ValueError(
            "verification command name is required when multiple commands are configured"
        )

    def _load_raw_definitions(self) -> object | None:
        config = read_json(self.layout.config, default={}) or {}
        raw = config.get("verification_commands")
        if raw is not None:
            return raw
        verification = config.get("verification")
        if isinstance(verification, Mapping):
            return verification.get("commands")
        return None

    def _definition_from_candidate(
        self,
        candidate: object,
        index: int,
    ) -> VerificationDefinition:
        if isinstance(candidate, Mapping):
            return self._definition_from_mapping(
                candidate,
                fallback_name=f"verification-{index}",
            )
        return VerificationDefinition(
            name=f"verification-{index}",
            command=_command_tuple(candidate),
        )

    def _definition_from_mapping(
        self,
        candidate: Mapping[str, object],
        *,
        fallback_name: str | None = None,
    ) -> VerificationDefinition:
        name = str(candidate.get("name") or fallback_name or "verification")
        command = _command_tuple(candidate.get("command"))
        if not command:
            raise ValueError(f"verification command {name!r} requires a command")
        identity = _optional_string(candidate.get("command_identity"))
        return VerificationDefinition(
            name=name,
            command=command,
            command_identity=identity,
        )


class SubprocessVerificationExecutor:
    def execute(
        self,
        definition: VerificationDefinition,
        *,
        cwd: Path,
    ) -> VerificationExecution:
        if not definition.command:
            raise ValueError("verification command is required")
        started_at = utc_now()
        completed = subprocess.run(
            definition.command,
            cwd=str(cwd),
            capture_output=True,
            check=False,
        )
        finished_at = utc_now()
        return VerificationExecution(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started_at,
            finished_at=finished_at,
        )


class VerificationRecordStore:
    def __init__(self, layout: LitLayout) -> None:
        self.layout = layout

    def list_records(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[VerificationRecord, ...]:
        records: list[VerificationRecord] = []
        for path in sorted(self.layout.verifications.glob("*.json")):
            record = VerificationRecord.from_dict(read_json(path, default=None))
            if owner_kind is not None and record.owner_kind != owner_kind:
                continue
            if owner_id is not None and record.owner_id != owner_id:
                continue
            records.append(record)
        records.sort(key=_record_sort_key)
        return tuple(records)

    def get_record(self, verification_id: str) -> VerificationRecord:
        path = self.layout.verification_path(verification_id)
        if not path.exists():
            raise FileNotFoundError(f"verification not found: {verification_id}")
        return VerificationRecord.from_dict(read_json(path, default=None))

    def find_cache_record(
        self,
        *,
        state_fingerprint: str | None,
        environment_fingerprint: str | None,
        command_identity: str | None,
    ) -> VerificationRecord | None:
        if not _has_complete_cache_key(
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        ):
            return None
        candidates = [
            record
            for record in self.list_records()
            if record.state_fingerprint == state_fingerprint
            and record.environment_fingerprint == environment_fingerprint
            and record.command_identity == command_identity
            and replay_status_for(record.status) is not None
        ]
        if not candidates:
            return None
        return candidates[-1]

    def latest_owner_record(
        self,
        owner_kind: str,
        owner_id: str | None,
        *,
        command_identity: str | None = None,
    ) -> VerificationRecord | None:
        records = [
            record
            for record in self.list_records(owner_kind=owner_kind, owner_id=owner_id)
            if command_identity is None or record.command_identity == command_identity
        ]
        if not records:
            return None
        return records[-1]

    def persist_result(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        status: VerificationStatus,
        summary: str | None,
        state_fingerprint: str | None,
        environment_fingerprint: str | None,
        command_identity: str | None,
        return_code: int | None,
        output_streams: Mapping[str, bytes | bytearray | str] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> VerificationRecord:
        verification_id = next_identifier("verification")
        artifact_ids = self._persist_output_artifacts(
            verification_id,
            output_streams or {},
        )
        record = VerificationRecord(
            verification_id=verification_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            status=status,
            summary=summary,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
            started_at=started_at or utc_now(),
            finished_at=finished_at or utc_now(),
            return_code=return_code,
            output_artifact_ids=artifact_ids,
        )
        write_json(self.layout.verification_path(verification_id), record.to_dict())
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        path = self.layout.artifact_record_path(artifact_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        return ArtifactRecord.from_dict(read_json(path, default=None))

    def _persist_output_artifacts(
        self,
        verification_id: str,
        output_streams: Mapping[str, bytes | bytearray | str],
    ) -> tuple[str, ...]:
        created_at = utc_now()
        artifact_ids: list[str] = []
        for name, payload in output_streams.items():
            data, content_type = _coerce_output_payload(payload)
            if not data:
                continue
            artifact_id = next_identifier("artifact")
            filename = _artifact_filename(name)
            payload_path = self.layout.artifact_payload_path(artifact_id, filename)
            write_bytes(payload_path, data)
            artifact = ArtifactRecord(
                artifact_id=artifact_id,
                owner_kind="verification",
                owner_id=verification_id,
                kind=f"verification-output/{name}",
                relative_path=payload_path.relative_to(self.layout.root).as_posix(),
                content_type=content_type,
                digest=hash_bytes(data),
                size_bytes=len(data),
                created_at=created_at,
            )
            write_json(self.layout.artifact_record_path(artifact_id), artifact.to_dict())
            artifact_ids.append(artifact_id)
        return tuple(artifact_ids)


class VerificationCacheService:
    def __init__(self, records: VerificationRecordStore) -> None:
        self.records = records

    def find_replayable_result(
        self,
        *,
        state_fingerprint: str | None,
        environment_fingerprint: str | None,
        command_identity: str | None,
    ) -> VerificationRecord | None:
        return self.records.find_cache_record(
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        )

    def replay(self, record: VerificationRecord) -> VerificationRecord:
        replayed_status = replay_status_for(record.status)
        if replayed_status is None:
            raise ValueError(
                f"verification record {record.verification_id} is not replayable"
            )
        return VerificationRecord(
            verification_id=record.verification_id,
            owner_kind=record.owner_kind,
            owner_id=record.owner_id,
            status=replayed_status,
            summary=record.summary,
            state_fingerprint=record.state_fingerprint,
            environment_fingerprint=record.environment_fingerprint,
            command_identity=record.command_identity,
            started_at=record.started_at,
            finished_at=record.finished_at,
            return_code=record.return_code,
            output_artifact_ids=record.output_artifact_ids,
        )


class VerificationSummaryService:
    def __init__(
        self,
        records: VerificationRecordStore,
        cache: VerificationCacheService,
    ) -> None:
        self.records = records
        self.cache = cache

    def summarize_revision(
        self,
        revision: RevisionRecord,
        *,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        command_identity: str | None = None,
    ) -> VerificationStatusSummary:
        return self.summarize_owner(
            owner_kind="revision",
            owner_id=revision.revision_id,
            linked_verification_id=revision.verification_id,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        )

    def summarize_checkpoint(
        self,
        checkpoint: CheckpointRecord,
        *,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        command_identity: str | None = None,
    ) -> VerificationStatusSummary:
        return self.summarize_owner(
            owner_kind="checkpoint",
            owner_id=checkpoint.checkpoint_id,
            linked_verification_id=checkpoint.verification_id,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity,
        )

    def summarize_owner(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        linked_verification_id: str | None = None,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        command_identity: str | None = None,
    ) -> VerificationStatusSummary:
        linked = self._resolve_linked_record(
            owner_kind=owner_kind,
            owner_id=owner_id,
            linked_verification_id=linked_verification_id,
            command_identity=command_identity,
        )
        exact = self.cache.find_replayable_result(
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=command_identity
            or (linked.command_identity if linked is not None else None),
        )
        if exact is not None:
            if linked is not None and exact.verification_id == linked.verification_id:
                return _summary_from_record(owner_kind, owner_id, exact, status=exact.status)
            return _summary_from_record(
                owner_kind,
                owner_id,
                exact,
                status=replay_status_for(exact.status) or exact.status,
            )
        if linked is not None:
            stale_reasons = _stale_reasons(
                linked,
                state_fingerprint=state_fingerprint,
                environment_fingerprint=environment_fingerprint,
            )
            if stale_reasons and replay_status_for(linked.status) is not None:
                return _summary_from_record(
                    owner_kind,
                    owner_id,
                    linked,
                    status=VerificationStatus.STALE,
                    summary=f"stale: {' and '.join(stale_reasons)}",
                )
            return _summary_from_record(owner_kind, owner_id, linked, status=linked.status)
        return VerificationStatusSummary(
            owner_kind=owner_kind,
            owner_id=owner_id,
            status=VerificationStatus.NEVER_VERIFIED,
            command_identity=command_identity,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
        )

    def _resolve_linked_record(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        linked_verification_id: str | None,
        command_identity: str | None,
    ) -> VerificationRecord | None:
        linked: VerificationRecord | None = None
        if linked_verification_id is not None:
            try:
                linked = self.records.get_record(linked_verification_id)
            except FileNotFoundError:
                linked = None
        if linked is None:
            linked = self.records.latest_owner_record(
                owner_kind,
                owner_id,
                command_identity=command_identity,
            )
        if linked is None:
            return None
        if command_identity is not None and linked.command_identity != command_identity:
            return self.records.latest_owner_record(
                owner_kind,
                owner_id,
                command_identity=command_identity,
            )
        return linked


class VerificationRunService:
    def __init__(
        self,
        layout: LitLayout,
        *,
        definitions: VerificationDefinitionService | None = None,
        records: VerificationRecordStore | None = None,
        cache: VerificationCacheService | None = None,
        executor: VerificationExecutor | None = None,
    ) -> None:
        self.layout = layout
        self.definitions = definitions or VerificationDefinitionService(layout)
        self.records = records or VerificationRecordStore(layout)
        self.cache = cache or VerificationCacheService(self.records)
        self.executor = executor or SubprocessVerificationExecutor()

    def verify(
        self,
        *,
        owner_kind: str,
        owner_id: str | None,
        definition_name: str | None = None,
        definition: VerificationDefinition | None = None,
        command: Sequence[str] = (),
        command_identity: str | None = None,
        state_fingerprint: str | None = None,
        environment_fingerprint: str | None = None,
        allow_cache: bool = True,
    ) -> VerificationRecord:
        resolved = self._resolve_definition(
            definition_name=definition_name,
            definition=definition,
            command=command,
            command_identity=command_identity,
        )
        identity = resolved.identity
        cached = None
        if allow_cache:
            cached = self.cache.find_replayable_result(
                state_fingerprint=state_fingerprint,
                environment_fingerprint=environment_fingerprint,
                command_identity=identity,
            )
        if cached is not None:
            return self.cache.replay(cached)

        execution = self.executor.execute(resolved, cwd=self.layout.root)
        status = (
            VerificationStatus.PASSED
            if execution.return_code == 0
            else VerificationStatus.FAILED
        )
        summary = execution.summary or _default_execution_summary(
            resolved,
            status=status,
            return_code=execution.return_code,
        )
        return self.records.persist_result(
            owner_kind=owner_kind,
            owner_id=owner_id,
            status=status,
            summary=summary,
            state_fingerprint=state_fingerprint,
            environment_fingerprint=environment_fingerprint,
            command_identity=identity,
            return_code=execution.return_code,
            output_streams={"stdout": execution.stdout, "stderr": execution.stderr},
            started_at=execution.started_at,
            finished_at=execution.finished_at,
        )

    def _resolve_definition(
        self,
        *,
        definition_name: str | None,
        definition: VerificationDefinition | None,
        command: Sequence[str],
        command_identity: str | None,
    ) -> VerificationDefinition:
        if definition is not None:
            base = definition
        elif command:
            base = VerificationDefinition(
                name=definition_name or "verification",
                command=_command_tuple(command),
                command_identity=command_identity,
            )
        else:
            base = self.definitions.get_definition(definition_name)
        if not base.command:
            raise ValueError("verification command is required")
        if command_identity is None or command_identity == base.identity:
            return base
        return VerificationDefinition(
            name=base.name,
            command=base.command,
            command_identity=command_identity,
        )


def replay_status_for(status: VerificationStatus) -> VerificationStatus | None:
    if status in {VerificationStatus.PASSED, VerificationStatus.CACHED_PASS}:
        return VerificationStatus.CACHED_PASS
    if status in {VerificationStatus.FAILED, VerificationStatus.CACHED_FAIL}:
        return VerificationStatus.CACHED_FAIL
    return None


def _command_tuple(command: object) -> tuple[str, ...]:
    if command is None:
        return ()
    if isinstance(command, (str, bytes, bytearray, Path)):
        return (str(command),)
    if isinstance(command, Sequence):
        return tuple(str(part) for part in command)
    return (str(command),)


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _coerce_output_payload(payload: bytes | bytearray | str) -> tuple[bytes, str]:
    if isinstance(payload, bytearray):
        return bytes(payload), "application/octet-stream"
    if isinstance(payload, bytes):
        return payload, "application/octet-stream"
    return str(payload).encode("utf-8"), "text/plain; charset=utf-8"


def _artifact_filename(name: str) -> str:
    safe = "".join(
        character if character.isalnum() else "-"
        for character in name
    ).strip("-")
    return f"{safe or 'payload'}.txt"


def _has_complete_cache_key(
    *,
    state_fingerprint: str | None,
    environment_fingerprint: str | None,
    command_identity: str | None,
) -> bool:
    return all((state_fingerprint, environment_fingerprint, command_identity))


def _record_sort_key(record: VerificationRecord) -> tuple[str, str]:
    return (
        record.finished_at or record.started_at or "",
        record.verification_id or "",
    )


def _stale_reasons(
    record: VerificationRecord,
    *,
    state_fingerprint: str | None,
    environment_fingerprint: str | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if state_fingerprint is not None and record.state_fingerprint != state_fingerprint:
        reasons.append("state fingerprint changed")
    if (
        environment_fingerprint is not None
        and record.environment_fingerprint != environment_fingerprint
    ):
        reasons.append("environment fingerprint changed")
    return tuple(reasons)


def _default_execution_summary(
    definition: VerificationDefinition,
    *,
    status: VerificationStatus,
    return_code: int,
) -> str:
    if status is VerificationStatus.PASSED:
        return f"{definition.name} passed"
    return f"{definition.name} failed with exit code {return_code}"


def _summary_from_record(
    owner_kind: str,
    owner_id: str | None,
    record: VerificationRecord,
    *,
    status: VerificationStatus,
    summary: str | None = None,
) -> VerificationStatusSummary:
    return VerificationStatusSummary(
        owner_kind=owner_kind,
        owner_id=owner_id,
        verification_id=record.verification_id,
        status=status,
        summary=record.summary if summary is None else summary,
        command_identity=record.command_identity,
        state_fingerprint=record.state_fingerprint,
        environment_fingerprint=record.environment_fingerprint,
        started_at=record.started_at,
        finished_at=record.finished_at,
        return_code=record.return_code,
        output_artifact_ids=record.output_artifact_ids,
    )


__all__ = [
    "SubprocessVerificationExecutor",
    "VerificationCacheService",
    "VerificationDefinition",
    "VerificationDefinitionService",
    "VerificationExecution",
    "VerificationExecutor",
    "VerificationRecordStore",
    "VerificationRunService",
    "VerificationStatusSummary",
    "VerificationSummaryService",
    "replay_status_for",
]
