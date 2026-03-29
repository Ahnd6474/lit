from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.cli import build_parser
from lit.backend_api import (
    BackendService,
    CreateCheckpointRequest,
    CreateRevisionRequest,
    OpenRepositoryRequest,
    RepositoryHandle,
)
from lit.commits import CommitMetadata, CommitRecord, commit_id, deserialize_commit, serialize_commit
from lit.domain import ApprovalState, ProvenanceRecord, RevisionRecord, VerificationStatus
from lit.layout import LitLayout
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


def test_v1_contract_modules_freeze_layout_and_backend_surface(tmp_path: Path) -> None:
    legacy_revision = RevisionRecord.from_dict(
        {
            "tree": "abc123",
            "parents": ["base1"],
            "message": "bootstrap",
            "metadata": {
                "author": "lit",
                "committed_at": "2026-03-26T00:00:00Z",
            },
        }
    )

    assert legacy_revision.schema_version == 0
    assert legacy_revision.tree == "abc123"
    assert legacy_revision.parents == ("base1",)
    assert legacy_revision.provenance.actor_role == "legacy"
    assert legacy_revision.provenance.actor_id == "lit"
    assert legacy_revision.provenance.committed_at == "2026-03-26T00:00:00Z"
    assert legacy_revision.provenance.verification_status is VerificationStatus.NEVER_VERIFIED
    assert legacy_revision.to_dict()["provenance"]["verification_status"] == "never_verified"

    layout = LitLayout(tmp_path)
    assert layout.branch_path("feature/demo") == tmp_path / ".lit" / "refs" / "heads" / "feature" / "demo"
    assert layout.revision_path("rev-1") == tmp_path / ".lit" / "v1" / "revisions" / "rev-1.json"
    assert layout.checkpoint_path("cp-1") == tmp_path / ".lit" / "v1" / "checkpoints" / "cp-1.json"
    assert layout.lineage_path("main") == tmp_path / ".lit" / "v1" / "lineages" / "main.json"
    assert layout.verification_path("ver-1") == tmp_path / ".lit" / "v1" / "verifications" / "ver-1.json"
    assert layout.artifact_record_path("art-1") == (
        tmp_path / ".lit" / "v1" / "artifacts" / "art-1" / "artifact.json"
    )
    assert layout.lock_path() == tmp_path / ".lit" / "v1" / "locks" / "repository.lock"

    handle = RepositoryHandle.for_root(tmp_path, current_branch="main", is_initialized=True)
    assert handle.layout.revisions == layout.revisions
    assert handle.current_branch == "main"
    assert handle.is_initialized is True

    open_request = OpenRepositoryRequest(root=tmp_path, create_if_missing=True)
    revision_request = CreateRevisionRequest(
        root=tmp_path,
        message="ship",
        provenance=ProvenanceRecord(lineage_id="main"),
    )
    checkpoint_request = CreateCheckpointRequest(
        root=tmp_path,
        revision_id="rev-1",
        approval_state=ApprovalState.PENDING,
    )

    assert open_request.create_if_missing is True
    assert revision_request.provenance.lineage_id == "main"
    assert checkpoint_request.safe is True
    assert checkpoint_request.approval_state is ApprovalState.PENDING
    assert {
        "open_repository",
        "initialize_repository",
        "get_repository_state",
        "list_revisions",
        "get_revision",
        "create_revision",
        "list_checkpoints",
        "get_checkpoint",
        "create_checkpoint",
        "rollback_to_checkpoint",
        "list_lineages",
        "get_lineage",
        "create_lineage",
        "switch_lineage",
        "promote_lineage",
        "record_verification",
        "get_verification",
        "list_artifacts",
        "get_artifact",
    } <= BackendService.__abstractmethods__


def test_release_version_strings_match_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]

    import lit
    import lit_gui

    assert version == "1.0.0"
    assert lit.__version__ == version
    assert lit_gui.__version__ == version


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
    main_only = tmp_path / "docs" / "main-only.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("base\n", encoding="utf-8")
    base_commit = _commit_path(repo, "docs")
    repo.create_branch("feature", start_point=base_commit)

    nested.write_text("main\n", encoding="utf-8")
    main_only.write_text("present\n", encoding="utf-8")
    main_commit = _commit_path(repo, "docs")

    checkout = repo.checkout("feature")
    assert checkout.branch_name == "feature"
    assert checkout.commit_id == base_commit
    assert repo.layout.head.read_text(encoding="utf-8") == "ref: refs/heads/feature\n"
    assert nested.read_text(encoding="utf-8") == "base\n"
    assert not main_only.exists()

    main_only.write_text("scratch\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="overwrite untracked paths"):
        repo.checkout("main")
    main_only.unlink()

    detached = repo.checkout(main_commit)
    assert detached.detached is True
    assert detached.commit_id == main_commit
    assert repo.layout.head.read_text(encoding="utf-8") == f"{main_commit}\n"
    assert nested.read_text(encoding="utf-8") == "main\n"
    assert main_only.read_text(encoding="utf-8") == "present\n"

    nested.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="clean index and tracked working tree"):
        repo.checkout("feature")
    nested.write_text("main\n", encoding="utf-8")

    switched_back = repo.checkout("main")
    assert switched_back.branch_name == "main"
    assert switched_back.commit_id == main_commit
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


