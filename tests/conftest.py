from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lit.refs import branch_ref
from lit.repository import Repository
from lit.storage import read_json, write_json


@pytest.fixture
def commit_all():
    def _commit_all(repository: Repository, message: str) -> str:
        repository.stage(["."])
        return repository.commit(message)

    return _commit_all


@pytest.fixture
def prepare_merge_conflict(commit_all):
    def _prepare_merge_conflict(repository: Repository, root: Path) -> None:
        story = root / "story.txt"
        story.write_text("base\n", encoding="utf-8")
        base_commit = commit_all(repository, "base")
        repository.create_branch("feature", start_point=base_commit)

        story.write_text("main change\n", encoding="utf-8")
        main_commit = commit_all(repository, "main")

        repository.set_head_ref(branch_ref("feature"))
        repository.apply_commit(base_commit, baseline_commit=main_commit)
        story.write_text("feature change\n", encoding="utf-8")
        feature_commit = commit_all(repository, "feature")

        repository.set_head_ref(branch_ref("main"))
        repository.apply_commit(main_commit, baseline_commit=feature_commit)

    return _prepare_merge_conflict


@pytest.fixture
def prepare_rebase_conflict(commit_all):
    def _prepare_rebase_conflict(repository: Repository, root: Path) -> None:
        story = root / "story.txt"
        story.write_text("base\n", encoding="utf-8")
        base_commit = commit_all(repository, "base")
        repository.create_branch("feature", start_point=base_commit)

        story.write_text("main change\n", encoding="utf-8")
        main_commit = commit_all(repository, "main")

        repository.set_head_ref(branch_ref("feature"))
        repository.apply_commit(base_commit, baseline_commit=main_commit)
        story.write_text("feature change\n", encoding="utf-8")
        commit_all(repository, "feature")

    return _prepare_rebase_conflict


@pytest.fixture
def write_smoke_verification_command():
    def _write_smoke_verification_command(
        repository: Repository,
        *,
        command_identity: str,
    ) -> None:
        config = read_json(repository.layout.config, default={}) or {}
        config["verification_commands"] = [
            {
                "name": "smoke",
                "command": [sys.executable, "-c", "print('ok')"],
                "command_identity": command_identity,
            }
        ]
        write_json(repository.layout.config, config)

    return _write_smoke_verification_command
