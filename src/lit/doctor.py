from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lit.repository import Repository
from lit.storage import read_json
from lit.transactions import recover_pending_transactions

DoctorSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    severity: DoctorSeverity
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorStats:
    revisions: int = 0
    checkpoints: int = 0
    lineages: int = 0
    verifications: int = 0
    artifacts: int = 0
    operations: int = 0


@dataclass(frozen=True, slots=True)
class DoctorReport:
    repository_root: Path
    is_initialized: bool
    current_branch: str | None = None
    head_revision: str | None = None
    latest_safe_checkpoint_id: str | None = None
    recovered_operations: tuple[str, ...] = ()
    findings: tuple[DoctorFinding, ...] = ()
    stats: DoctorStats = field(default_factory=DoctorStats)

    @property
    def healthy(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)


def run_doctor(root: str | Path, *, repair: bool = False) -> DoctorReport:
    repository_root = Path(root).expanduser().resolve()
    dot_lit = repository_root / ".lit"
    if not dot_lit.is_dir():
        return _missing_repository_report(repository_root, dot_lit)

    repo = Repository.open(repository_root)
    recovered_operations = recover_pending_transactions(repo.layout) if repair else ()
    findings: list[DoctorFinding] = []

    _append_transaction_findings(findings, repo, repository_root, recovered_operations)

    lock_finding = _lock_finding(repo, repository_root)
    if lock_finding is not None:
        findings.append(lock_finding)

    current_branch, head_revision = _append_head_findings(findings, repo, repository_root)

    revision_ids = tuple(path.stem for path in sorted(repo.layout.revisions.glob("*.json")))
    checkpoints = repo.list_checkpoints()
    lineages = repo.list_managed_lineages()
    verifications = repo.list_verifications()
    artifacts = repo.list_artifact_manifests()

    _append_revision_findings(findings, repo, repository_root, revision_ids)
    _append_checkpoint_findings(findings, repo, repository_root, checkpoints)
    _append_lineage_findings(findings, repo, repository_root, lineages)
    _append_artifact_findings(findings, repository_root, artifacts)

    stats = DoctorStats(
        revisions=len(revision_ids),
        checkpoints=len(checkpoints),
        lineages=len(lineages),
        verifications=len(verifications),
        artifacts=len(artifacts),
        operations=sum(1 for _ in repo.layout.operations.glob("*.json")),
    )
    return DoctorReport(
        repository_root=repository_root,
        is_initialized=True,
        current_branch=current_branch,
        head_revision=head_revision,
        latest_safe_checkpoint_id=_latest_safe_checkpoint_id(checkpoints, lineage_id=current_branch)
        or _latest_safe_checkpoint_id(checkpoints),
        recovered_operations=recovered_operations,
        findings=tuple(findings),
        stats=stats,
    )


def _missing_repository_report(repository_root: Path, dot_lit: Path) -> DoctorReport:
    return DoctorReport(
        repository_root=repository_root,
        is_initialized=False,
        findings=(
            DoctorFinding(
                severity="error",
                code="repository_missing",
                message=f"lit repository metadata not found at {dot_lit}",
                path=".lit",
            ),
        ),
    )


def _append_transaction_findings(
    findings: list[DoctorFinding],
    repo: Repository,
    repository_root: Path,
    recovered_operations: tuple[str, ...],
) -> None:
    journals_path = _repository_relative_path(repository_root, repo.layout.journals)
    if recovered_operations:
        findings.append(
            DoctorFinding(
                severity="warning",
                code="transactions_recovered",
                message=f"recovered {len(recovered_operations)} unfinished transaction(s)",
                path=journals_path,
            )
        )
        return
    if _has_pending_journals(repo):
        findings.append(
            DoctorFinding(
                severity="warning",
                code="unfinished_transactions",
                message="unfinished repository transactions are waiting for recovery",
                path=journals_path,
            )
        )


def _append_head_findings(
    findings: list[DoctorFinding],
    repo: Repository,
    repository_root: Path,
) -> tuple[str | None, str | None]:
    if repo.current_head_target() is None:
        findings.append(
            DoctorFinding(
                severity="warning",
                code="head_unset",
                message="HEAD is unset",
                path=_repository_relative_path(repository_root, repo.layout.head),
            )
        )

    current_branch = repo.current_branch_name()
    head_revision = repo.current_commit_id()
    if current_branch is not None:
        branch_path = repo.layout.branch_path(current_branch)
        if not branch_path.exists():
            findings.append(
                DoctorFinding(
                    severity="error",
                    code="branch_ref_missing",
                    message=f"current branch ref is missing for {current_branch}",
                    path=_repository_relative_path(repository_root, branch_path),
                )
            )
    return current_branch, head_revision


def _append_revision_findings(
    findings: list[DoctorFinding],
    repo: Repository,
    repository_root: Path,
    revision_ids: tuple[str, ...],
) -> None:
    for revision_id in revision_ids:
        revision = repo.get_revision(revision_id)
        if not _verification_missing(repo, revision.verification_id):
            continue
        revision_path = repo.layout.revision_path(revision.revision_id or "")
        findings.append(
            DoctorFinding(
                severity="warning",
                code="revision_verification_missing",
                message=(
                    f"revision {revision.revision_id} links missing verification "
                    f"{revision.verification_id}"
                ),
                path=_repository_relative_path(repository_root, revision_path),
            )
        )


