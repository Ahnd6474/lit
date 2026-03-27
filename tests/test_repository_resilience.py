from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.commits import CommitMetadata, CommitRecord, serialize_commit
from lit.domain import OperationKind, OperationRecord, OperationStatus
from lit.refs import branch_ref
from lit.repository import Repository
from lit.storage import read_json, write_json
from lit.transactions import JournaledTransaction, utc_now
from lit.trees import TreeRecord, serialize_tree


def test_open_migrates_legacy_commit_store_into_v1_revision_records(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    tree_id = repo.store_object("trees", serialize_tree(TreeRecord()))
    legacy_commit = CommitRecord(
        tree=tree_id,
        parents=(),
        message="legacy bootstrap",
        metadata=CommitMetadata(author="legacy-bot", committed_at="2026-03-01T00:00:00Z"),
    )
    commit_id = repo.store_object("commits", serialize_commit(legacy_commit))
    repo.write_branch("main", commit_id)
    repo.set_head_ref(branch_ref("main"))

    shutil.rmtree(repo.layout.v1)

    reopened = Repository.open(tmp_path)
    revision = reopened.get_revision(commit_id)

    assert reopened.layout.revision_path(commit_id).exists()
    assert revision.provenance.actor_role == "legacy"
    assert revision.provenance.actor_id == "legacy-bot"
    assert revision.provenance.committed_at == "2026-03-01T00:00:00Z"
    assert reopened.get_lineage("main").head_revision == commit_id


def test_open_recovers_unfinished_transaction_and_marks_operation_failed(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"
    story.write_text("safe\n", encoding="utf-8")

    transaction = JournaledTransaction(repo.layout, kind="repair", message="simulate crash")
    transaction.__enter__()
    transaction.write_text(story, "broken\n")
    write_json(
        repo.layout.operation_path(transaction.operation_id),
        OperationRecord(
            operation_id=transaction.operation_id,
            kind=OperationKind.ROLLBACK,
            status=OperationStatus.RUNNING,
            repository_root=tmp_path.as_posix(),
            journal_path=repo.layout.journal_path(transaction.operation_id).as_posix(),
            started_at=utc_now(),
            message="simulate crash",
        ).to_dict(),
    )
    repo.layout.lock_path().write_text(
        '{\n  "created_at": "2026-03-28T00:00:00Z",\n  "pid": 999999,\n  "token": "stale"\n}\n',
        encoding="utf-8",
    )

    reopened = Repository.open(tmp_path)
    operation = OperationRecord.from_dict(
        read_json(repo.layout.operation_path(transaction.operation_id), default=None)
    )

    assert story.read_text(encoding="utf-8") == "safe\n"
    assert reopened.recovered_operations == (transaction.operation_id,)
    assert not repo.layout.lock_path().exists()
    assert operation.status is OperationStatus.FAILED

