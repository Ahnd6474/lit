from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.cli import build_parser
from lit.commits import CommitMetadata, CommitRecord, commit_id, deserialize_commit, serialize_commit
from lit.merge_ops import merge_revision
from lit.refs import branch_ref
from lit.rebase_ops import rebase_onto
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


def test_repository_checkout_switches_branches_and_detaches_head(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    nested = tmp_path / "docs" / "guide.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("base\n", encoding="utf-8")
    base_commit = _commit_path(repo, "docs")
    repo.create_branch("feature", start_point=base_commit)

    nested.write_text("main\n", encoding="utf-8")
    (tmp_path / "docs" / "main-only.txt").write_text("present\n", encoding="utf-8")
    main_commit = _commit_path(repo, "docs")

    checkout = repo.checkout("feature")
    assert checkout.branch_name == "feature"
    assert repo.current_branch_name() == "feature"
    assert repo.current_commit_id() == base_commit
    assert repo.layout.head.read_text(encoding="utf-8") == "ref: refs/heads/feature\n"
    assert nested.read_text(encoding="utf-8") == "base\n"
    assert not (tmp_path / "docs" / "main-only.txt").exists()

    (tmp_path / "docs" / "main-only.txt").write_text("scratch\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="overwrite untracked paths"):
        repo.checkout("main")
    (tmp_path / "docs" / "main-only.txt").unlink()

    detached = repo.checkout(main_commit)
    assert detached.detached is True
    assert repo.current_branch_name() is None
    assert repo.current_commit_id() == main_commit
    assert repo.layout.head.read_text(encoding="utf-8") == f"{main_commit}\n"
    assert nested.read_text(encoding="utf-8") == "main\n"
    assert (tmp_path / "docs" / "main-only.txt").read_text(encoding="utf-8") == "present\n"

    nested.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="clean index and tracked working tree"):
        repo.checkout("feature")
    nested.write_text("main\n", encoding="utf-8")

    switched_back = repo.checkout("main")
    assert switched_back.branch_name == "main"
    assert repo.current_branch_name() == "main"
    assert repo.current_commit_id() == main_commit
    assert repo.layout.head.read_text(encoding="utf-8") == "ref: refs/heads/main\n"


def test_restore_restores_nested_paths_and_clears_selected_index_entries(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    nested = tmp_path / "docs" / "guide.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("saved\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("baseline\n", encoding="utf-8")
    base_commit = _commit_path(repo, ".")

    nested.write_text("edited\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("changed\n", encoding="utf-8")
    repo.stage(["docs", "notes.txt"])

    restored = repo.restore(["docs"], source=base_commit)

    assert restored == ("docs/guide.txt",)
    assert nested.read_text(encoding="utf-8") == "saved\n"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "changed\n"
    assert [entry.path for entry in repo.read_index().entries] == ["notes.txt"]


def test_cli_builds_real_command_modules() -> None:
    parser = build_parser()

    branch_args = parser.parse_args(["branch"])
    checkout_args = parser.parse_args(["checkout", "main"])
    merge_args = parser.parse_args(["merge", "feature"])
    rebase_args = parser.parse_args(["rebase", "main"])

    assert branch_args.handler.__module__ == "lit.commands.branch"
    assert checkout_args.handler.__module__ == "lit.commands.checkout"
    assert merge_args.handler.__module__ == "lit.commands.merge"
    assert rebase_args.handler.__module__ == "lit.commands.rebase"


def test_merge_revision_creates_real_merge_commit(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    (tmp_path / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")

    repo.create_branch("feature", start_point=base_commit)

    (tmp_path / "story.txt").write_text("main\n", encoding="utf-8")
    main_commit = _commit_all(repo, "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    (tmp_path / "side.txt").write_text("feature\n", encoding="utf-8")
    repo.stage(["side.txt"])
    feature_commit = repo.commit("feature")

    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(main_commit, baseline_commit=feature_commit)

    result = merge_revision(repo, "feature")

    assert result.status == "merged"
    merge_commit = repo.current_commit_id()
    assert merge_commit is not None
    record = repo.read_commit(merge_commit)
    assert record.parents == (main_commit, feature_commit)
    assert (tmp_path / "story.txt").read_text(encoding="utf-8") == "main\n"
    assert (tmp_path / "side.txt").read_text(encoding="utf-8") == "feature\n"
    assert repo.read_merge_state() is None


def test_merge_revision_persists_conflict_state_and_markers(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    (tmp_path / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")
    repo.create_branch("feature", start_point=base_commit)

    (tmp_path / "story.txt").write_text("main change\n", encoding="utf-8")
    main_commit = _commit_all(repo, "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    (tmp_path / "story.txt").write_text("feature change\n", encoding="utf-8")
    feature_commit = _commit_all(repo, "feature")

    repo.set_head_ref(branch_ref("main"))
    repo.apply_commit(main_commit, baseline_commit=feature_commit)

    result = merge_revision(repo, "feature")

    assert result.status == "conflict"
    assert result.conflicts == ("story.txt",)
    conflict_text = (tmp_path / "story.txt").read_text(encoding="utf-8")
    assert "<<<<<<< current" in conflict_text
    assert "main change" in conflict_text
    assert "feature change" in conflict_text
    state = repo.read_merge_state()
    assert state is not None
    assert state.base_commit == base_commit
    assert state.current_commit == main_commit
    assert state.target_commit == feature_commit
    assert state.conflicts == ("story.txt",)


def test_rebase_onto_rewrites_local_commits(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    (tmp_path / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")
    repo.create_branch("feature", start_point=base_commit)

    (tmp_path / "main.txt").write_text("main\n", encoding="utf-8")
    repo.stage(["main.txt"])
    main_commit = repo.commit("main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    repo.stage(["feature.txt"])
    original_feature = repo.commit("feature")

    result = rebase_onto(repo, "main")

    assert result.status == "rebased"
    rebased_head = repo.current_commit_id()
    assert rebased_head is not None
    assert rebased_head != original_feature
    assert repo.read_commit(rebased_head).parents == (main_commit,)
    assert (tmp_path / "main.txt").read_text(encoding="utf-8") == "main\n"
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    assert repo.read_rebase_state() is None


def test_rebase_onto_persists_conflict_state_and_markers(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)

    (tmp_path / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")
    repo.create_branch("feature", start_point=base_commit)

    (tmp_path / "story.txt").write_text("main change\n", encoding="utf-8")
    main_commit = _commit_all(repo, "main")

    repo.set_head_ref(branch_ref("feature"))
    repo.apply_commit(base_commit, baseline_commit=main_commit)
    (tmp_path / "story.txt").write_text("feature change\n", encoding="utf-8")
    feature_commit = _commit_all(repo, "feature")

    result = rebase_onto(repo, "main")

    assert result.status == "conflict"
    assert result.conflicts == ("story.txt",)
    state = repo.read_rebase_state()
    assert state is not None
    assert state.original_head == feature_commit
    assert state.onto == main_commit
    assert state.current_commit == feature_commit
    assert state.pending_commits == (feature_commit,)
    assert state.conflicts == ("story.txt",)
    conflict_text = (tmp_path / "story.txt").read_text(encoding="utf-8")
    assert "<<<<<<< current" in conflict_text
    assert "main change" in conflict_text
    assert "feature change" in conflict_text


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


def test_module_cli_checkout_switches_branch_and_detaches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)

    (repo_root / "story.txt").write_text("base\n", encoding="utf-8")
    base_commit = _commit_all(repo, "base")
    repo.create_branch("feature", start_point=base_commit)

    (repo_root / "story.txt").write_text("main\n", encoding="utf-8")
    main_commit = _commit_all(repo, "main")

    branch_result = subprocess.run(
        [sys.executable, "-m", "lit", "checkout", "feature"],
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert branch_result.returncode == 0
    assert branch_result.stdout.strip() == "switched to branch feature"
    assert repo.layout.head.read_text(encoding="utf-8") == "ref: refs/heads/feature\n"
    assert (repo_root / "story.txt").read_text(encoding="utf-8") == "base\n"

    detached_result = subprocess.run(
        [sys.executable, "-m", "lit", "checkout", main_commit],
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert detached_result.returncode == 0
    assert detached_result.stdout.strip() == f"detached HEAD at {main_commit[:12]}"
    assert repo.layout.head.read_text(encoding="utf-8") == f"{main_commit}\n"
    assert (repo_root / "story.txt").read_text(encoding="utf-8") == "main\n"


def _commit_all(repo: Repository, message: str) -> str:
    repo.stage(["story.txt"])
    return repo.commit(message)


def _commit_path(repo: Repository, path: str, message: str = "commit") -> str:
    repo.stage([path])
    return repo.commit(message)
