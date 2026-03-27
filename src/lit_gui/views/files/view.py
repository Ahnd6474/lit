from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import FileNode, FilesViewState, SummaryItem


class FilesView(QtWidgets.QWidget):
    def __init__(
        self,
        state: FilesViewState,
        *,
        on_select_file,
        on_refresh_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self._on_select_file = on_select_file
        self._on_refresh_requested = on_refresh_requested
        self._summary_labels: list[QtWidgets.QLabel] = []
        self._node_buttons: list[QtWidgets.QPushButton] = []

        self.title_label = QtWidgets.QLabel()
        self.subtitle_label = QtWidgets.QLabel()
        self.root_label = QtWidgets.QLabel()
        self.preview_title_label = QtWidgets.QLabel()
        self.preview_body_label = QtWidgets.QLabel()
        self.metadata_label = QtWidgets.QLabel()
        self.empty_tree_label = QtWidgets.QLabel("No repository tree loaded yet.")
        self.refresh_button = QtWidgets.QPushButton("Refresh Files")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        for label in (
            self.title_label,
            self.subtitle_label,
            self.root_label,
            self.preview_title_label,
            self.preview_body_label,
            self.metadata_label,
            self.empty_tree_label,
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

        tree_group = QtWidgets.QGroupBox()
        tree_group.setTitle("Repository Tree")
        self._tree_layout = QtWidgets.QVBoxLayout(tree_group)
        self._tree_layout.addWidget(self.empty_tree_label)
        content_row.addWidget(tree_group, 1)

        preview_group = QtWidgets.QGroupBox()
        preview_group.setTitle("Preview")
        preview_layout = QtWidgets.QVBoxLayout(preview_group)
        preview_layout.addWidget(self.preview_title_label)
        preview_layout.addWidget(self.preview_body_label)
        preview_layout.addWidget(self.metadata_label)
        content_row.addWidget(preview_group, 2)

        layout.addLayout(content_row)
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._on_refresh_requested)

        self.apply_state(state)

    @property
    def node_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return tuple(self._node_buttons)

    def apply_state(self, state: FilesViewState) -> None:
        self.state = state
        self.title_label.setText(state.title)
        self.subtitle_label.setText(state.subtitle)
        root = state.context.root if state.context is not None else None
        self.root_label.setText(f"Root: {root}" if root is not None else "Root: n/a")
        self.preview_title_label.setText(state.selected_path or "No file selected")
        self.preview_body_label.setText(state.detail.selection.body)
        self.metadata_label.setText(state.detail.metadata.body)
        self._apply_summary_items(state.highlights)
        self._apply_tree(state.tree, state.selected_path)

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

    def _apply_tree(self, nodes: tuple[FileNode, ...], selected_path: str | None) -> None:
        self.empty_tree_label.setVisible(not nodes)

        for index, node in enumerate(nodes):
            if index >= len(self._node_buttons):
                button = QtWidgets.QPushButton()
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, source=button: self._select_node_button(source)
                )
                self._node_buttons.append(button)
                self._tree_layout.addWidget(button)
            button = self._node_buttons[index]
            prefix = "[dir] " if node.node_kind == "directory" else "[file] "
            indent = "  " * node.depth
            button.setText(f"{indent}{prefix}{node.display_name}")
            button.setChecked(node.path == selected_path)
            button._target_path = node.path
            button.setVisible(True)

        for button in self._node_buttons[len(nodes):]:
            button.setVisible(False)

    def _select_node_button(self, button: QtWidgets.QPushButton) -> None:
        path = getattr(button, "_target_path", None)
        if path is not None:
            self._on_select_file(path)
