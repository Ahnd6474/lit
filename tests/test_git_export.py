from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.repository import Repository
from lit.storage import write_json


def test_export_cli_preserves_legacy_revision_metadata_and_allows_checkpoint_creation(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

    _run_lit(tmp_path, "init", "repo", env=env)
    story = repo_root / "story.txt"
    story.write_text("legacy\n", encoding="utf-8")
    _run_lit(repo_root, "add", "story.txt", env=env)
    _run_lit(repo_root, "commit", "-m", "legacy commit", env=env)

    repo = Repository.open(repo_root)
    revision = repo.current_revision()
    assert revision is not None
    write_json(
        repo.layout.revision_path(revision.revision_id or ""),
        {
            "tree": revision.tree,
            "parents": list(revision.parents),
            "message": revision.message,
            "metadata": {
                "author": "legacy-user",
                "committed_at": "2026-03-29T00:00:00Z",
            },
        },
    )

    export_payload = json.loads(_run_lit(repo_root, "export", "--json", env=env).stdout)
    commit = export_payload["commits"][0]

    assert commit["revision_id"] == revision.revision_id
    assert ("Lit-Actor-Role", "legacy") in [tuple(item) for item in commit["trailers"]]
    assert ("Lit-Actor-Id", "legacy-user") in [tuple(item) for item in commit["trailers"]]

    checkpoint_payload = json.loads(
        _run_lit(repo_root, "checkpoint", "create", "--name", "legacy-safe", "--json", env=env).stdout
    )
    assert checkpoint_payload["checkpoint"]["revision_id"] == revision.revision_id


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
