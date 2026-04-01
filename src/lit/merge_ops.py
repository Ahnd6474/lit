from __future__ import annotations

from lit.workflows import ConflictFile, MergePlan, MergeResult, WorkflowService


def merge_revision(repository, revision: str) -> MergeResult:
    return WorkflowService(repository).merge_revision(revision)


__all__ = [
    "ConflictFile",
    "MergePlan",
    "MergeResult",
    "WorkflowService",
    "merge_revision",
]
