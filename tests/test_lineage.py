from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lit.domain import ProvenanceRecord
from lit.lineage import (
    LineageService,
    LineageStatus,
    PathReservationError,
    PromotionConflictError,
    PromotionConflictType,
)
from lit.repository import Repository


def test_lineage_service_creates_switches_and_discards_lineages(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    story = tmp_path / "story.txt"
    base_commit = _commit_file(
        repo,
        "story.txt",
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    checkpoint = repo.create_checkpoint(
        revision_id=base_commit,
        name="base-safe",
        safe=True,
        provenance=ProvenanceRecord(actor_role="reviewer", actor_id="human", lineage_id="main"),
    )

    service = LineageService.open(tmp_path)
    feature = service.create_lineage(
        "feature",
        owned_paths=("feature.txt",),
        title="Feature",
        description="parallel work",
    )
    listed = {lineage.lineage_id: lineage for lineage in service.list_lineages()}

    assert feature.base_checkpoint_id == checkpoint.checkpoint_id
    assert feature.head_revision == base_commit
    assert feature.status is LineageStatus.ACTIVE
    assert feature.owned_paths == ("feature.txt",)
    assert "main" in listed
    assert listed["feature"].description == "parallel work"

    switched = service.switch_lineage("feature")
    reopened = Repository.open(tmp_path)

    assert reopened.current_branch_name() == "feature"
    assert switched.last_switched_at is not None

    service.switch_lineage("main")
    discarded = service.discard_lineage("feature")

    assert discarded.status is LineageStatus.DISCARDED
    assert discarded.discarded_at is not None
    assert not reopened.layout.branch_path("feature").exists()
    with pytest.raises(ValueError, match="cannot switch to discarded lineage"):
        service.switch_lineage("feature")
    assert story.read_text(encoding="utf-8") == "base\n"


def test_lineage_service_rejects_overlapping_owned_paths_without_explicit_rule(tmp_path: Path) -> None:
    Repository.create(tmp_path)
    service = LineageService.open(tmp_path)

    alpha = service.create_lineage("alpha", owned_paths=("src",))
    assert alpha.owned_paths == ("src",)

    with pytest.raises(PathReservationError) as error:
        service.create_lineage("beta", owned_paths=("src/app.py",))

    assert error.value.conflicts[0].existing_lineage_id == "alpha"
    assert error.value.conflicts[0].requested_path == "src/app.py"

    beta = service.create_lineage(
        "beta",
        owned_paths=("src/app.py",),
        allow_owned_path_overlap_with=("alpha",),
    )
    assert beta.allow_owned_path_overlap_with == ("alpha",)


def test_lineage_service_previews_conflicts_before_promotion(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    base_commit = _commit_file(
        repo,
        "story.txt",
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    repo.create_checkpoint(
        revision_id=base_commit,
        name="base-safe",
        safe=True,
        provenance=ProvenanceRecord(actor_role="reviewer", actor_id="human", lineage_id="main"),
    )

    service = LineageService.open(tmp_path)
    service.create_lineage("feature", owned_paths=("story.txt",))
    service.switch_lineage("feature")
    feature_repo = Repository.open(tmp_path)
    feature_commit = _commit_file(
        feature_repo,
        "story.txt",
        "feature\n",
        "feature update",
        ProvenanceRecord(actor_role="executor", actor_id="agent-feature", lineage_id="feature"),
    )
    service.switch_lineage("main")
    main_repo = Repository.open(tmp_path)
    _commit_file(
        main_repo,
        "story.txt",
        "main\n",
        "main update",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )

    preview = service.preview_promotion_conflicts("feature", "main")

    assert preview.base_checkpoint_id is not None
    assert preview.baseline_revision == base_commit
    assert preview.source_head_revision == feature_commit
    assert preview.can_promote is False
    assert preview.source_changed_paths == ("story.txt",)
    assert preview.destination_changed_paths == ("story.txt",)
    assert preview.conflicts[0].conflict_type is PromotionConflictType.DESTINATION_CHANGED
    assert preview.conflicts[0].path == "story.txt"

    with pytest.raises(PromotionConflictError) as error:
        service.promote_lineage("feature", destination_lineage_id="main")
    assert error.value.preview.destination_lineage_id == "main"


def test_lineage_service_promotes_without_conflicts_and_preserves_state(tmp_path: Path) -> None:
    repo = Repository.create(tmp_path)
    base_commit = _commit_file(
        repo,
        "story.txt",
        "base\n",
        "base",
        ProvenanceRecord(actor_role="executor", actor_id="agent-main", lineage_id="main"),
    )
    repo.create_checkpoint(
        revision_id=base_commit,
        name="base-safe",
        safe=True,
        provenance=ProvenanceRecord(actor_role="reviewer", actor_id="human", lineage_id="main"),
    )

    service = LineageService.open(tmp_path)
    service.create_lineage("feature", owned_paths=("feature.txt",))
    service.switch_lineage("feature")
    feature_repo = Repository.open(tmp_path)
    feature_commit = _commit_file(
        feature_repo,
        "feature.txt",
        "feature\n",
        "feature update",
        ProvenanceRecord(actor_role="executor", actor_id="agent-feature", lineage_id="feature"),
    )

    preview = service.preview_promotion_conflicts("feature", "main")
    result = service.promote_lineage("feature", destination_lineage_id="main")
    promoted_source = service.get_lineage("feature")
    promoted_destination = service.get_lineage("main")

    assert preview.can_promote is True
    assert result.destination.head_revision == feature_commit
    assert promoted_source.status is LineageStatus.PROMOTED
    assert promoted_source.promoted_to == "main"
    assert promoted_source.promoted_at is not None
    assert promoted_destination.promoted_from == "feature"
    assert promoted_destination.head_revision == feature_commit
    assert "feature.txt" in promoted_destination.owned_paths
    assert Repository.open(tmp_path).read_branch("main") == feature_commit


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