def test_cli_core_workflow_covers_status_diff_log_restore_and_nested_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"

    init_result = _run_lit(tmp_path, "init", "repo")
    assert init_result.stdout.strip() == f"Initialized empty lit repository in {repo_root / '.lit'}"

    nested = repo_root / "docs" / "guide.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("hello\n", encoding="utf-8")
    tracked = repo_root / "notes.txt"
    tracked.write_text("start\n", encoding="utf-8")

    add_result = _run_lit(repo_root, "add", "docs", "notes.txt")
    assert add_result.stdout.strip() == "staged 2 path(s)"

    commit_result = _run_lit(repo_root, "commit", "-m", "initial snapshot")
    repo = Repository.open(repo_root)
    first_commit = repo.current_commit_id()
    assert first_commit is not None
    assert commit_result.stdout.strip() == f"[main {first_commit[:12]}] initial snapshot"
    assert repo.read_commit(first_commit).metadata.author == "lit"

    nested.write_text("hello again\n", encoding="utf-8")
    tracked.unlink()
    untracked = repo_root / "scratch.txt"
    untracked.write_text("extra\n", encoding="utf-8")

    status_result = _run_lit(repo_root, "status")
    assert "Changes not staged for commit:" in status_result.stdout
    assert "  modified: docs/guide.txt" in status_result.stdout
    assert "  deleted: notes.txt" in status_result.stdout
    assert "Untracked files:" in status_result.stdout
    assert "  scratch.txt" in status_result.stdout

    diff_result = _run_lit(repo_root, "diff")
    assert "--- a/docs/guide.txt" in diff_result.stdout
    assert "+++ b/docs/guide.txt" in diff_result.stdout
    assert "-hello" in diff_result.stdout
    assert "+hello again" in diff_result.stdout
    assert "--- a/notes.txt" in diff_result.stdout
    assert "+++ b/notes.txt" in diff_result.stdout

    staged_result = _run_lit(repo_root, "add", "docs", "notes.txt")
    assert staged_result.stdout.strip() == "staged 2 path(s)"

    staged_status = _run_lit(repo_root, "status")
    assert "Changes to be committed:" in staged_status.stdout
    assert "  modified: docs/guide.txt" in staged_status.stdout
    assert "  deleted: notes.txt" in staged_status.stdout
    assert "  scratch.txt" in staged_status.stdout

    second_commit_result = _run_lit(repo_root, "commit", "-m", "update tracked files")
    repo = Repository.open(repo_root)
    second_commit = repo.current_commit_id()
    assert second_commit is not None and second_commit != first_commit
    assert second_commit_result.stdout.strip() == f"[main {second_commit[:12]}] update tracked files"

    log_result = _run_lit(repo_root, "log")
    log_lines = [line for line in log_result.stdout.splitlines() if line]
    assert log_lines[:4] == [
        f"commit {second_commit}",
        "    update tracked files",
        f"commit {first_commit}",
        "    initial snapshot",
    ]

    nested.write_text("broken\n", encoding="utf-8")
    restore_result = _run_lit(repo_root, "restore", "--source", "HEAD", "docs")
    assert restore_result.stdout.strip() == "restored 1 path(s) from HEAD"
    assert nested.read_text(encoding="utf-8") == "hello again\n"


