from __future__ import annotations

from PySide6 import QtWidgets


class DiffPanel(QtWidgets.QGroupBox):
    def __init__(
        self,
        title: str = "Preview",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self.title_label = QtWidgets.QLabel()
        self.body_label = QtWidgets.QLabel()
        self.metadata_label = QtWidgets.QLabel()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        for label in (self.title_label, self.body_label, self.metadata_label):
            label.setWordWrap(True)
            layout.addWidget(label)

    def apply(self, *, title: str, body: str, metadata: str) -> None:
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.metadata_label.setText(metadata)
