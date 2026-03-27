from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from lit_gui.contracts import (
    NavigationTarget,
    RepositoryDescriptor,
    RepositorySession,
    SessionSnapshot,
    VIEW_ORDER,
)
from lit_gui.views import build_shell_views
from lit_gui.widgets.shared import SharedDetailSlots


def _navigation_label(target: NavigationTarget) -> str:
    return {
        NavigationTarget.HOME: "Home",
        NavigationTarget.CHANGES: "Changes",
        NavigationTarget.HISTORY: "History",
        NavigationTarget.BRANCHES: "Branches",
        NavigationTarget.FILES: "Files",
    }[target]


class SidebarPanel(QtWidgets.QFrame):
    def __init__(self, repository: RepositoryDescriptor | None, on_navigate, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[NavigationTarget, QtWidgets.QPushButton] = {}
        self._on_navigate = on_navigate
        self._title_label = QtWidgets.QLabel("lit")
        self._repository_label = QtWidgets.QLabel()
        self._root_label = QtWidgets.QLabel()
        self._branch_label = QtWidgets.QLabel()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label.setWordWrap(True)
        self._repository_label.setWordWrap(True)
        self._root_label.setWordWrap(True)
        self._branch_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._repository_label)
        layout.addWidget(self._root_label)
        layout.addWidget(self._branch_label)

        for target in VIEW_ORDER:
            button = QtWidgets.QPushButton(_navigation_label(target))
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, destination=target: self._on_navigate(destination))
            self._buttons[target] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.setMinimumWidth(240)
        self.apply_repository(repository)

    def apply_repository(self, repository: RepositoryDescriptor | None) -> None:
        if repository is None:
            self._repository_label.setText("No repository loaded")
            self._root_label.setText("Open a folder to start.")
            self._branch_label.setText("Branch: n/a")
            return
        self._repository_label.setText(f"Repository: {repository.name}")
        self._root_label.setText(f"Path: {repository.root}" if repository.root is not None else "Path: n/a")
        branch_name = repository.current_branch or "none"
        self._branch_label.setText(f"Branch: {branch_name}")

    def set_active(self, target: NavigationTarget) -> None:
        for destination, button in self._buttons.items():
            button.setChecked(destination == target)

    def is_active(self, target: NavigationTarget) -> bool:
        return self._buttons[target].isChecked()


class LitShellWindow(QtWidgets.QMainWindow):
    def __init__(self, session: RepositorySession, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._snapshot = session.snapshot()
        self._view_index: dict[NavigationTarget, int] = {}
        self._views = build_shell_views(
            self._snapshot,
            on_open_requested=self._open_repository_requested,
            on_initialize_requested=self._initialize_repository_requested,
            on_recent_requested=self._open_repository_requested,
            on_select_file=self._select_file_requested,
            on_refresh_requested=self._refresh_requested,
        )
        self._active_view = self._snapshot.default_view

        self.sidebar: SidebarPanel
        self.center_stack: QtWidgets.QStackedWidget
        self.detail_slots: SharedDetailSlots
        self.splitter: QtWidgets.QSplitter

        self.setWindowTitle("lit")
        self.resize(1440, 900)
        self._build_shell()
        self.show_view(self._active_view)

    @property
    def available_views(self) -> tuple[NavigationTarget, ...]:
        return VIEW_ORDER

    @property
    def active_view(self) -> NavigationTarget:
        return self._active_view

    @property
    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def view(self, target: NavigationTarget):
        return self._views[target]

    def show_view(self, target: NavigationTarget) -> None:
        self._active_view = target
        self.center_stack.setCurrentIndex(self._view_index[target])
        self.sidebar.set_active(target)
        self.detail_slots.apply(self._snapshot.for_view(target).detail)

    def apply_snapshot(
        self,
        snapshot: SessionSnapshot,
        *,
        preferred_view: NavigationTarget | None = None,
    ) -> None:
        self._snapshot = snapshot
        self.sidebar.apply_repository(snapshot.repository)
        for target in VIEW_ORDER:
            view = self._views[target]
            apply_state = getattr(view, "apply_state", None)
            if callable(apply_state):
                apply_state(snapshot.for_view(target))

        target = preferred_view or self._active_view
        self.show_view(target)

    def _build_shell(self) -> None:
        root = QtWidgets.QWidget(self)
        root_layout = QtWidgets.QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.sidebar = SidebarPanel(self._snapshot.repository, self.show_view)
        self.center_stack = QtWidgets.QStackedWidget()
        self.detail_slots = SharedDetailSlots()
        self.detail_slots.setMinimumWidth(320)

        for target in VIEW_ORDER:
            self._view_index[target] = self.center_stack.addWidget(self._views[target])

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.center_stack)
        self.splitter.addWidget(self.detail_slots)
        self.splitter.setSizes([260, 840, 340])

        root_layout.addWidget(self.splitter)
        self.setCentralWidget(root)

    def _open_repository_requested(self, root) -> None:
        snapshot = self._session.open_repository(root)
        self.apply_snapshot(snapshot, preferred_view=snapshot.default_view)

    def _initialize_repository_requested(self, root) -> None:
        snapshot = self._session.initialize_repository(root)
        self.apply_snapshot(snapshot, preferred_view=snapshot.default_view)

    def _refresh_requested(self) -> None:
        snapshot = self._session.refresh()
        self.apply_snapshot(snapshot, preferred_view=self._active_view)

    def _select_file_requested(self, path: str) -> None:
        snapshot = self._session.select_file(path)
        self.apply_snapshot(snapshot, preferred_view=NavigationTarget.FILES)
