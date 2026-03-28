from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lit.domain import ProvenanceRecord
from lit.repository import Repository


@dataclass(frozen=True, slots=True)
class GitExportRef:
    ref_name: str
    revision_id: str
    source_kind: str
    source_id: str


@dataclass(frozen=True, slots=True)
class GitExportCommit:
    revision_id: str
    message: str
    parents: tuple[str, ...]
    changed_paths: tuple[str, ...]
    trailers: tuple[tuple[str, str], ...]
    verification_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitExportPlan:
    repository_root: Path
    default_branch: str
    current_branch: str | None
    head_revision: str | None
    refs: tuple[GitExportRef, ...]
    commits: tuple[GitExportCommit, ...]


def build_git_export_plan(
    root: str | Path,
    *,
    start_revision: str | None = None,
    lineage_id: str | None = None,
) -> GitExportPlan:
    repo = Repository.open(root)
    checkpoints = repo.list_checkpoints(lineage_id=lineage_id)
    refs: list[GitExportRef] = []
    for branch in repo.list_branches():
        if branch.commit_id is None:
            continue
        refs.append(
            GitExportRef(
                ref_name=f"refs/heads/{branch.name}",
                revision_id=branch.commit_id,
                source_kind="branch",
                source_id=branch.name,
            )
        )
    for checkpoint in checkpoints:
        if checkpoint.revision_id is None or checkpoint.checkpoint_id is None:
            continue
        refs.append(
            GitExportRef(
                ref_name=_checkpoint_ref_name(checkpoint.name, checkpoint.checkpoint_id),
                revision_id=checkpoint.revision_id,
                source_kind="checkpoint",
                source_id=checkpoint.checkpoint_id,
            )
        )
    revisions = _collect_revisions(
        repo,
        start_revision=start_revision,
        lineage_id=lineage_id,
        refs=tuple(refs),
        checkpoints=checkpoints,
    )
    commits = tuple(
        GitExportCommit(
            revision_id=revision.revision_id or "",
            message=revision.message,
            parents=revision.parents,
            changed_paths=repo.changed_files(revision.revision_id),
            trailers=_trailers_for_revision(
                revision.provenance,
                verification_id=revision.verification_id,
                artifact_ids=_linked_artifact_ids(repo, revision.revision_id),
                checkpoint_ids=revision.checkpoint_ids,
            ),
            verification_id=revision.verification_id,
            artifact_ids=_linked_artifact_ids(repo, revision.revision_id),
            checkpoint_ids=revision.checkpoint_ids,
        )
        for revision in revisions
    )
    refs.sort(key=lambda item: (item.ref_name, item.revision_id))
    return GitExportPlan(
        repository_root=repo.root,
        default_branch=repo.config.default_branch,
        current_branch=repo.current_branch_name(),
        head_revision=repo.current_commit_id(),
        refs=tuple(refs),
        commits=commits,
    )


def _trailers_for_revision(
    provenance: ProvenanceRecord,
    *,
    verification_id: str | None,
    artifact_ids: tuple[str, ...],
    checkpoint_ids: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    trailers: list[tuple[str, str]] = []
    fields = (
        ("Lit-Actor-Role", provenance.actor_role),
        ("Lit-Actor-Id", provenance.actor_id),
        ("Lit-Prompt-Template", provenance.prompt_template),
        ("Lit-Agent-Family", provenance.agent_family),
        ("Lit-Run-Id", provenance.run_id),
        ("Lit-Block-Id", provenance.block_id),
        ("Lit-Step-Id", provenance.step_id),
        ("Lit-Lineage-Id", provenance.lineage_id),
        ("Lit-Verification-Status", provenance.verification_status.value),
        ("Lit-Verification-Summary", provenance.verification_summary),
        ("Lit-Committed-At", provenance.committed_at),
        ("Lit-Origin-Commit", provenance.origin_commit),
        ("Lit-Rewritten-From", provenance.rewritten_from),
        ("Lit-Promoted-From", provenance.promoted_from),
        ("Lit-Verification-Id", verification_id),
        ("Lit-Artifact-Ids", ",".join(artifact_ids) if artifact_ids else None),
        ("Lit-Checkpoint-Ids", ",".join(checkpoint_ids) if checkpoint_ids else None),
    )
    for key, value in fields:
        if value:
            trailers.append((key, str(value)))
    return tuple(trailers)


def _linked_artifact_ids(repo: Repository, revision_id: str | None) -> tuple[str, ...]:
    if revision_id is None:
        return ()
    artifact_ids: list[str] = []
    for manifest in repo.list_artifact_manifests(owner_kind="revision", owner_id=revision_id):
        if manifest.artifact_id is not None and manifest.artifact_id not in artifact_ids:
            artifact_ids.append(manifest.artifact_id)
    return tuple(artifact_ids)


def _checkpoint_ref_name(name: str | None, checkpoint_id: str) -> str:
    label = name or checkpoint_id
    safe = "".join(character if character.isalnum() else "-" for character in label).strip("-")
    suffix = checkpoint_id if safe == checkpoint_id else f"{safe}-{checkpoint_id}"
    return f"refs/tags/lit/checkpoints/{suffix}"


def _collect_revisions(
    repo: Repository,
    *,
    start_revision: str | None,
    lineage_id: str | None,
    refs: tuple[GitExportRef, ...],
    checkpoints: tuple[object, ...],
) -> tuple[object, ...]:
    candidates: list[str] = []
    if start_revision is not None:
        resolved = repo.resolve_revision(start_revision)
        if resolved is not None:
            candidates.append(resolved)
    elif lineage_id is not None:
        try:
            lineage = repo.get_managed_lineage(lineage_id)
        except FileNotFoundError:
            lineage = None
        if lineage is not None and lineage.head_revision is not None:
            candidates.append(lineage.head_revision)
    else:
        for ref in refs:
            if ref.revision_id not in candidates:
                candidates.append(ref.revision_id)
        for checkpoint in checkpoints:
            if checkpoint.revision_id is not None and checkpoint.revision_id not in candidates:
                candidates.append(checkpoint.revision_id)
        current = repo.current_commit_id()
        if current is not None and current not in candidates:
            candidates.append(current)

    ordered: list[object] = []
    seen: set[str] = set()
    for candidate in candidates:
        for commit_id, _ in repo.iter_commit_graph(candidate):
            if commit_id in seen:
                continue
            seen.add(commit_id)
            ordered.append(repo.get_revision(commit_id))
    return tuple(ordered)


__all__ = [
    "GitExportCommit",
    "GitExportPlan",
    "GitExportRef",
    "build_git_export_plan",
]
