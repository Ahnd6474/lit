from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import DetailPaneState, DetailSlotId, DetailSlotState


class DetailSlot(QtWidgets.QGroupBox):
    def __init__(self, slot_id: DetailSlotId, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.slot_id = slot_id
        self._body_label = QtWidgets.QLabel()
        self._body_label.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._body_label)

    @property
    def body_text(self) -> str:
        return self._body_label.text()

    def apply(self, state: DetailSlotState) -> None:
        self.setTitle(state.title)
        self._body_label.setText(state.body)


class SharedDetailSlots(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._slots = {
            DetailSlotId.SELECTION: DetailSlot(DetailSlotId.SELECTION),
            DetailSlotId.METADATA: DetailSlot(DetailSlotId.METADATA),
            DetailSlotId.GUIDANCE: DetailSlot(DetailSlotId.GUIDANCE),
        }

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        for slot_id in self.slot_ids:
            layout.addWidget(self._slots[slot_id])
        layout.addStretch(1)

    @property
    def slot_ids(self) -> tuple[DetailSlotId, ...]:
        return (
            DetailSlotId.SELECTION,
            DetailSlotId.METADATA,
            DetailSlotId.GUIDANCE,
        )

    def slot(self, slot_id: DetailSlotId) -> DetailSlot:
        return self._slots[slot_id]

    def slot_title(self, slot_id: DetailSlotId) -> str:
        return self._slots[slot_id].title()

    def slot_body(self, slot_id: DetailSlotId) -> str:
        return self._slots[slot_id].body_text

    def apply(self, detail: DetailPaneState) -> None:
        for state in detail.slots():
            self._slots[state.slot_id].apply(state)
