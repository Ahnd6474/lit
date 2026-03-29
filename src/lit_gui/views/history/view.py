from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import CommitSummary, HistoryViewState, SummaryItem
from lit_gui.widgets.shared import DiffPanel


class HistoryView(QtWidgets.QWidget):
    def __init__(
        self,
        state: HistoryViewState,
        *,
        on_select_commit,
        on_select_commit_path,
        on_refresh_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self._on_select_commit = on_select_commit
        self._on_select_commit_path = on_select_commit_path
        self._on_refresh_requested = on_refresh_requested
        self._summary_labels: list[QtWidgets.QLabel] = []
        self._commit_buttons: list[QtWidgets.QPushButton] = []
        self._checkpoint_buttons: list[QtWidgets.QPushButton] = []
        self._changed_file_buttons: list[QtWidgets.QPushButton] = []

        self.title_label = QtWidgets.QLabel()
        self.subtitle_label = QtWidgets.QLabel()
        self.root_label = QtWidgets.QLabel()
        self.refresh_button = QtWidgets.QPushButton("Refresh History")
        self.diff_panel = DiffPanel("Commit Preview")
        self.timeline_group = QtWidgets.QGroupBox()
        self.checkpoint_group = QtWidgets.QGroupBox()
        self.changed_files_group = QtWidgets.QGroupBox()
        self._timeline_empty_label = QtWidgets.QLabel("No commits loaded yet.")
        self._checkpoint_empty_label = QtWidgets.QLabel("Selected commit has no checkpoints.")
        self._changed_files_empty_label = QtWidgets.QLabel("Select a commit to inspect its changed files.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        for label in (
            self.title_label,
            self.subtitle_label,
            self.root_label,
            self._timeline_empty_label,
            self._checkpoint_empty_label,
            self._changed_files_empty_label,
        ):
            label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.root_label)

        summary_group = QtWidgets.QGroupBox()
        summary_group.setTitle("Summary")
        self._summary_layout = QtWidgets.QVBoxLayout(summary_group)
        layout.addWidget(summary_group)

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.refresh_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        content_row = QtWidgets.QHBoxLayout()

        left_column = QtWidgets.QVBoxLayout()
        self._timeline_layout = QtWidgets.QVBoxLayout(self.timeline_group)
        self._timeline_layout.addWidget(self._timeline_empty_label)
        left_column.addWidget(self.timeline_group)
        self._checkpoint_layout = QtWidgets.QVBoxLayout(self.checkpoint_group)
        self._checkpoint_layout.addWidget(self._checkpoint_empty_label)
        left_column.addWidget(self.checkpoint_group)
        self._changed_files_layout = QtWidgets.QVBoxLayout(self.changed_files_group)
        self._changed_files_layout.addWidget(self._changed_files_empty_label)
        left_column.addWidget(self.changed_files_group)
        left_column.addStretch(1)

        content_row.addLayout(left_column, 1)
        content_row.addWidget(self.diff_panel, 2)
        layout.addLayout(content_row)
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._on_refresh_requested)

        self.apply_state(state)

    @property
    def commit_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._commit_buttons)

    @property
    def changed_file_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._changed_file_buttons)

    @property
    def checkpoint_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._checkpoint_buttons)

    def apply_state(self, state: HistoryViewState) -> None:
        self.state = state
        self.title_label.setText(state.title)
        self.subtitle_label.setText(state.subtitle)
        root = state.context.root if state.context is not None else None
        self.root_label.setText(f"Root: {root}" if root is not None else "Root: n/a")
        self.diff_panel.apply(
            title=state.selected_path or state.selected_commit or "No commit selected",
            body=state.detail.selection.body,
            metadata=state.detail.metadata.body,
        )
        self._apply_summary_items(state.highlights)
        self._apply_commits(state.commits, state.selected_commit)
        selected = next(
            (commit for commit in state.commits if commit.commit_id == state.selected_commit),
            None,
        )
        self._apply_checkpoints(state.checkpoints, state.selected_commit)
        self._apply_changed_files(selected, state.selected_path)

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

    def _apply_commits(
        self,
        commits: tuple[CommitSummary, ...],
        selected_commit: str | None,
    ) -> None:
        self.timeline_group.setTitle(f"Timeline ({len(commits)})")
        self._timeline_empty_label.setVisible(not commits)

        for index, commit in enumerate(commits):
            if index >= len(self._commit_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_commit_button(source)
                )
                self._commit_buttons.append(button)
                self._timeline_layout.addWidget(button)
            button = self._commit_buttons[index]
            short_id = commit.commit_id[:12]
            timestamp = commit.committed_at or "unknown"
            author = commit.author or "lit"
            message = commit.message or "(empty commit message)"
            checkpoint_count = len(commit.checkpoint_ids)
            verification = commit.verification_status
            button.setText(
                f"{short_id}  {message}\n"
                f"{author}  {timestamp}  {len(commit.changed_paths)} path(s)  "
                f"{checkpoint_count} checkpoint(s)  {verification}"
            )
            button.setChecked(commit.commit_id == selected_commit)
            button._target_commit_id = commit.commit_id
            button.setVisible(True)

        for button in self._commit_buttons[len(commits):]:
            button.setVisible(False)

    def _apply_checkpoints(
        self,
        checkpoints,
        selected_commit: str | None,
    ) -> None:
        visible = tuple(
            checkpoint
            for checkpoint in checkpoints
            if selected_commit is None or checkpoint.revision_id == selected_commit
        )
        self.checkpoint_group.setTitle(f"Checkpoint Timeline ({len(visible)})")
        self._checkpoint_empty_label.setVisible(not visible)

        for index, checkpoint in enumerate(visible):
            if index >= len(self._checkpoint_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(False)
                self._checkpoint_buttons.append(button)
                self._checkpoint_layout.addWidget(button)
            button = self._checkpoint_buttons[index]
            tags = ["safe" if checkpoint.safe else "unsafe"]
            if checkpoint.pinned:
                tags.append("pinned")
            button.setText(
                f"{checkpoint.checkpoint_id} [{', '.join(tags)}] "
                f"{checkpoint.name or checkpoint.note or 'checkpoint'}"
            )
            button.setVisible(True)

        for button in self._checkpoint_buttons[len(visible):]:
            button.setVisible(False)

    def _apply_changed_files(
        self,
        selected: CommitSummary | None,
        selected_path: str | None,
    ) -> None:
        changed_paths = selected.changed_paths if selected is not None else ()
        self.changed_files_group.setTitle(f"Changed Files ({len(changed_paths)})")
        self._changed_files_empty_label.setVisible(not changed_paths)

        for index, path in enumerate(changed_paths):
            if index >= len(self._changed_file_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_changed_file_button(source)
                )
                self._changed_file_buttons.append(button)
                self._changed_files_layout.addWidget(button)
            button = self._changed_file_buttons[index]
            button.setText(path)
            button.setChecked(path == selected_path)
            button._target_path = path
            button.setVisible(True)

        for button in self._changed_file_buttons[len(changed_paths):]:
            button.setVisible(False)

    def _select_commit_button(self, button: QtWidgets.QPushButton) -> None:
        commit_id = getattr(button, "_target_commit_id", None)
        if commit_id is not None:
            self._on_select_commit(commit_id)

    def _select_changed_file_button(self, button: QtWidgets.QPushButton) -> None:
        path = getattr(button, "_target_path", None)
        if path is not None:
            self._on_select_commit_path(path)
