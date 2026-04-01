"""Machine-facing lit CLI and backend surfaces serialize through typed contracts here. JSON keys, exit codes, provenance input fields, workspace identity fields, step policy fields, and operation projection fields are stable automation interfaces; commands may add human rendering, but they must not invent divergent shapes or infer workspace state from filesystem layout alone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lit.refs import normalize_branch_name

LAYOUT_SCHEMA_VERSION = 1
ObjectKind = Literal["blobs", "trees", "commits"]
ResumeStateKind = Literal["merge", "rebase"]


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
    def policy_config(self) -> Path:
        return self.config

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
    def checkpoint_refs(self) -> Path:
        return self.refs / "checkpoints"

    @property
    def safe_checkpoint_refs(self) -> Path:
        return self.checkpoint_refs / "safe"

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

    def object_dir(self, kind: ObjectKind) -> Path:
        return getattr(self, kind)

    def object_path(self, kind: ObjectKind, object_id: str) -> Path:
        return self.object_dir(kind) / object_id

    @property
    def state(self) -> Path:
        return self.dot_lit / "state"

    @property
    def merge_state(self) -> Path:
        return self.state / "merge.json"

    @property
    def rebase_state(self) -> Path:
        return self.state / "rebase.json"

    def resume_state_path(self, kind: ResumeStateKind) -> Path:
        if kind == "merge":
            return self.merge_state
        if kind == "rebase":
            return self.rebase_state
        raise ValueError(f"unsupported resume state kind: {kind}")

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
    def workspaces(self) -> Path:
        return self.v1 / "workspaces"

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

    def safe_checkpoint_ref_path(self, checkpoint_id: str) -> Path:
        return self.safe_checkpoint_refs / checkpoint_id

    @property
    def latest_safe_checkpoint_ref(self) -> Path:
        return self.safe_checkpoint_refs / "latest"

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

    def workspace_path(self, workspace_id: str) -> Path:
        return self.workspaces / f"{workspace_id}.json"

    def operation_path(self, operation_id: str) -> Path:
        return self.operations / f"{operation_id}.json"

    def journal_path(self, operation_id: str) -> Path:
        return self.journals / f"{operation_id}.jsonl"

    def journal_dir(self, operation_id: str) -> Path:
        return self.journals / operation_id

    def lock_path(self, name: str = "repository") -> Path:
        return self.locks / f"{name}.lock"

    def workspace_lock_path(self, workspace_id: str) -> Path:
        return self.lock_path(f"workspace-{workspace_id}")

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
            self.checkpoint_refs,
            self.safe_checkpoint_refs,
            self.state,
            self.v1,
            self.revisions,
            self.checkpoints,
            self.lineages,
            self.verifications,
            self.artifacts,
            self.workspaces,
            self.operations,
            self.journals,
            self.locks,
        )

__all__ = ["LAYOUT_SCHEMA_VERSION", "LitLayout", "ObjectKind", "ResumeStateKind"]
