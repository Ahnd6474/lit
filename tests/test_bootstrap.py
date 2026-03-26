from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.commits import CommitRecord, commit_id, deserialize_commit, serialize_commit
from lit.repository import Repository


def test_init_creates_deterministic_repository_layout(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    expected_dirs = (
        repo.layout.dot_lit,
        repo.layout.objects,
        repo.layout.blobs,
        repo.layout.trees,
        repo.layout.commits,
        repo.layout.refs,
        repo.layout.heads,
        repo.layout.tags,
        repo.layout.state,
    )
    for directory in expected_dirs:
        assert directory.is_dir()

    assert repo.layout.config.read_text(encoding="utf-8") == (
        '{\n  "default_branch": "main",\n  "schema_version": 1\n}\n'
    )
    assert repo.layout.head.read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert repo.layout.index.read_text(encoding="utf-8") == '{\n  "entries": []\n}\n'
    assert repo.layout.branch_path("main").read_text(encoding="utf-8") == ""
    assert repo.layout.merge_state.read_text(encoding="utf-8") == "null\n"
    assert repo.layout.rebase_state.read_text(encoding="utf-8") == "null\n"


def test_open_reloads_repository_state_and_objects(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    payload = b"hello lit"

    object_id = repo.store_object("blobs", payload)
    reopened = Repository.open(tmp_path)

    assert reopened.current_branch_name() == "main"
    assert reopened.read_branch("main") is None
    assert reopened.read_object("blobs", object_id) == payload


def test_commit_serialization_is_deterministic() -> None:
    record = CommitRecord(tree="abc123", parents=("base1", "base2"), message="bootstrap")

    serialized = serialize_commit(record)

    assert serialized == (
        b'{\n  "message": "bootstrap",\n  "parents": [\n    "base1",\n    "base2"\n  ],\n'
        b'  "tree": "abc123"\n}\n'
    )
    assert deserialize_commit(serialized) == record
    assert commit_id(record) == commit_id(record)


def test_module_cli_init_is_runnable(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "lit", "init", "repo"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Initialized empty lit repository" in result.stdout
    assert (tmp_path / "repo" / ".lit" / "HEAD").read_text(encoding="utf-8") == (
        "ref: refs/heads/main\n"
    )
