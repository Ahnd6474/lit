from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import ChangedPath, ChangesViewState, SummaryItem
from lit_gui.widgets.shared import DiffPanel


class ChangesView(QtWidgets.QWidget):
    def __init__(
        self,
        state: ChangesViewState,
        *,
        on_select_change,
        on_stage_paths_requested,
        on_commit_requested,
        on_refresh_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self._on_select_change = on_select_change
        self._on_stage_paths_requested = on_stage_paths_requested
        self._on_commit_requested = on_commit_requested
        self._on_refresh_requested = on_refresh_requested
        self._summary_labels: list[QtWidgets.QLabel] = []
        self._staged_buttons: list[QtWidgets.QPushButton] = []
        self._modified_buttons: list[QtWidgets.QPushButton] = []
        self._deleted_buttons: list[QtWidgets.QPushButton] = []
        self._untracked_buttons: list[QtWidgets.QPushButton] = []

        self.title_label = QtWidgets.QLabel()
        self.subtitle_label = QtWidgets.QLabel()
        self.root_label = QtWidgets.QLabel()
        self.stage_hint_label = QtWidgets.QLabel()
        self.commit_hint_label = QtWidgets.QLabel()
        self.stage_path_input = QtWidgets.QLineEdit()
        self.stage_path_button = QtWidgets.QPushButton("Stage Path")
        self.stage_selected_button = QtWidgets.QPushButton("Stage Selected")
        self.stage_all_button = QtWidgets.QPushButton("Stage All")
        self.refresh_button = QtWidgets.QPushButton("Refresh Changes")
        self.commit_message_input = QtWidgets.QLineEdit()
        self.commit_button = QtWidgets.QPushButton("Create Commit")
        self.diff_panel = DiffPanel("Working Tree Preview")

        self.staged_group = QtWidgets.QGroupBox()
        self.modified_group = QtWidgets.QGroupBox()
        self.deleted_group = QtWidgets.QGroupBox()
        self.untracked_group = QtWidgets.QGroupBox()
        self.stage_modified_button = QtWidgets.QPushButton("Stage Modified")
        self.stage_deleted_button = QtWidgets.QPushButton("Stage Deleted")
        self.stage_untracked_button = QtWidgets.QPushButton("Stage Untracked")
        self._staged_empty_label = QtWidgets.QLabel("No staged paths.")
        self._modified_empty_label = QtWidgets.QLabel("No modified paths.")
        self._deleted_empty_label = QtWidgets.QLabel("No deleted paths.")
        self._untracked_empty_label = QtWidgets.QLabel("No untracked paths.")
        self.staged_group.setTitle("Staged")
        self.modified_group.setTitle("Modified")
        self.deleted_group.setTitle("Deleted")
        self.untracked_group.setTitle("Untracked")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        for label in (
            self.title_label,
            self.subtitle_label,
            self.root_label,
            self.stage_hint_label,
            self.commit_hint_label,
            self._staged_empty_label,
            self._modified_empty_label,
            self._deleted_empty_label,
            self._untracked_empty_label,
        ):
            label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.root_label)

        summary_group = QtWidgets.QGroupBox()
        summary_group.setTitle("Summary")
        self._summary_layout = QtWidgets.QVBoxLayout(summary_group)
        layout.addWidget(summary_group)

        actions_group = QtWidgets.QGroupBox()
        actions_group.setTitle("Staging")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)
        actions_layout.addWidget(self.stage_hint_label)
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.stage_path_input)
        path_row.addWidget(self.stage_path_button)
        actions_layout.addLayout(path_row)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.stage_selected_button)
        action_row.addWidget(self.stage_all_button)
        action_row.addWidget(self.refresh_button)
        action_row.addStretch(1)
        actions_layout.addLayout(action_row)
        layout.addWidget(actions_group)

        content_row = QtWidgets.QHBoxLayout()
        groups_column = QtWidgets.QVBoxLayout()
        self._build_change_group(
            self.staged_group,
            self._staged_empty_label,
            None,
        )
        self._build_change_group(
            self.modified_group,
            self._modified_empty_label,
            self.stage_modified_button,
        )
        self._build_change_group(
            self.deleted_group,
            self._deleted_empty_label,
            self.stage_deleted_button,
        )
        self._build_change_group(
            self.untracked_group,
            self._untracked_empty_label,
            self.stage_untracked_button,
        )
        for group in (
            self.staged_group,
            self.modified_group,
            self.deleted_group,
            self.untracked_group,
        ):
            groups_column.addWidget(group)
        groups_column.addStretch(1)
        content_row.addLayout(groups_column, 1)
        content_row.addWidget(self.diff_panel, 2)
        layout.addLayout(content_row)

        commit_group = QtWidgets.QGroupBox()
        commit_group.setTitle("Commit")
        commit_layout = QtWidgets.QVBoxLayout(commit_group)
        commit_layout.addWidget(self.commit_hint_label)
        commit_layout.addWidget(self.commit_message_input)
        commit_row = QtWidgets.QHBoxLayout()
        commit_row.addWidget(self.commit_button)
        commit_row.addStretch(1)
        commit_layout.addLayout(commit_row)
        layout.addWidget(commit_group)
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._on_refresh_requested)
        self.stage_path_button.clicked.connect(self._stage_manual_path)
        self.stage_selected_button.clicked.connect(self._stage_selected_path)
        self.stage_all_button.clicked.connect(self._stage_all_unstaged)
        self.stage_modified_button.clicked.connect(self._stage_modified_paths)
        self.stage_deleted_button.clicked.connect(self._stage_deleted_paths)
        self.stage_untracked_button.clicked.connect(self._stage_untracked_paths)
        self.commit_button.clicked.connect(self._commit_requested)
        self.commit_message_input.textChanged.connect(lambda *_: self._sync_actions())

        self.apply_state(state)

    @property
    def change_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(
            self._staged_buttons
            + self._modified_buttons
            + self._deleted_buttons
            + self._untracked_buttons
        )

    def apply_state(self, state: ChangesViewState) -> None:
        self.state = state
        self.title_label.setText(state.title)
        self.subtitle_label.setText(state.subtitle)
        root = state.context.root if state.context is not None else None
        self.root_label.setText(f"Root: {root}" if root is not None else "Root: n/a")
        self.stage_hint_label.setText(
            "Stage the selected path, stage an entire change group, or enter a file or directory path."
        )
        self.commit_hint_label.setText(state.commit_message_hint)
        self.diff_panel.apply(
            title=state.selected_path or "No change selected",
            body=state.detail.selection.body,
            metadata=state.detail.metadata.body,
        )
        self._apply_summary_items(state.highlights)
        self._apply_change_group(
            group=self.staged_group,
            buttons=self._staged_buttons,
            empty_label=self._staged_empty_label,
            entries=state.staged,
            selected_path=state.selected_path,
        )
        self._apply_change_group(
            group=self.modified_group,
            buttons=self._modified_buttons,
            empty_label=self._modified_empty_label,
            entries=tuple(entry for entry in state.unstaged if entry.change_kind == "modified"),
            selected_path=state.selected_path,
        )
        self._apply_change_group(
            group=self.deleted_group,
            buttons=self._deleted_buttons,
            empty_label=self._deleted_empty_label,
            entries=tuple(entry for entry in state.unstaged if entry.change_kind == "deleted"),
            selected_path=state.selected_path,
        )
        self._apply_change_group(
            group=self.untracked_group,
            buttons=self._untracked_buttons,
            empty_label=self._untracked_empty_label,
            entries=tuple(entry for entry in state.unstaged if entry.change_kind == "untracked"),
            selected_path=state.selected_path,
        )
        if state.selected_path is not None and not self.stage_path_input.text().strip():
            self.stage_path_input.setText(state.selected_path)
        if not state.can_commit:
            self.commit_message_input.setText("")
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

    def _build_change_group(
        self,
        group: QtWidgets.QGroupBox,
        empty_label: QtWidgets.QLabel,
        action_button: QtWidgets.QPushButton | None,
    ) -> None:
        layout = QtWidgets.QVBoxLayout(group)
        if action_button is not None:
            layout.addWidget(action_button)
        layout.addWidget(empty_label)

    def _apply_change_group(
        self,
        *,
        group: QtWidgets.QGroupBox,
        buttons: list[QtWidgets.QPushButton],
        empty_label: QtWidgets.QLabel,
        entries: tuple[ChangedPath, ...],
        selected_path: str | None,
    ) -> None:
        group.setTitle(f"{group.title().split(' (', 1)[0] or 'Paths'} ({len(entries)})")
        empty_label.setVisible(not entries)

        layout = group.layout()
        assert layout is not None
        for index, entry in enumerate(entries):
            if index >= len(buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_change_button(source)
                )
                buttons.append(button)
                layout.addWidget(button)
            button = buttons[index]
            button.setText(f"{entry.path} [{entry.change_kind}]")
            button.setChecked(entry.path == selected_path)
            button._target_path = entry.path
            button.setVisible(True)

        for button in buttons[len(entries):]:
            button.setVisible(False)

    def _sync_actions(self) -> None:
        modified = tuple(entry.path for entry in self.state.unstaged if entry.change_kind == "modified")
        deleted = tuple(entry.path for entry in self.state.unstaged if entry.change_kind == "deleted")
        untracked = tuple(entry.path for entry in self.state.unstaged if entry.change_kind == "untracked")
        self.stage_selected_button.setEnabled(self.state.selected_path is not None)
        self.stage_all_button.setEnabled(bool(self.state.unstaged))
        self.stage_modified_button.setEnabled(bool(modified))
        self.stage_deleted_button.setEnabled(bool(deleted))
        self.stage_untracked_button.setEnabled(bool(untracked))
        self.commit_button.setEnabled(
            self.state.can_commit and bool(self.commit_message_input.text().strip())
        )

    def _select_change_button(self, button: QtWidgets.QPushButton) -> None:
        path = getattr(button, "_target_path", None)
        if path is not None:
            self._on_select_change(path)

    def _stage_manual_path(self) -> None:
        path = self.stage_path_input.text().strip()
        if path:
            self._on_stage_paths_requested((path,))

    def _stage_selected_path(self) -> None:
        if self.state.selected_path is not None:
            self._on_stage_paths_requested((self.state.selected_path,))

    def _stage_all_unstaged(self) -> None:
        paths = tuple(entry.path for entry in self.state.unstaged)
        if paths:
            self._on_stage_paths_requested(paths)

    def _stage_modified_paths(self) -> None:
        self._stage_matching_kind("modified")

    def _stage_deleted_paths(self) -> None:
        self._stage_matching_kind("deleted")

    def _stage_untracked_paths(self) -> None:
        self._stage_matching_kind("untracked")

    def _stage_matching_kind(self, change_kind: str) -> None:
        paths = tuple(entry.path for entry in self.state.unstaged if entry.change_kind == change_kind)
        if paths:
            self._on_stage_paths_requested(paths)

    def _commit_requested(self) -> None:
        message = self.commit_message_input.text().strip()
        if self.state.can_commit and message:
            self._on_commit_requested(message)
