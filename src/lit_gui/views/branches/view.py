from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import BranchSummary, BranchesViewState, SummaryItem
from lit_gui.views.operations import RestoreActionPanel, RevisionActionPanel


class BranchesView(QtWidgets.QWidget):
    def __init__(
        self,
        state: BranchesViewState,
        *,
        on_select_branch,
        on_create_branch_requested,
        on_checkout_requested,
        on_restore_paths_requested,
        on_merge_requested,
        on_abort_merge_requested,
        on_rebase_requested,
        on_abort_rebase_requested,
        on_refresh_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self._on_select_branch = on_select_branch
        self._on_create_branch_requested = on_create_branch_requested
        self._on_checkout_requested = on_checkout_requested
        self._on_restore_paths_requested = on_restore_paths_requested
        self._on_merge_requested = on_merge_requested
        self._on_abort_merge_requested = on_abort_merge_requested
        self._on_rebase_requested = on_rebase_requested
        self._on_abort_rebase_requested = on_abort_rebase_requested
        self._on_refresh_requested = on_refresh_requested
        self._summary_labels: list[QtWidgets.QLabel] = []
        self._branch_buttons: list[QtWidgets.QPushButton] = []
        self._lineage_buttons: list[QtWidgets.QPushButton] = []
        self._conflict_buttons: list[QtWidgets.QPushButton] = []

        self.title_label = QtWidgets.QLabel()
        self.subtitle_label = QtWidgets.QLabel()
        self.root_label = QtWidgets.QLabel()
        self.attention_label = QtWidgets.QLabel()
        self.refresh_button = QtWidgets.QPushButton("Refresh Branches")

        self.branch_list_group = QtWidgets.QGroupBox()
        self.branch_list_group.setTitle("Branch List")
        self._branch_list_layout = QtWidgets.QVBoxLayout(self.branch_list_group)
        self._branch_empty_label = QtWidgets.QLabel("No branches loaded yet.")
        self._branch_empty_label.setWordWrap(True)
        self._branch_list_layout.addWidget(self._branch_empty_label)

        self.manual_state_group = QtWidgets.QGroupBox()
        self.manual_state_group.setTitle("Repository State")
        self._manual_state_layout = QtWidgets.QVBoxLayout(self.manual_state_group)
        self.manual_state_label = QtWidgets.QLabel()
        self.manual_state_label.setWordWrap(True)
        self._manual_state_layout.addWidget(self.manual_state_label)
        self.promotion_preview_label = QtWidgets.QLabel()
        self.promotion_preview_label.setWordWrap(True)
        self._manual_state_layout.addWidget(self.promotion_preview_label)
        self._conflict_empty_label = QtWidgets.QLabel("No conflicted paths recorded.")
        self._conflict_empty_label.setWordWrap(True)
        self._manual_state_layout.addWidget(self._conflict_empty_label)

        self.lineage_group = QtWidgets.QGroupBox()
        self.lineage_group.setTitle("Lineages")
        self._lineage_layout = QtWidgets.QVBoxLayout(self.lineage_group)
        self._lineage_empty_label = QtWidgets.QLabel("No lineage records loaded.")
        self._lineage_empty_label.setWordWrap(True)
        self._lineage_layout.addWidget(self._lineage_empty_label)

        self.create_group = QtWidgets.QGroupBox()
        self.create_group.setTitle("Create Branch")
        create_layout = QtWidgets.QVBoxLayout(self.create_group)
        self.create_hint_label = QtWidgets.QLabel()
        self.create_hint_label.setWordWrap(True)
        self.create_name_label = QtWidgets.QLabel("Branch name")
        self.create_name_input = QtWidgets.QLineEdit()
        self.create_start_label = QtWidgets.QLabel("Start point")
        self.create_start_input = QtWidgets.QLineEdit("HEAD")
        self.create_button = QtWidgets.QPushButton("Create Branch")
        create_layout.addWidget(self.create_hint_label)
        create_layout.addWidget(self.create_name_label)
        create_layout.addWidget(self.create_name_input)
        create_layout.addWidget(self.create_start_label)
        create_layout.addWidget(self.create_start_input)
        create_row = QtWidgets.QHBoxLayout()
        create_row.addWidget(self.create_button)
        create_row.addStretch(1)
        create_layout.addLayout(create_row)

        self.checkout_selected_button = QtWidgets.QPushButton("Checkout Selected Branch")
        self.checkout_panel = RevisionActionPanel(
            title="Checkout",
            description="Checkout another branch or commit id. This rewrites the working tree.",
            primary_button_text="Checkout Revision",
            on_primary_requested=self._on_checkout_requested,
        )
        self.restore_panel = RestoreActionPanel(
            description="Restore a path from HEAD or another revision to discard working tree changes.",
            on_restore_requested=self._on_restore_paths_requested,
        )
        self.merge_panel = RevisionActionPanel(
            title="Merge",
            description="Merge another local branch or commit into the current branch.",
            primary_button_text="Merge Revision",
            on_primary_requested=self._on_merge_requested,
            secondary_button_text="Abort Merge",
            on_secondary_requested=self._on_abort_merge_requested,
        )
        self.rebase_panel = RevisionActionPanel(
            title="Rebase",
            description="Rebase the current branch onto another local branch or commit.",
            primary_button_text="Rebase Onto",
            on_primary_requested=self._on_rebase_requested,
            secondary_button_text="Abort Rebase",
            on_secondary_requested=self._on_abort_rebase_requested,
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        for label in (
            self.title_label,
            self.subtitle_label,
            self.root_label,
            self.attention_label,
        ):
            label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.root_label)
        layout.addWidget(self.attention_label)

        summary_group = QtWidgets.QGroupBox()
        summary_group.setTitle("Summary")
        self._summary_layout = QtWidgets.QVBoxLayout(summary_group)
        layout.addWidget(summary_group)

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.refresh_button)
        action_row.addWidget(self.checkout_selected_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        content_row = QtWidgets.QHBoxLayout()
        left_column = QtWidgets.QVBoxLayout()
        left_column.addWidget(self.branch_list_group)
        left_column.addWidget(self.lineage_group)
        left_column.addWidget(self.manual_state_group)
        left_column.addStretch(1)
        content_row.addLayout(left_column, 1)

        right_column = QtWidgets.QVBoxLayout()
        right_column.addWidget(self.create_group)
        right_column.addWidget(self.checkout_panel)
        right_column.addWidget(self.restore_panel)
        right_column.addWidget(self.merge_panel)
        right_column.addWidget(self.rebase_panel)
        right_column.addStretch(1)
        content_row.addLayout(right_column, 1)

        layout.addLayout(content_row)
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._on_refresh_requested)
        self.checkout_selected_button.clicked.connect(self._checkout_selected_branch)
        self.create_button.clicked.connect(self._create_branch_requested)
        self.create_name_input.textChanged.connect(lambda *_: self._sync_actions())
        self.checkout_panel.revision_input.textChanged.connect(lambda *_: self._sync_actions())
        self.restore_panel.path_input.textChanged.connect(lambda *_: self._sync_actions())
        self.merge_panel.revision_input.textChanged.connect(lambda *_: self._sync_actions())
        self.rebase_panel.revision_input.textChanged.connect(lambda *_: self._sync_actions())

        self.apply_state(state)

    @property
    def branch_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._branch_buttons)

    @property
    def conflict_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._conflict_buttons)

    @property
    def lineage_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._lineage_buttons)

    def apply_state(self, state: BranchesViewState) -> None:
        self.state = state
        self.title_label.setText(state.title)
        self.subtitle_label.setText(state.subtitle)

        root = state.context.root if state.context is not None else None
        self.root_label.setText(f"Root: {root}" if root is not None else "Root: n/a")

        context_attention = (
            state.context.attention
            if state.context is not None and state.context.attention
            else state.context.status_text if state.context is not None else "No repository loaded."
        )
        self.attention_label.setText(context_attention)
        self.manual_state_label.setText(self._manual_state_text())
        self.promotion_preview_label.setText(self._promotion_preview_text())
        self.create_hint_label.setText(
            "Create a local branch from HEAD or another revision. The start point defaults to HEAD."
        )
        self.checkout_panel.set_description(self._checkout_description())
        self.restore_panel.set_description(self._restore_description())
        self.merge_panel.set_description(self._merge_description())
        self.rebase_panel.set_description(self._rebase_description())

        self._apply_summary_items(state.highlights)
        self._apply_branches(state.branches, state.selected_branch)
        self._apply_lineages(state.lineages, state.selected_branch)
        self._apply_conflicts()

        if state.selected_branch is not None and not self.checkout_panel.revision_input.text().strip():
            self.checkout_panel.revision_input.setText(state.selected_branch)
        if state.restore_suggestion is not None and not self.restore_panel.path_input.text().strip():
            self.restore_panel.path_input.setText(state.restore_suggestion)
        if not self.restore_panel.source_input.text().strip():
            self.restore_panel.source_input.setText("HEAD")
        self._sync_actions()

    def _apply_summary_items(self, items: tuple[SummaryItem, ...]) -> None:
        for index, item in enumerate(items):
            if index >= len(self._summary_labels):
                label = QtWidgets.QLabel()
                label.setWordWrap(True)
                self._summary_labels.append(label)
                self._summary_layout.addWidget(label)
            label = self._summary_labels[index]
            label.setText(f"{item.label}: {item.value}")
            label.setVisible(True)

        for label in self._summary_labels[len(items):]:
            label.setVisible(False)

    def _apply_branches(
        self,
        branches: tuple[BranchSummary, ...],
        selected_branch: str | None,
    ) -> None:
        self.branch_list_group.setTitle(f"Branch List ({len(branches)})")
        self._branch_empty_label.setVisible(not branches)

        for index, branch in enumerate(branches):
            if index >= len(self._branch_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_branch_button(source)
                )
                self._branch_buttons.append(button)
                self._branch_list_layout.addWidget(button)
            button = self._branch_buttons[index]
            target = branch.commit_id[:12] if branch.commit_id is not None else "unborn"
            marker = "* " if branch.is_current else "  "
            button.setText(f"{marker}{branch.name} -> {target}")
            button.setChecked(branch.name == selected_branch)
            button._target_branch = branch.name
            button.setVisible(True)

        for button in self._branch_buttons[len(branches):]:
            button.setVisible(False)

    def _apply_conflicts(self) -> None:
        conflicts = self._conflicts()
        title = "Manual Resolution" if conflicts else "Repository State"
        self.manual_state_group.setTitle(f"{title} ({len(conflicts)})")
        self._conflict_empty_label.setVisible(not conflicts)

        for index, path in enumerate(conflicts):
            if index >= len(self._conflict_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(False)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_conflict_button(source)
                )
                self._conflict_buttons.append(button)
                self._manual_state_layout.addWidget(button)
            button = self._conflict_buttons[index]
            button.setText(path)
            button._target_path = path
            button.setVisible(True)

        for button in self._conflict_buttons[len(conflicts):]:
            button.setVisible(False)

    def _apply_lineages(self, lineages, selected_branch: str | None) -> None:
        self.lineage_group.setTitle(f"Lineages ({len(lineages)})")
        self._lineage_empty_label.setVisible(not lineages)

        for index, lineage in enumerate(lineages):
            if index >= len(self._lineage_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(False)
                self._lineage_buttons.append(button)
                self._lineage_layout.addWidget(button)
            button = self._lineage_buttons[index]
            marker = "* " if lineage.lineage_id == selected_branch else ""
            button.setText(
                f"{marker}{lineage.lineage_id} [{lineage.status}] "
                f"base={lineage.base_checkpoint_id or 'none'} "
                f"owned={', '.join(lineage.owned_paths) or '-'}"
            )
            button.setVisible(True)

        for button in self._lineage_buttons[len(lineages):]:
            button.setVisible(False)

    def _sync_actions(self) -> None:
        selected = self._selected_branch_summary()
        can_create = self.state.context is not None and self.state.context.is_lit_repository
        can_checkout_selected = (
            self.state.can_checkout
            and selected is not None
            and not selected.is_current
        )

        self.create_button.setEnabled(can_create and bool(self.create_name_input.text().strip()))
        self.checkout_selected_button.setEnabled(can_checkout_selected)
        self.checkout_panel.set_primary_enabled(
            self.state.can_checkout and bool(self.checkout_panel.revision_input.text().strip())
        )
        self.restore_panel.set_restore_enabled(
            self.state.context is not None and self.state.context.is_lit_repository
            and bool(self.restore_panel.path_input.text().strip())
        )
        self.merge_panel.set_primary_enabled(
            self.state.can_merge and bool(self.merge_panel.revision_input.text().strip())
        )
        self.merge_panel.set_secondary_enabled(self._active_operation_kind() == "merge")
        self.rebase_panel.set_primary_enabled(
            self.state.can_rebase and bool(self.rebase_panel.revision_input.text().strip())
        )
        self.rebase_panel.set_secondary_enabled(self._active_operation_kind() == "rebase")

    def _selected_branch_summary(self) -> BranchSummary | None:
        return next(
            (branch for branch in self.state.branches if branch.name == self.state.selected_branch),
            None,
        )

    def _conflicts(self) -> tuple[str, ...]:
        operation = self.state.context.operation if self.state.context is not None else None
        return operation.conflicts if operation is not None else ()

    def _active_operation_kind(self) -> str | None:
        operation = self.state.context.operation if self.state.context is not None else None
        return operation.kind if operation is not None else None

    def _checkout_description(self) -> str:
        if not self.state.can_checkout:
            return self.state.context.attention if self.state.context is not None else "Open a repository first."
        return "Checkout another branch or commit id. This rewrites the working tree."

    def _restore_description(self) -> str:
        if self._conflicts():
            return (
                "Restore rewrites the selected path from HEAD or another revision. "
                "Use it carefully because it discards manual edits."
            )
        return "Restore a path from HEAD or another revision to discard working tree changes."

    def _merge_description(self) -> str:
        if self._active_operation_kind() == "merge":
            return "A merge is in progress. Abort it here if you want to return to the pre-merge tree."
        if not self.state.can_merge:
            return self.state.context.attention if self.state.context is not None else "Open a repository first."
        return "Merge another local branch or commit into the current branch."

    def _rebase_description(self) -> str:
        if self._active_operation_kind() == "rebase":
            return "A rebase is in progress. Abort it here if you want to return to the original branch tip."
        if not self.state.can_rebase:
            return self.state.context.attention if self.state.context is not None else "Open a repository first."
        return "Rebase the current branch onto another local branch or commit."

    def _manual_state_text(self) -> str:
        operation = self.state.context.operation if self.state.context is not None else None
        if operation is not None:
            return operation.summary
        if self.state.context is None:
            return "No repository loaded."
        return self.state.context.attention or self.state.context.status_text

    def _promotion_preview_text(self) -> str:
        metadata = self.state.detail.metadata.body
        for line in metadata.splitlines():
            if line.startswith("Promotion preview:"):
                return line
        if self.state.context is None:
            return "Promotion preview: open a repository first."
        return "Promotion preview: select a lineage-backed branch to inspect promotion readiness."

    def _select_branch_button(self, button: QtWidgets.QPushButton) -> None:
        branch_name = getattr(button, "_target_branch", None)
        if branch_name is not None:
            self._on_select_branch(branch_name)

    def _select_conflict_button(self, button: QtWidgets.QPushButton) -> None:
        path = getattr(button, "_target_path", None)
        if path is not None:
            self.restore_panel.path_input.setText(path)

    def _create_branch_requested(self) -> None:
        name = self.create_name_input.text().strip()
        if not name:
            return
        start_point = self.create_start_input.text().strip() or "HEAD"
        self._on_create_branch_requested(name, start_point)

    def _checkout_selected_branch(self) -> None:
        selected = self._selected_branch_summary()
        if selected is not None and self.state.can_checkout and not selected.is_current:
            self._on_checkout_requested(selected.name)
