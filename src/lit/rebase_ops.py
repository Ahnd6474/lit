from __future__ import annotations

from dataclasses import dataclass

from lit.commits import CommitRecord, serialize_commit
from lit.merge_ops import MergePlan, _current_branch, _ensure_operation_ready, _merge_trees
from lit.repository import Repository


@dataclass(frozen=True)
class RebaseResult:
    status: str
    message: str
    commit_id: str | None = None
    replayed: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def rebase_onto(repository: Repository, revision: str) -> RebaseResult:
    _ensure_operation_ready(repository)
    branch_name = repository.current_branch_name()
    head_commit = repository.current_commit_id()
    if branch_name is None or head_commit is None:
        raise ValueError("rebase requires the current branch to have at least one commit")

    onto_commit = repository.resolve_revision(revision)
    if onto_commit is None:
        raise ValueError(f"unknown revision: {revision}")
    if onto_commit == head_commit:
        return RebaseResult(status="noop", message="Already up to date.")

    base_commit = repository.merge_base(head_commit, onto_commit)
    pending = repository.commits_to_replay(head_commit, onto_commit)
    if base_commit == head_commit:
        repository.write_branch(branch_name, onto_commit)
        repository.apply_commit(onto_commit, baseline_commit=head_commit)
        repository.clear_rebase()
        return RebaseResult(
            status="fast_forward",
            message=f"Rebased by fast-forwarding to {onto_commit[:12]}.",
            commit_id=onto_commit,
        )
    if base_commit == onto_commit:
        return RebaseResult(status="noop", message="Already up to date.")

    repository.begin_rebase(
        onto=onto_commit,
        original_head=head_commit,
        pending_commits=pending,
        applied_commits=(),
    )

    current_base = onto_commit
    rewritten: list[str] = []
    for index, commit_id in enumerate(pending):
        record = repository.read_commit(commit_id)
        parent_commit = record.primary_parent
        parent_tree = repository.read_commit_tree(parent_commit)
        current_tree = repository.read_commit_tree(current_base)
        commit_tree = repository.read_commit_tree(commit_id)
        plan = _merge_trees(repository, parent_tree, current_tree, commit_tree)

        repository.apply_tree(plan.files, baseline=current_tree)
        if plan.conflicts:
            from lit.merge_ops import _write_conflicts

            _write_conflicts(repository, plan.conflicts)
            repository.advance_rebase(
                pending_commits=pending[index:],
                applied_commits=tuple(rewritten),
                current_commit=commit_id,
                conflicts=plan.conflict_paths,
            )
            return RebaseResult(
                status="conflict",
                message=f"Rebase stopped while replaying {commit_id[:12]}.",
                commit_id=current_base,
                replayed=tuple(rewritten),
                conflicts=plan.conflict_paths,
            )

        current_base = _rewrite_commit(repository, record, parent=current_base, tree=plan)
        rewritten.append(current_base)
        repository.apply_commit(current_base, baseline_commit=record.primary_parent)
        repository.advance_rebase(
            pending_commits=pending[index + 1 :],
            applied_commits=tuple(rewritten),
        )

    repository.clear_rebase()
    repository.write_branch(branch_name, current_base)
    repository.apply_commit(current_base, baseline_commit=head_commit)
    return RebaseResult(
        status="rebased",
        message=f"Rebased onto {revision} at {current_base[:12]}.",
        commit_id=current_base,
        replayed=tuple(rewritten),
    )


def _rewrite_commit(
    repository: Repository,
    record: CommitRecord,
    *,
    parent: str,
    tree: MergePlan,
) -> str:
    tree_id = repository._store_tree(tree.files)
    rewritten = CommitRecord(tree=tree_id, parents=(parent,), message=record.message)
    commit_id = repository.store_object("commits", serialize_commit(rewritten))
    repository.write_branch(_current_branch(repository), commit_id)
    repository.write_index(repository.read_index().__class__())
    return commit_id