def _append_checkpoint_findings(
    findings: list[DoctorFinding],
    repo: Repository,
    repository_root: Path,
    checkpoints: tuple[object, ...],
) -> None:
    for checkpoint in checkpoints:
        checkpoint_path = repo.layout.checkpoint_path(checkpoint.checkpoint_id or "")
        path = _repository_relative_path(repository_root, checkpoint_path)
        if checkpoint.revision_id is None:
            findings.append(
                DoctorFinding(
                    severity="error",
                    code="checkpoint_without_revision",
                    message=f"checkpoint {checkpoint.checkpoint_id} has no revision",
                    path=path,
                )
            )
            continue
        try:
            repo.get_revision(checkpoint.revision_id)
        except FileNotFoundError:
            findings.append(
                DoctorFinding(
                    severity="error",
                    code="checkpoint_revision_missing",
                    message=(
                        f"checkpoint {checkpoint.checkpoint_id} points to missing revision "
                        f"{checkpoint.revision_id}"
                    ),
                    path=path,
                )
            )
        if _verification_missing(repo, checkpoint.verification_id):
            findings.append(
                DoctorFinding(
                    severity="warning",
                    code="checkpoint_verification_missing",
                    message=(
                        f"checkpoint {checkpoint.checkpoint_id} links missing verification "
                        f"{checkpoint.verification_id}"
                    ),
                    path=path,
                )
            )


def _append_lineage_findings(
    findings: list[DoctorFinding],
    repo: Repository,
    repository_root: Path,
    lineages: tuple[object, ...],
) -> None:
    for lineage in lineages:
        lineage_path = repo.layout.lineage_path(lineage.lineage_id)
        path = _repository_relative_path(repository_root, lineage_path)
        if lineage.head_revision is not None:
            try:
                repo.get_revision(lineage.head_revision)
            except FileNotFoundError:
                findings.append(
                    DoctorFinding(
                        severity="error",
                        code="lineage_head_missing",
                        message=(
                            f"lineage {lineage.lineage_id} points to missing head revision "
                            f"{lineage.head_revision}"
                        ),
                        path=path,
                    )
                )
        if lineage.base_checkpoint_id is not None:
            try:
                repo.get_checkpoint(lineage.base_checkpoint_id)
            except FileNotFoundError:
                findings.append(
                    DoctorFinding(
                        severity="error",
                        code="lineage_checkpoint_missing",
                        message=(
                            f"lineage {lineage.lineage_id} points to missing base checkpoint "
                            f"{lineage.base_checkpoint_id}"
                        ),
                        path=path,
                    )
                )


def _append_artifact_findings(
    findings: list[DoctorFinding],
    repository_root: Path,
    artifacts: tuple[object, ...],
) -> None:
    for artifact in artifacts:
        if artifact.relative_path and not (repository_root / artifact.relative_path).exists():
            findings.append(
                DoctorFinding(
                    severity="warning",
                    code="artifact_payload_missing",
                    message=(
                        f"artifact {artifact.artifact_id} payload is missing from "
                        f"{artifact.relative_path}"
                    ),
                    path=artifact.relative_path,
                )
            )


def _latest_safe_checkpoint_id(
    checkpoints: tuple[object, ...],
    *,
    lineage_id: str | None = None,
) -> str | None:
    safe = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.safe and (lineage_id is None or checkpoint.provenance.lineage_id == lineage_id)
    ]
    return None if not safe else safe[-1].checkpoint_id


def _verification_missing(repo: Repository, verification_id: str | None) -> bool:
    if verification_id is None:
        return False
    try:
        repo.get_verification(verification_id)
    except FileNotFoundError:
        return True
    return False


def _repository_relative_path(repository_root: Path, path: Path) -> str:
    return path.relative_to(repository_root).as_posix()


def _has_pending_journals(repo: Repository) -> bool:
    for journal_path in repo.layout.journals.glob("*.jsonl"):
        if _journal_is_unfinished(journal_path):
            return True
    return False


def _journal_is_unfinished(path: Path) -> bool:
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not events:
        return False
    return str(events[-1].get("event", "")) not in {"commit", "rollback"}


def _lock_finding(repo: Repository, repository_root: Path) -> DoctorFinding | None:
    lock_path = repo.layout.lock_path()
    if not lock_path.exists():
        return None
    owner = read_json(lock_path, default={}) or {}
    pid = owner.get("pid")
    if isinstance(pid, int) and _pid_is_alive(pid):
        return DoctorFinding(
            severity="warning",
            code="repository_locked",
            message=f"repository lock is currently held by pid {pid}",
            path=lock_path.relative_to(repository_root).as_posix(),
        )
    return DoctorFinding(
        severity="warning",
        code="stale_lock",
        message="repository lock appears stale and can be cleared by a repair run",
        path=lock_path.relative_to(repository_root).as_posix(),
    )


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


__all__ = [
    "DoctorFinding",
    "DoctorReport",
    "DoctorSeverity",
    "DoctorStats",
    "run_doctor",
]
