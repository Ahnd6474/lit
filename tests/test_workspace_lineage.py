from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.cli import main
from lit.commands import add, commit
from lit.domain import ProvenanceRecord
from lit.lineage import LineageService
from lit.repository import Repository


def test_workspace_management_lifecycle_supports_multiple_stable_workspaces(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    workspace_one_root = tmp_path / "ws-one"
    workspace_two_root = tmp_path / "ws-two"

    repo = Repository.create(repo_root)
    _commit_file(
        repo,
        "src/app.py",
        "print('base')\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )

    service = LineageService.open(repo_root)
    service.create_lineage("feature", owned_paths=("src",))

    workspace_one = service.create_workspace("feature", workspace_one_root, workspace_id="ws-one")
    workspace_two = service.create_workspace("feature", workspace_two_root, workspace_id="ws-two")
    inspections = {item.workspace.workspace_id: item for item in service.inspect_workspaces()}

    assert workspace_one.workspace_id == "ws-one"
    assert workspace_two.workspace_id == "ws-two"
    assert workspace_one.materialized_revision_id == repo.current_commit_id()
    assert workspace_one.materialized_at is not None
    assert workspace_one.attached_at is not None
    assert (workspace_one_root / "src" / "app.py").read_text(encoding="utf-8") == "print('base')\n"
    assert (workspace_two_root / "src" / "app.py").read_text(encoding="utf-8") == "print('base')\n"
    assert inspections["ws-one"].exists_on_disk is True
    assert inspections["ws-one"].missing_on_disk is False
    assert inspections["ws-two"].workspace.lineage_id == "feature"

    service.create_lineage("feature-fix", forked_from="feature")
    attached = service.attach_workspace("feature-fix", "ws-one")

    assert attached.workspace_id == "ws-one"
    assert attached.lineage_id == "feature-fix"
    assert attached.materialized_at == workspace_one.materialized_at
    assert attached.attached_at is not None

    shutil.rmtree(workspace_one_root)
    gc_result = service.gc_workspaces()

    assert gc_result.scanned_count == 2
    assert gc_result.removed_workspace_ids == ("ws-one",)
    assert [item.workspace.workspace_id for item in gc_result.removed] == ["ws-one"]
    assert [item.workspace.workspace_id for item in gc_result.retained] == ["ws-two"]
    assert [workspace.workspace_id for workspace in service.list_workspaces()] == ["ws-two"]


def test_lineage_workspace_cli_emits_json_for_materialize_list_attach_and_gc(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    workspace_root = tmp_path / "ws-json"
    Repository.create(repo_root)
    service = LineageService.open(repo_root)
    service.create_lineage("feature", owned_paths=("src",))
    service.create_lineage("feature-fix", forked_from="feature")

    monkeypatch.chdir(repo_root)

    materialize_code, materialize_payload = _run_cli_json(
        [
            "lineage",
            "create-workspace",
            "feature",
            str(workspace_root),
            "--workspace-id",
            "ws-json",
            "--json",
        ]
    )
    assert materialize_code == 0
    assert materialize_payload["workspace_id"] == "ws-json"
    assert materialize_payload["lineage_id"] == "feature"

    list_code, list_payload = _run_cli_json(["lineage", "workspace", "list", "--json"])
    assert list_code == 0
    assert list_payload["workspaces"][0]["workspace"]["workspace_id"] == "ws-json"
    assert list_payload["workspaces"][0]["exists_on_disk"] is True

    attach_code, attach_payload = _run_cli_json(
        ["lineage", "workspace", "attach", "feature-fix", "ws-json", "--json"]
    )
    assert attach_code == 0
    assert attach_payload["workspace_id"] == "ws-json"
    assert attach_payload["lineage_id"] == "feature-fix"

    shutil.rmtree(workspace_root)
    gc_code, gc_payload = _run_cli_json(["lineage", "workspace", "gc", "--json"])
    assert gc_code == 0
    assert gc_payload["scanned_count"] == 1
    assert gc_payload["removed_workspace_ids"] == ["ws-json"]


def test_add_rejects_mixed_owned_paths_before_staging(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    Repository.create(repo_root)
    service = LineageService.open(repo_root)
    service.create_lineage("feature", owned_paths=("src",))
    service.switch_lineage("feature")

    (repo_root / "docs.txt").write_text("outside", encoding="utf-8")
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("inside", encoding="utf-8")

    monkeypatch.chdir(repo_root)
    exit_code, output = _capture_stdout(
        add.run,
        argparse.Namespace(paths=["src/app.py", "docs.txt"]),
    )

    assert exit_code == 1
    assert "error: path docs.txt is not within owned paths for lineage feature" in output
    assert Repository.open(repo_root).read_index().entries == ()


def test_commit_rejects_staged_owned_path_violation_before_commit(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    service = LineageService.open(repo_root)
    service.create_lineage("feature", owned_paths=("src",))
    service.switch_lineage("feature")

    (repo_root / "docs.txt").write_text("outside", encoding="utf-8")
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("inside", encoding="utf-8")
    repo = Repository.open(repo_root)
    repo.stage(["src/app.py", "docs.txt"])

    monkeypatch.chdir(repo_root)
    exit_code, output = _capture_stdout(
        commit.run,
        argparse.Namespace(message="feat: blocked"),
    )

    assert exit_code == 1
    assert "error: path docs.txt is not within owned paths for lineage feature" in output
    assert Repository.open(repo_root).current_commit_id() is None
    assert [entry.path for entry in Repository.open(repo_root).read_index().entries] == [
        "docs.txt",
        "src/app.py",
    ]


def test_add_and_commit_allow_owned_paths_when_workspace_metadata_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    workspace_root = tmp_path / "ws-allowed"
    Repository.create(repo_root)
    service = LineageService.open(repo_root)
    service.create_lineage("feature", owned_paths=("src",))
    service.create_workspace("feature", workspace_root, workspace_id="ws-allowed")
    service.switch_lineage("feature")

    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.chdir(repo_root)
    add_exit_code, add_output = _capture_stdout(
        add.run,
        argparse.Namespace(paths=["src/app.py"]),
    )
    commit_exit_code, commit_output = _capture_stdout(
        commit.run,
        argparse.Namespace(message="feat: allowed"),
    )

    assert add_exit_code == 0
    assert "staged 1 path(s)" in add_output
    assert commit_exit_code == 0
    assert "[feature" in commit_output
    assert Repository.open(repo_root).current_commit_id() is not None


def _capture_stdout(func, args: argparse.Namespace) -> tuple[int, str]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        exit_code = func(args)
    return exit_code, stream.getvalue()


def _run_cli_json(argv: list[str]) -> tuple[int, object]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        exit_code = main(argv)
    return exit_code, json.loads(stream.getvalue())


def _commit_file(
    repository: Repository,
    relative_path: str,
    content: str,
    message: str,
    provenance: ProvenanceRecord,
) -> str:
    target = repository.root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    repository.stage([relative_path])
    return repository.commit(message, provenance=provenance)
