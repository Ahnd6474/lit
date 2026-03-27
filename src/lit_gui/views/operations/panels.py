from __future__ import annotations

from PySide6 import QtWidgets


class RevisionActionPanel(QtWidgets.QGroupBox):
    def __init__(
        self,
        *,
        title: str,
        description: str,
        primary_button_text: str,
        on_primary_requested,
        secondary_button_text: str | None = None,
        on_secondary_requested=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._on_primary_requested = on_primary_requested
        self._on_secondary_requested = on_secondary_requested
        self._has_secondary = secondary_button_text is not None

        self.description_label = QtWidgets.QLabel(description)
        self.revision_label = QtWidgets.QLabel("Target revision")
        self.revision_input = QtWidgets.QLineEdit()
        self.primary_button = QtWidgets.QPushButton(primary_button_text)
        self.secondary_button = QtWidgets.QPushButton(secondary_button_text or "")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        for label in (self.description_label, self.revision_label):
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addWidget(self.revision_input)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.primary_button)
        if self._has_secondary:
            button_row.addWidget(self.secondary_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.secondary_button.setVisible(self._has_secondary)
        self.primary_button.clicked.connect(self._submit_primary)
        if self._has_secondary and self._on_secondary_requested is not None:
            self.secondary_button.clicked.connect(self._on_secondary_requested)

    def set_description(self, text: str) -> None:
        self.description_label.setText(text)

    def set_primary_enabled(self, enabled: bool) -> None:
        self.primary_button.setEnabled(enabled)

    def set_secondary_enabled(self, enabled: bool) -> None:
        if self._has_secondary:
            self.secondary_button.setEnabled(enabled)

    def _submit_primary(self) -> None:
        revision = self.revision_input.text().strip()
        if revision:
            self._on_primary_requested(revision)


class RestoreActionPanel(QtWidgets.QGroupBox):
    def __init__(
        self,
        *,
        description: str,
        on_restore_requested,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle("Restore")
        self._on_restore_requested = on_restore_requested

        self.description_label = QtWidgets.QLabel(description)
        self.path_label = QtWidgets.QLabel("Path to restore")
        self.path_input = QtWidgets.QLineEdit()
        self.source_label = QtWidgets.QLabel("Source revision")
        self.source_input = QtWidgets.QLineEdit("HEAD")
        self.restore_button = QtWidgets.QPushButton("Restore Path")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        for label in (self.description_label, self.path_label, self.source_label):
            label.setWordWrap(True)
        layout.addWidget(self.description_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.path_input)
        layout.addWidget(self.source_label)
        layout.addWidget(self.source_input)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.restore_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.restore_button.clicked.connect(self._submit_restore)

    def set_description(self, text: str) -> None:
        self.description_label.setText(text)

    def set_restore_enabled(self, enabled: bool) -> None:
        self.restore_button.setEnabled(enabled)

    def _submit_restore(self) -> None:
        path = self.path_input.text().strip()
        if not path:
            return
        source = self.source_input.text().strip() or "HEAD"
        self._on_restore_requested((path,), source)
