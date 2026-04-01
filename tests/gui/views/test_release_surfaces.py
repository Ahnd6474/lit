from __future__ import annotations

from pathlib import Path

from lit.artifact_store import ArtifactStore
from lit.artifacts import ArtifactLink
from lit.repository import Repository


def test_release_surface_views_render_checkpoints_verification_lineages_and_health(
    gui_modules,
    tmp_path: Path,
    write_smoke_verification_command,
) -> None:
    app_module = gui_modules.app
    contracts = gui_modules.contracts
    persistence_module = gui_modules.persistence
    session_module = gui_modules.session

    repo_root = tmp_path / "repo"
    repo = Repository.create(repo_root)
    story = repo_root / "story.txt"
    story.write_text("base\n", encoding="utf-8")
    repo.stage(["story.txt"])
    head_revision = repo.commit("seed")
    checkpoint = repo.create_checkpoint(revision_id=head_revision, name="safe-seed")
    write_smoke_verification_command(repo, command_identity="gui-smoke")
    repo.run_verification(
        owner_kind="revision",
        owner_id=head_revision,
        definition_name="smoke",
        state_fingerprint=repo.get_revision(head_revision).tree,
        environment_fingerprint="gui-test",
    )
    repo.create_lineage(
        "feature-a",
        owned_paths=("src/lit",),
        description="parallel worker lane",
    )
    ArtifactStore(tmp_path / "artifact-home").store_bytes(
        b"bundle",
        repository_root=repo_root,
        kind="checkpoint-bundle",
        relative_path="bundles/state.tar",
        links=(ArtifactLink.checkpoint(checkpoint.checkpoint_id or ""),),
    )

    store = persistence_module.RecentRepositoriesStore(tmp_path / "appdata" / "recent.json")
    session = session_module.LitRepositorySession(repo_root, recent_store=store)
    session.open_repository(repo_root)
    window = app_module.build_window(session=session)

    home_view = window.view(contracts.NavigationTarget.HOME)
    assert "Latest safe checkpoint" in home_view.call_to_action_label.text()
    assert any(label.text().startswith("Repository health:") for label in home_view._health_labels)
    assert any(label.text().startswith("Objects:") for label in home_view._artifact_labels)

    window.show_view(contracts.NavigationTarget.HISTORY)
    history_view = window.view(contracts.NavigationTarget.HISTORY)
    assert history_view.checkpoint_group.title() == "Checkpoint Timeline (1)"
    assert any(button.isVisible() and "safe-seed" in button.text() for button in history_view.checkpoint_buttons)
    assert "Verification status:" in history_view.diff_panel.metadata_label.text()
    assert "Actor:" in history_view.diff_panel.metadata_label.text()

    window.show_view(contracts.NavigationTarget.BRANCHES)
    branches_view = window.view(contracts.NavigationTarget.BRANCHES)
    _click_button(branches_view.branch_buttons, "feature-a")

    assert any(button.isVisible() and "feature-a" in button.text() for button in branches_view.lineage_buttons)
    assert branches_view.promotion_preview_label.text().startswith("Promotion preview:")
    assert "Selected lineage: feature-a" in window.detail_slots.slot_body(contracts.DetailSlotId.METADATA)


def _click_button(buttons, text_fragment: str) -> None:
    for button in buttons:
        if button.isVisible() and text_fragment in button.text():
            button.clicked.emit()
            return
    raise AssertionError(f"button not found: {text_fragment}")
