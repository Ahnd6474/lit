from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.domain import CheckpointRecord, RevisionRecord, VerificationStatus
from lit.repository import Repository
from lit.storage import read_json, write_json
from lit.verification import (
    VerificationCacheService,
    VerificationDefinitionService,
    VerificationExecution,
    VerificationRecordStore,
    VerificationRunService,
    VerificationSummaryService,
)


@dataclass
class FakeExecutor:
    results: list[VerificationExecution]
    calls: list[tuple[str, ...]] = field(default_factory=list)
    working_directories: list[Path] = field(default_factory=list)

    def execute(self, definition, *, cwd: Path) -> VerificationExecution:
        self.calls.append(definition.command)
        self.working_directories.append(cwd)
        return self.results.pop(0)


def test_definition_service_reads_repository_configured_commands(
    tmp_path: Path,
) -> None:
    repo = Repository.create(tmp_path)
    _write_verification_commands(
        repo,
        [
            {
                "name": "tests",
                "command": ["python", "-m", "pytest"],
                "command_identity": "pytest",
            },
            {
                "name": "smoke",
                "command": ["python", "-m", "lit", "status"],
            },
        ],
    )

    service = VerificationDefinitionService(repo.layout)

    definitions = service.list_definitions()

    assert [definition.name for definition in definitions] == ["tests", "smoke"]
    assert definitions[0].command == ("python", "-m", "pytest")
    assert definitions[0].identity == "pytest"
    assert definitions[1].identity == "python -m lit status"
    assert service.get_definition("tests").command == ("python", "-m", "pytest")


def test_record_store_persists_output_artifacts_as_references(
    tmp_path: Path,
) -> None:
    repo = Repository.create(tmp_path)
    store = VerificationRecordStore(repo.layout)

    record = store.persist_result(
        owner_kind="revision",
        owner_id="rev-1",
        status=VerificationStatus.PASSED,
        summary="tests passed",
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
        command_identity="pytest",
        return_code=0,
        output_streams={"stdout": "ok\n", "stderr": "warn\n"},
        started_at="2026-03-28T00:00:00Z",
        finished_at="2026-03-28T00:00:01Z",
    )

    loaded = store.get_record(record.verification_id or "")
    artifacts = {
        artifact.kind: artifact
        for artifact in (
            store.get_artifact(artifact_id)
            for artifact_id in record.output_artifact_ids
        )
    }

    assert loaded == record
    assert set(artifacts) == {
        "verification-output/stdout",
        "verification-output/stderr",
    }
    assert (
        tmp_path / artifacts["verification-output/stdout"].relative_path
    ).read_text(encoding="utf-8") == "ok\n"
    assert (
        tmp_path / artifacts["verification-output/stderr"].relative_path
    ).read_text(encoding="utf-8") == "warn\n"
    assert all(
        artifact.owner_id == record.verification_id for artifact in artifacts.values()
    )


@pytest.mark.parametrize(
    ("return_code", "stored_status", "cached_status"),
    [
        (0, VerificationStatus.PASSED, VerificationStatus.CACHED_PASS),
        (3, VerificationStatus.FAILED, VerificationStatus.CACHED_FAIL),
    ],
)
def test_run_service_replays_cached_results_for_identical_cache_key(
    tmp_path: Path,
    return_code: int,
    stored_status: VerificationStatus,
    cached_status: VerificationStatus,
) -> None:
    repo = Repository.create(tmp_path)
    _write_verification_commands(
        repo,
        [
            {
                "name": "tests",
                "command": ["python", "-m", "pytest"],
                "command_identity": "pytest",
            }
        ],
    )
    executor = FakeExecutor(
        [
            VerificationExecution(
                return_code=return_code,
                stdout=b"ran\n",
                stderr=b"",
                started_at="2026-03-28T00:00:00Z",
                finished_at="2026-03-28T00:00:03Z",
            )
        ]
    )
    store = VerificationRecordStore(repo.layout)
    cache = VerificationCacheService(store)
    service = VerificationRunService(
        repo.layout,
        records=store,
        cache=cache,
        executor=executor,
    )

    first = service.verify(
        owner_kind="revision",
        owner_id="rev-1",
        definition_name="tests",
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
    )
    second = service.verify(
        owner_kind="checkpoint",
        owner_id="cp-1",
        definition_name="tests",
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
    )

    assert first.status is stored_status
    assert second.status is cached_status
    assert second.verification_id == first.verification_id
    assert executor.calls == [("python", "-m", "pytest")]
    assert executor.working_directories == [tmp_path]
    assert len(store.list_records()) == 1


def test_summary_service_reports_exact_cached_and_stale_statuses(
    tmp_path: Path,
) -> None:
    repo = Repository.create(tmp_path)
    store = VerificationRecordStore(repo.layout)
    cache = VerificationCacheService(store)
    summaries = VerificationSummaryService(store, cache)
    record = store.persist_result(
        owner_kind="revision",
        owner_id="rev-1",
        status=VerificationStatus.PASSED,
        summary="tests passed",
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
        command_identity="pytest",
        return_code=0,
        started_at="2026-03-28T00:00:00Z",
        finished_at="2026-03-28T00:00:01Z",
    )

    revision = RevisionRecord(
        revision_id="rev-1",
        verification_id=record.verification_id,
    )
    checkpoint = CheckpointRecord(checkpoint_id="cp-1", revision_id="rev-1")

    exact = summaries.summarize_revision(
        revision,
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
        command_identity="pytest",
    )
    cached = summaries.summarize_checkpoint(
        checkpoint,
        state_fingerprint="tree-1",
        environment_fingerprint="env-1",
        command_identity="pytest",
    )
    stale = summaries.summarize_revision(
        revision,
        state_fingerprint="tree-2",
        environment_fingerprint="env-1",
        command_identity="pytest",
    )

    assert exact.status is VerificationStatus.PASSED
    assert exact.verification_id == record.verification_id
    assert cached.status is VerificationStatus.CACHED_PASS
    assert cached.verification_id == record.verification_id
    assert stale.status is VerificationStatus.STALE
    assert stale.summary == "stale: state fingerprint changed"


def _write_verification_commands(
    repo: Repository,
    commands: list[dict[str, object]],
) -> None:
    config = read_json(repo.layout.config, default={}) or {}
    config["verification_commands"] = commands
    write_json(repo.layout.config, config)