def test_cli_branch_checkout_and_merge_workflows(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _run_lit(tmp_path, "init", "repo")

    story = repo_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt")
    _run_lit(repo_root, "commit", "-m", "base")

    base_repo = Repository.open(repo_root)
    base_commit = base_repo.current_commit_id()
    assert base_commit is not None

    branch_create = _run_lit(repo_root, "branch", "feature")
    assert branch_create.stdout.strip() == f"feature -> {base_commit[:12]}"

    branch_list = _run_lit(repo_root, "branch")
    assert branch_list.stdout.splitlines() == [f"  feature {base_commit[:12]}", f"* main {base_commit[:12]}"]

    checkout_feature = _run_lit(repo_root, "checkout", "feature")
    assert checkout_feature.stdout.strip() == "switched to branch feature"

    story.write_text("feature branch\n", encoding="utf-8")
    feature_only = repo_root / "feature.txt"
    feature_only.write_text("feature side\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt", "feature.txt")
    _run_lit(repo_root, "commit", "-m", "feature work")

    feature_repo = Repository.open(repo_root)
    feature_commit = feature_repo.current_commit_id()
    assert feature_commit is not None and feature_commit != base_commit

    detached = _run_lit(repo_root, "checkout", base_commit)
    assert detached.stdout.strip() == f"detached HEAD at {base_commit[:12]}"
    assert story.read_text(encoding="utf-8") == "base\n"
    assert not feature_only.exists()

    back_to_main = _run_lit(repo_root, "checkout", "main")
    assert back_to_main.stdout.strip() == "switched to branch main"
    assert story.read_text(encoding="utf-8") == "base\n"

    main_only = repo_root / "main.txt"
    main_only.write_text("main side\n", encoding="utf-8")
    _run_lit(repo_root, "add", "main.txt")
    _run_lit(repo_root, "commit", "-m", "main work")

    merge_result = _run_lit(repo_root, "merge", "feature")
    assert "Merge commit created:" in merge_result.stdout
    assert story.read_text(encoding="utf-8") == "feature branch\n"
    assert feature_only.read_text(encoding="utf-8") == "feature side\n"
    assert main_only.read_text(encoding="utf-8") == "main side\n"

    merged_repo = Repository.open(repo_root)
    merge_commit = merged_repo.current_commit_id()
    assert merge_commit is not None
    assert merged_repo.read_commit(merge_commit).parents[1] == feature_commit


def test_cli_rebase_replays_branch_commits(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _run_lit(tmp_path, "init", "repo")

    shared = repo_root / "shared.txt"
    shared.write_text("base\n", encoding="utf-8")
    _run_lit(repo_root, "add", "shared.txt")
    _run_lit(repo_root, "commit", "-m", "base")

    repo = Repository.open(repo_root)
    base_commit = repo.current_commit_id()
    assert base_commit is not None

    _run_lit(repo_root, "branch", "feature")

    main_file = repo_root / "main.txt"
    main_file.write_text("main\n", encoding="utf-8")
    _run_lit(repo_root, "add", "main.txt")
    _run_lit(repo_root, "commit", "-m", "main work")

    repo = Repository.open(repo_root)
    main_commit = repo.current_commit_id()
    assert main_commit is not None and main_commit != base_commit

    _run_lit(repo_root, "checkout", "feature")
    feature_file = repo_root / "feature.txt"
    feature_file.write_text("feature\n", encoding="utf-8")
    _run_lit(repo_root, "add", "feature.txt")
    _run_lit(repo_root, "commit", "-m", "feature work")

    feature_repo = Repository.open(repo_root)
    original_feature_commit = feature_repo.current_commit_id()
    assert original_feature_commit is not None

    rebase_result = _run_lit(repo_root, "rebase", "main")
    assert "Rebased onto main at" in rebase_result.stdout

    rebased_repo = Repository.open(repo_root)
    rebased_commit = rebased_repo.current_commit_id()
    assert rebased_commit is not None and rebased_commit != original_feature_commit
    assert rebased_repo.read_commit(rebased_commit).parents == (main_commit,)
    assert main_file.read_text(encoding="utf-8") == "main\n"
    assert feature_file.read_text(encoding="utf-8") == "feature\n"


def test_cli_merge_conflict_reports_state_and_supports_abort(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _run_lit(tmp_path, "init", "repo")

    story = repo_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt")
    _run_lit(repo_root, "commit", "-m", "base")
    _run_lit(repo_root, "branch", "feature")

    story.write_text("main change\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt")
    _run_lit(repo_root, "commit", "-m", "main change")

    _run_lit(repo_root, "checkout", "feature")
    story.write_text("feature change\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt")
    _run_lit(repo_root, "commit", "-m", "feature change")
    _run_lit(repo_root, "checkout", "main")

    merge_result = _run_lit(repo_root, "merge", "feature", expected_returncode=1)
    assert "Merge stopped with conflicts." in merge_result.stdout
    assert "conflicts:" in merge_result.stdout
    assert "  story.txt" in merge_result.stdout
    conflict_text = story.read_text(encoding="utf-8")
    assert "<<<<<<< current" in conflict_text
    assert "main change" in conflict_text
    assert "feature change" in conflict_text

    merge_state = _run_lit(repo_root, "merge")
    assert "merge in progress:" in merge_state.stdout
    assert "conflicts:" in merge_state.stdout

    abort_result = _run_lit(repo_root, "merge", "--abort")
    assert abort_result.stdout.strip() == "Merge state cleared."
    assert story.read_text(encoding="utf-8") == "main change\n"


def _run_lit(
    cwd: Path,
    *args: str,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "lit", *args],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    return result


def test_readme_and_website_cover_verified_local_workflows() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    website = (ROOT / "website" / "index.html").read_text(encoding="utf-8").lower()
    styles = (ROOT / "website" / "styles.css").read_text(encoding="utf-8")

    for content in (readme, website):
        assert "local-only" in content
        assert "offline" in content
        assert "python -m pip install -e ." in content
        assert "quick start" in content
        assert "lit init" in content
        assert "lit add" in content
        assert "lit commit -m" in content
        assert "lit branch" in content
        assert "lit merge" in content
        assert "lit rebase" in content
        assert "git" in content
        assert "limitations" in content
        assert "non-goals" in content
        assert "push" in content
        assert "pull" in content

    assert "<!doctype html>" in website
    assert "website/index.html" in readme
    assert ":root" in styles


def _commit_all(repo: Repository, message: str) -> str:
    repo.stage(["story.txt"])
    return repo.commit(message)


def _commit_path(repo: Repository, path: str, message: str = "commit") -> str:
    repo.stage([path])
    return repo.commit(message)
