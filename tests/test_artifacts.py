from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.artifact_store import ArtifactStore, default_artifact_home
from lit.artifacts import ArtifactLink, ArtifactManifest
from lit.domain import ArtifactRecord
from lit.repository import Repository
from lit.storage import read_json


def test_artifact_store_uses_configurable_global_home_and_deduplicates_payloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configured_home = tmp_path / "configured-home"
    monkeypatch.setenv("LIT_ARTIFACT_HOME", str(configured_home))

    assert default_artifact_home() == configured_home.resolve()

    repo_root = tmp_path / "repo"
    Repository.create(repo_root)
    store = ArtifactStore()
    revision_link = ArtifactLink.revision("rev-1")
    checkpoint_link = ArtifactLink.checkpoint("cp-1")
    lineage_link = ArtifactLink.lineage("main")

    first = store.store_bytes(
        b"hello artifact store\n",
        repository_root=repo_root,
        kind="verification-output",
        relative_path="logs/verify.txt",
        content_type="text/plain",
        links=(revision_link, checkpoint_link, lineage_link),
        pinned=True,
    )
    second = store.store_bytes(
        b"hello artifact store\n",
        repository_root=repo_root,
        kind="verification-output",
        relative_path="logs/retry.txt",
        content_type="text/plain",
        links=(ArtifactLink.revision("rev-2"),),
    )

    assert first.digest == second.digest
    assert first.content_address == second.content_address
    assert store.read_bytes(first.content_address or "") == b"hello artifact store\n"

    object_path = store.object_path(first.content_address or "")
    assert object_path.is_file()
    assert len(store.iter_objects()) == 1

    manifest_path = repo_root / ".lit" / "v1" / "artifacts" / (first.artifact_id or "") / "artifact.json"
    persisted = ArtifactManifest.from_dict(read_json(manifest_path, default=None))
    assert persisted.pinned is True
    assert [link.owner_kind for link in persisted.all_links] == [
        "revision",
        "checkpoint",
        "lineage",
    ]
    assert ArtifactRecord.from_dict(read_json(manifest_path, default=None)).digest == first.digest


def test_artifact_store_supports_resumable_writes_and_link_updates(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    Repository.create(repo_root)
    store = ArtifactStore(tmp_path / "global-home")

    session = store.begin_write(
        kind="checkpoint-bundle",
        relative_path="bundles/checkpoint.tar",
        content_type="application/x-tar",
        links=(ArtifactLink.revision("rev-10"),),
        expected_size=11,
    )
    assert session.append(b"hello ") == 6

    resumed = store.open_session(session.session_id)
    assert resumed.bytes_written == 6
    assert resumed.append(b"world") == 11

    manifest = resumed.finalize(repository_root=repo_root)
    updated = store.link_artifact(
        repo_root,
        manifest.artifact_id or "",
        ArtifactLink.checkpoint("cp-10"),
        ArtifactLink.lineage("feature-a"),
    )

    assert store.read_bytes(updated.content_address or "") == b"hello world"
    assert not store.session_state_path(session.session_id).exists()
    assert not store.session_data_path(session.session_id).exists()
    assert {(link.owner_kind, link.owner_id) for link in updated.all_links} == {
        ("revision", "rev-10"),
        ("checkpoint", "cp-10"),
        ("lineage", "feature-a"),
    }


def test_artifact_store_exposes_explicit_commit_checkpoint_and_lineage_link_helpers(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    Repository.create(repo_root)
    store = ArtifactStore(tmp_path / "global-home")

    manifest = store.store_bytes(
        b"bundle-bytes",
        repository_root=repo_root,
        kind="checkpoint-bundle",
        relative_path="bundles/state.tar",
    )

    assert ArtifactLink.commit("rev-20").owner_kind == "revision"

    linked = store.link_commit_artifact(
        repo_root,
        manifest.artifact_id or "",
        "rev-20",
        relationship="produced",
        note="captured after commit",
    )
    linked = store.link_checkpoint_artifact(
        repo_root,
        linked.artifact_id or "",
        "cp-20",
        relationship="checkpoint-input",
    )
    linked = store.link_lineage_artifact(
        repo_root,
        linked.artifact_id or "",
        "feature-a",
    )

    assert linked.primary_link is not None
    assert linked.primary_link.owner_kind == "revision"
    assert linked.primary_link.owner_id == "rev-20"
    assert linked.is_linked_to("checkpoint", "cp-20") is True
    assert linked.is_linked_to("lineage", "feature-a") is True

    assert [item.artifact_id for item in store.list_commit_manifests(repo_root, "rev-20")] == [
        manifest.artifact_id
    ]
    assert [
        item.artifact_id for item in store.list_checkpoint_manifests(repo_root, "cp-20")
    ] == [manifest.artifact_id]
    assert [item.artifact_id for item in store.list_lineage_manifests(repo_root, "feature-a")] == [
        manifest.artifact_id
    ]
    assert [
        item.artifact_id
        for item in store.list_linked_manifests(
            repo_root,
            owner_kind="revision",
            owner_id="rev-20",
        )
    ] == [manifest.artifact_id]


def test_artifact_store_reports_usage_and_collects_unlinked_objects(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    Repository.create(repo_root)
    store = ArtifactStore(tmp_path / "global-home")
    store.set_quota(20)

    pinned = store.store_bytes(
        b"keep-me",
        repository_root=repo_root,
        kind="generic",
        relative_path="artifacts/keep.bin",
        links=(ArtifactLink.revision("rev-keep"),),
        pinned=True,
    )
    linked = store.store_bytes(
        b"linked",
        repository_root=repo_root,
        kind="generic",
        relative_path="artifacts/linked.bin",
        links=(ArtifactLink.lineage("main"),),
    )
    orphan = store.store_bytes(
        b"orphaned-data",
        kind="generic",
        relative_path="tmp/orphan.bin",
    )

    report = store.usage_report([repo_root])
    assert report.total_objects == 3
    assert report.total_bytes == len(b"keep-me") + len(b"linked") + len(b"orphaned-data")
    assert report.pinned_objects == 1
    assert report.pinned_bytes == len(b"keep-me")
    assert report.linked_objects == 2
    assert report.linked_bytes == len(b"keep-me") + len(b"linked")
    assert report.reclaimable_objects == 1
    assert report.reclaimable_bytes == len(b"orphaned-data")
    assert report.quota_bytes == 20
    assert report.over_quota is True

    inputs = store.artifact_gc_inputs([repo_root])
    assert set(inputs.pinned_digests) == {pinned.digest}
    assert set(inputs.linked_digests) == {pinned.digest, linked.digest}
    assert set(inputs.candidate_digests) == {orphan.digest}

    dry_run = store.collect_garbage([repo_root], dry_run=True)
    assert dry_run.dry_run is True
    assert dry_run.removed_digests == (orphan.digest,)
    assert store.has_object(orphan.content_address or "")

    collected = store.collect_garbage([repo_root])
    assert collected.removed_digests == (orphan.digest,)
    assert not store.has_object(orphan.content_address or "")
    assert store.has_object(pinned.content_address or "")
    assert store.has_object(linked.content_address or "")
