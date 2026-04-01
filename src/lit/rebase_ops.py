from __future__ import annotations

from lit.workflows import RebaseResult, WorkflowService


def rebase_onto(repository, revision: str) -> RebaseResult:
    return WorkflowService(repository).rebase_onto(revision)


__all__ = ["RebaseResult", "WorkflowService", "rebase_onto"]
