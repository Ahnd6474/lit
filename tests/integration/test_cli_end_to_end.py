from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lit.artifact_store import ArtifactStore
from lit.artifacts import ArtifactLink
from lit.repository import Repository
from lit.storage import read_json, write_json


def test_cli_release_surface_workflow_covers_checkpoint_verify_lineage_artifact_gc_doctor_and_export(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    artifact_home = tmp_path / "artifact-home"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "LIT_ARTIFACT_HOME": str(artifact_home)}

    _run_lit(tmp_path, "init", "repo", env=env)

    story = repo_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt", env=env)
    _run_lit(repo_root, "commit", "-m", "base", env=env)

    repo = Repository.open(repo_root)
    head_revision = repo.current_commit_id()
    assert head_revision is not None

    checkpoint_payload = _json_output(
        _run_lit(
            repo_root,
            "checkpoint",
            "create",
            "--name",
            "safe-base",
            "--json",
            env=env,
        )
    )
    checkpoint_id = checkpoint_payload["checkpoint"]["checkpoint_id"]
    assert checkpoint_payload["checkpoint"]["safe"] is True

    checkpoint_list = _json_output(
        _run_lit(repo_root, "checkpoint", "list", "--json", env=env)
    )
    assert checkpoint_list["latest_safe_checkpoint_id"] == checkpoint_id

    _write_verification_commands(
        repo,
        [
            {
                "name": "smoke",
                "command": [sys.executable, "-c", "print('ok')"],
                "command_identity": "smoke-python",
            }
        ],
    )

    verify_payload = _json_output(
        _run_lit(
            repo_root,
            "verify",
            "run",
            "--definition",
            "smoke",
            "--json",
            env=env,
        )
    )
    assert verify_payload["status"] == "passed"
    assert len(verify_payload["output_artifact_ids"]) == 1

    verify_status = _json_output(
        _run_lit(repo_root, "verify", "status", "--json", env=env)
    )
    assert verify_status["status"] in {"passed", "cached_pass", "stale"}

    lineage_payload = _json_output(
        _run_lit(
            repo_root,
            "lineage",
            "create",
            "feature-a",
            "--owned-path",
            "src/lit",
            "--description",
            "parallel worker lane",
            "--json",
            env=env,
        )
    )
    assert lineage_payload["lineage"]["lineage_id"] == "feature-a"

    switch_payload = _json_output(
        _run_lit(
            repo_root,
            "lineage",
            "switch",
            "feature-a",
            "--json",
            env=env,
        )
    )
    assert switch_payload["lineage_id"] == "feature-a"
    assert Repository.open(repo_root).current_branch_name() == "feature-a"

    _run_lit(repo_root, "lineage", "switch", "main", env=env)
    assert Repository.open(repo_root).current_branch_name() == "main"

    preview_payload = _json_output(
        _run_lit(
            repo_root,
            "lineage",
            "promote",
            "feature-a",
            "--preview",
            "--json",
            env=env,
        )
    )
    assert preview_payload["source_lineage_id"] == "feature-a"

    store = ArtifactStore(artifact_home)
    manifest = store.store_bytes(
        b"artifact-bytes",
        repository_root=repo_root,
        kind="checkpoint-bundle",
        relative_path="bundles/state.tar",
        links=(ArtifactLink.revision(head_revision),),
    )

    artifact_list = _json_output(
        _run_lit(repo_root, "artifact", "list", "--json", env=env)
    )
    assert any(item["artifact_id"] == manifest.artifact_id for item in artifact_list)

    artifact_show = _json_output(
        _run_lit(repo_root, "artifact", "show", manifest.artifact_id or "", "--json", env=env)
    )
    assert artifact_show["kind"] == "checkpoint-bundle"

    artifact_link = _json_output(
        _run_lit(
            repo_root,
            "artifact",
            "link",
            manifest.artifact_id or "",
            "--owner-kind",
            "checkpoint",
            "--owner-id",
            checkpoint_id,
            "--relationship",
            "checkpoint-input",
            "--json",
            env=env,
        )
    )
    assert any(link["owner_kind"] == "checkpoint" for link in artifact_link["links"])

    usage_payload = _json_output(
        _run_lit(repo_root, "artifact", "usage", "--json", env=env)
    )
    assert usage_payload["total_objects"] >= 1

    gc_payload = _json_output(
        _run_lit(repo_root, "gc", "--dry-run", "--json", env=env)
    )
    assert gc_payload["result"]["dry_run"] is True

    doctor_payload = _json_output(
        _run_lit(repo_root, "doctor", "--json", env=env)
    )
    assert doctor_payload["healthy"] is True
    assert doctor_payload["latest_safe_checkpoint_id"] == checkpoint_id

    export_payload = _json_output(
        _run_lit(repo_root, "export", "--json", env=env)
    )
    assert export_payload["current_branch"] == "main"
    assert export_payload["commits"][0]["revision_id"] == head_revision
    assert any(ref["source_kind"] == "checkpoint" for ref in export_payload["refs"])


def _run_lit(
    cwd: Path,
    *args: str,
    env: dict[str, str],
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "lit", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    return result


def _json_output(result: subprocess.CompletedProcess[str]) -> object:
    return json.loads(result.stdout)


def _write_verification_commands(
    repo: Repository,
    commands: list[dict[str, object]],
) -> None:
    config = read_json(repo.layout.config, default={}) or {}
    config["verification_commands"] = commands
    write_json(repo.layout.config, config)
