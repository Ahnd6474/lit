from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.cli import build_parser
from lit.commits import CommitMetadata, CommitRecord, commit_id, deserialize_commit, serialize_commit
from lit.refs import branch_ref
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
    record = CommitRecord(
        tree="abc123",
        parents=("base1", "base2"),
        message="bootstrap",
        metadata=CommitMetadata(author="lit", committed_at="2026-03-26T00:00:00Z"),
    )

    serialized = serialize_commit(record)

    assert serialized == (
        b'{\n  "message": "bootstrap",\n  "metadata": {\n    "author": "lit",\n'
        b'    "committed_at": "2026-03-26T00:00:00Z"\n  },\n  "parents": [\n'
        b'    "base1",\n    "base2"\n  ],\n  "tree": "abc123"\n}\n'
    )
    assert deserialize_commit(serialized) == record
    assert commit_id(record) == commit_id(record)


def test_repository_branch_dag_and_operation_primitives(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    (tmp_path / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")

    repo.create_branch("feature", start_point=base_commit)

    (tmp_path / "story.txt").write_text("main\n", encoding="utf-8")
    main_commit = _commit_all(repo, "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    (tmp_path / "story.txt").write_text("feature\n", encoding="utf-8")
    feature_commit = _commit_all(repo, "feature")

    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(main_commit, baseline_commit=feature_commit)

    branches = repo.list_branches()
    assert [(branch.name, branch.current) for branch in branches] == [
        ("feature", False),
        ("main", True),
    ]
    assert repo.merge_base(main_commit, feature_commit) == base_commit
    assert repo.is_ancestor(base_commit, main_commit) is True
    assert repo.is_ancestor(main_commit, feature_commit) is False
    assert repo.first_parent_range(base_commit, feature_commit) == (feature_commit,)
    assert repo.commits_to_replay(feature_commit, main_commit) == (feature_commit,)

    merge_state = repo.begin_merge(
        base_commit=base_commit,
        current_commit=main_commit,
        target_commit=feature_commit,
        target_ref=branch_ref("feature"),
        conflicts=("story.txt",),
    )
    assert repo.current_operation() is not None
    assert repo.layout.merge_state.read_text(encoding="utf-8") == (
        '{\n  "base_commit": "'
        + base_commit
        + '",\n  "conflicts": [\n    "story.txt"\n  ],\n  "current_commit": "'
        + main_commit
        + '",\n  "head_ref": "refs/heads/main",\n  "target_commit": "'
        + feature_commit
        + '",\n  "target_ref": "refs/heads/feature"\n}\n'
    )
    assert merge_state.target_ref == "refs/heads/feature"
    repo.clear_merge()

    rebase_state = repo.begin_rebase(
        onto=main_commit,
        original_head=feature_commit,
        pending_commits=(feature_commit,),
    )
    assert repo.current_operation() is not None
    assert rebase_state.pending_commits == (feature_commit,)
    assert repo.layout.rebase_state.read_text(encoding="utf-8") == (
        '{\n  "applied_commits": [],\n  "conflicts": [],\n  "head_ref": "refs/heads/main",\n'
        '  "onto": "'
        + main_commit
        + '",\n  "original_head": "'
        + feature_commit
        + '",\n  "pending_commits": [\n    "'
        + feature_commit
        + '"\n  ]\n}\n'
    )


def test_cli_builds_real_command_modules() -> None:
    parser = build_parser()

    branch_args = parser.parse_args(["branch"])
    merge_args = parser.parse_args(["merge"])
    rebase_args = parser.parse_args(["rebase"])

    assert branch_args.handler.__module__ == "lit.commands.branch"
    assert merge_args.handler.__module__ == "lit.commands.merge"
    assert rebase_args.handler.__module__ == "lit.commands.rebase"


def test_module_cli_init_and_branch_are_runnable(tmp_path: Path) -> None:
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

    branch_result = subprocess.run(
        [sys.executable, "-m", "lit", "branch"],
        cwd=tmp_path / "repo",
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert branch_result.returncode == 0
    assert branch_result.stdout.strip() == "* main unborn"


def _commit_all(repo: Repository, message: str) -> str:
    repo.stage(["story.txt"])
    return repo.commit(message)
