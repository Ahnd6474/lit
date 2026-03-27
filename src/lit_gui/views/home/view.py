from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from lit_gui.contracts import HomeViewState, RecentRepository, SummaryItem


class HomeView(QtWidgets.QWidget):
    def __init__(
        self,
        state: HomeViewState,
        *,
        on_open_requested,
        on_initialize_requested,
        on_recent_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self._on_open_requested = on_open_requested
        self._on_initialize_requested = on_initialize_requested
        self._on_recent_requested = on_recent_requested
        self._summary_labels: list[QtWidgets.QLabel] = []
        self._recent_buttons: list[QtWidgets.QPushButton] = []

        self.title_label = QtWidgets.QLabel()
        self.subtitle_label = QtWidgets.QLabel()
        self.path_input = QtWidgets.QLineEdit()
        self.open_button = QtWidgets.QPushButton("Open Folder")
        self.initialize_button = QtWidgets.QPushButton("Initialize Here")
        self.path_status_label = QtWidgets.QLabel()
        self.call_to_action_label = QtWidgets.QLabel()
        self.empty_recent_label = QtWidgets.QLabel("No recent repositories recorded yet.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        for label in (
            self.title_label,
            self.subtitle_label,
            self.path_status_label,
            self.call_to_action_label,
            self.empty_recent_label,
        ):
            label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        location_group = QtWidgets.QGroupBox()
        location_group.setTitle("Repository Location")
        location_layout = QtWidgets.QVBoxLayout(location_group)
        location_layout.setSpacing(8)
        location_layout.addWidget(self.path_input)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.open_button)
        action_row.addWidget(self.initialize_button)
        location_layout.addLayout(action_row)
        location_layout.addWidget(self.path_status_label)
        layout.addWidget(location_group)

        summary_group = QtWidgets.QGroupBox()
        summary_group.setTitle("Highlights")
        self._summary_layout = QtWidgets.QVBoxLayout(summary_group)
        layout.addWidget(summary_group)

        recent_group = QtWidgets.QGroupBox()
        recent_group.setTitle("Recent Repositories")
        self._recent_layout = QtWidgets.QVBoxLayout(recent_group)
        self._recent_layout.addWidget(self.empty_recent_label)
        layout.addWidget(recent_group)

        next_step_group = QtWidgets.QGroupBox()
        next_step_group.setTitle("Next Step")
        next_step_layout = QtWidgets.QVBoxLayout(next_step_group)
        next_step_layout.addWidget(self.call_to_action_label)
        layout.addWidget(next_step_group)
        layout.addStretch(1)

        self.open_button.clicked.connect(self._open_requested)
        self.initialize_button.clicked.connect(self._initialize_requested)

        self.apply_state(state)

    @property
    def recent_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._recent_buttons)

    def apply_state(self, state: HomeViewState) -> None:
        self.state = state
        self.title_label.setText(state.title)
        self.subtitle_label.setText(state.subtitle)
        if state.context is not None and state.context.root is not None:
            self.path_input.setText(str(state.context.root))
            self.path_status_label.setText(state.context.status_text)
        else:
            self.path_status_label.setText("Enter a folder path to open or initialize.")
        self.call_to_action_label.setText(state.call_to_action)
        self._apply_summary_items(state.highlights)
        self._apply_recent_repositories(state.recent_repositories)

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

    def _apply_recent_repositories(self, repositories: tuple[RecentRepository, ...]) -> None:
        self.empty_recent_label.setVisible(not repositories)
        for index, entry in enumerate(repositories):
            if index >= len(self._recent_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(False)
                button.clicked.connect(
                    lambda checked=False, source=button: self._open_recent_button(source)
                )
                self._recent_buttons.append(button)
                self._recent_layout.addWidget(button)
            button = self._recent_buttons[index]
            button.setText(f"{entry.root}\n{entry.summary}")
            button._target_root = entry.root
            button.setVisible(True)

        for button in self._recent_buttons[len(repositories):]:
            button.setVisible(False)

    def _open_requested(self) -> None:
        self._on_open_requested(Path(self.path_input.text().strip() or "."))

    def _initialize_requested(self) -> None:
        self._on_initialize_requested(Path(self.path_input.text().strip() or "."))

    def _open_recent_button(self, button: QtWidgets.QPushButton) -> None:
        target = getattr(button, "_target_root", None)
        if target is not None:
            self._on_recent_requested(Path(target))
