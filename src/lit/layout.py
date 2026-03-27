"""Canonical lit v1 contracts for autonomous local workflows. Persisted revision, checkpoint, lineage, verification, artifact, and operation records serialize only through these versioned dataclasses and layout helpers; readers must tolerate legacy v0 commit JSON and absent fields. CLI, GUI, export, and future Jakal Flow adapters talk to a narrow backend API and must not hardcode .lit paths or invent metadata keys independently."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lit.refs import normalize_branch_name

LAYOUT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LitLayout:
    root: Path

    @property
    def dot_lit(self) -> Path:
        return self.root / ".lit"

    @property
    def config(self) -> Path:
        return self.dot_lit / "config.json"

    @property
    def head(self) -> Path:
        return self.dot_lit / "HEAD"

    @property
    def index(self) -> Path:
        return self.dot_lit / "index.json"

    @property
    def refs(self) -> Path:
        return self.dot_lit / "refs"

    @property
    def heads(self) -> Path:
        return self.refs / "heads"

    @property
    def tags(self) -> Path:
        return self.refs / "tags"

    @property
    def objects(self) -> Path:
        return self.dot_lit / "objects"

    @property
    def blobs(self) -> Path:
        return self.objects / "blobs"

    @property
    def trees(self) -> Path:
        return self.objects / "trees"

    @property
    def commits(self) -> Path:
        return self.objects / "commits"

    @property
    def state(self) -> Path:
        return self.dot_lit / "state"

    @property
    def merge_state(self) -> Path:
        return self.state / "merge.json"

    @property
    def rebase_state(self) -> Path:
        return self.state / "rebase.json"

    @property
    def v1(self) -> Path:
        return self.dot_lit / "v1"

    @property
    def revisions(self) -> Path:
        return self.v1 / "revisions"

    @property
    def checkpoints(self) -> Path:
        return self.v1 / "checkpoints"

    @property
    def lineages(self) -> Path:
        return self.v1 / "lineages"

    @property
    def verifications(self) -> Path:
        return self.v1 / "verifications"

    @property
    def artifacts(self) -> Path:
        return self.v1 / "artifacts"

    @property
    def operations(self) -> Path:
        return self.v1 / "operations"

    @property
    def journals(self) -> Path:
        return self.v1 / "journals"

    @property
    def locks(self) -> Path:
        return self.v1 / "locks"

    def branch_path(self, branch_name: str) -> Path:
        return self.heads / normalize_branch_name(branch_name)

    def legacy_commit_path(self, revision_id: str) -> Path:
        return self.commits / revision_id

    def revision_path(self, revision_id: str) -> Path:
        return self.revisions / f"{revision_id}.json"

    def checkpoint_path(self, checkpoint_id: str) -> Path:
        return self.checkpoints / f"{checkpoint_id}.json"

    def lineage_path(self, lineage_id: str) -> Path:
        return self.lineages / f"{lineage_id}.json"

    def verification_path(self, verification_id: str) -> Path:
        return self.verifications / f"{verification_id}.json"

    def artifact_dir(self, artifact_id: str) -> Path:
        return self.artifacts / artifact_id

    def artifact_record_path(self, artifact_id: str) -> Path:
        return self.artifact_dir(artifact_id) / "artifact.json"

    def artifact_payload_path(self, artifact_id: str, filename: str = "payload") -> Path:
        return self.artifact_dir(artifact_id) / filename

    def operation_path(self, operation_id: str) -> Path:
        return self.operations / f"{operation_id}.json"

    def journal_path(self, operation_id: str) -> Path:
        return self.journals / f"{operation_id}.jsonl"

    def lock_path(self, name: str = "repository") -> Path:
        return self.locks / f"{name}.lock"

    def managed_directories(self) -> tuple[Path, ...]:
        return (
            self.dot_lit,
            self.objects,
            self.blobs,
            self.trees,
            self.commits,
            self.refs,
            self.heads,
            self.tags,
            self.state,
            self.v1,
            self.revisions,
            self.checkpoints,
            self.lineages,
            self.verifications,
            self.artifacts,
            self.operations,
            self.journals,
            self.locks,
        )


__all__ = ["LAYOUT_SCHEMA_VERSION", "LitLayout"]
