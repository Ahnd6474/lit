from __future__ import annotations

import time
from pathlib import Path

from lit.artifact_store import ArtifactStore
from lit.artifacts import ArtifactLink
from lit.doctor import run_doctor
from lit.export_git import build_git_export_plan
from lit.repository import Repository


def test_release_surface_export_and_doctor_smoke_complete_quickly(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    store = ArtifactStore(tmp_path / "artifact-home")

    for index in range(30):
        target = tmp_path / f"file-{index % 5}.txt"
        target.write_text(f"{index}\n", encoding="utf-8")
        repo.stage([target.name])
        commit_id = repo.commit(f"commit {index}")
        if index % 5 == 0:
            checkpoint = repo.create_checkpoint(name=f"cp-{index}", revision_id=commit_id)
            store.store_bytes(
                f"artifact-{index}".encode("utf-8"),
                repository_root=tmp_path,
                kind="verification-output",
                relative_path=f"artifacts/{index}.txt",
                links=(ArtifactLink.checkpoint(checkpoint.checkpoint_id or ""),),
            )

    started = time.perf_counter()
    plan = build_git_export_plan(tmp_path)
    doctor = run_doctor(tmp_path)
    usage = store.usage_report([tmp_path])
    elapsed = time.perf_counter() - started

    assert len(plan.commits) == 30
    assert doctor.stats.checkpoints == 6
    assert usage.total_objects == 6
    assert elapsed < 10
