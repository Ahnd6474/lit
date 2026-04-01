from __future__ import annotations

import importlib
import sys
import types

import pytest


def _clear_lit_gui_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "lit_gui" or module_name.startswith("lit_gui."):
            sys.modules.pop(module_name, None)


def _install_fake_pyside6(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Signal:
        def __init__(self) -> None:
            self._callbacks: list[object] = []

        def connect(self, callback) -> None:
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs) -> None:
            for callback in tuple(self._callbacks):
                callback(*args, **kwargs)

    class _Widget:
        def __init__(self, parent=None) -> None:
            self.parent = parent
            self._layout = None
            self._object_name = ""
            self.minimum_width = None
            self.maximum_width = None
            self.visible = False
            self.enabled = True

        def setLayout(self, layout) -> None:
            self._layout = layout

        def layout(self):
            return self._layout

        def setObjectName(self, name: str) -> None:
            self._object_name = name

        def objectName(self) -> str:
            return self._object_name

        def setMinimumWidth(self, width: int) -> None:
            self.minimum_width = width

        def setMaximumWidth(self, width: int) -> None:
            self.maximum_width = width

        def setContentsMargins(self, *margins: int) -> None:
            self.contents_margins = margins

        def show(self) -> None:
            self.visible = True

        def hide(self) -> None:
            self.visible = False

        def setVisible(self, visible: bool) -> None:
            self.visible = visible

        def isVisible(self) -> bool:
            return self.visible

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

        def isEnabled(self) -> bool:
            return self.enabled

    class _MainWindow(_Widget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._central_widget = None
            self._title = ""
            self._size = (0, 0)

        def setCentralWidget(self, widget) -> None:
            self._central_widget = widget

        def centralWidget(self):
            return self._central_widget

        def setWindowTitle(self, title: str) -> None:
            self._title = title

        def windowTitle(self) -> str:
            return self._title

        def resize(self, width: int, height: int) -> None:
            self._size = (width, height)

    class _Label(_Widget):
        def __init__(self, text: str = "", parent=None) -> None:
            super().__init__(parent)
            self._text = text

        def setText(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

        def setWordWrap(self, enabled: bool) -> None:
            self.word_wrap = enabled

    class _PushButton(_Label):
        def __init__(self, text: str = "", parent=None) -> None:
            super().__init__(text, parent)
            self.clicked = _Signal()
            self._checkable = False
            self._checked = False

        def setCheckable(self, enabled: bool) -> None:
            self._checkable = enabled

        def setChecked(self, checked: bool) -> None:
            self._checked = checked

        def isChecked(self) -> bool:
            return self._checked

    class _LineEdit(_Widget):
        def __init__(self, text: str = "", parent=None) -> None:
            super().__init__(parent)
            self._text = text
            self.textChanged = _Signal()

        def setText(self, text: str) -> None:
            self._text = text
            self.textChanged.emit(text)

        def text(self) -> str:
            return self._text

    class _Frame(_Widget):
        pass

    class _GroupBox(_Widget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._title = ""

        def setTitle(self, title: str) -> None:
            self._title = title

        def title(self) -> str:
            return self._title

    class _Layout:
        def __init__(self, parent=None) -> None:
            self.parent = parent
            self.items: list[tuple[str, object]] = []
            if parent is not None and hasattr(parent, "setLayout"):
                parent.setLayout(self)

        def addWidget(self, widget, stretch: int = 0) -> None:
            self.items.append(("widget", widget))

        def addLayout(self, layout, stretch: int = 0) -> None:
            self.items.append(("layout", layout))

        def addStretch(self, stretch: int = 0) -> None:
            self.items.append(("stretch", stretch))

        def setContentsMargins(self, *margins: int) -> None:
            self.contents_margins = margins

        def setSpacing(self, spacing: int) -> None:
            self.spacing = spacing

    class _VBoxLayout(_Layout):
        pass

    class _HBoxLayout(_Layout):
        pass

    class _Splitter(_Widget):
        def __init__(self, orientation, parent=None) -> None:
            super().__init__(parent)
            self.orientation = orientation
            self.widgets: list[object] = []
            self.sizes: list[int] = []

        def addWidget(self, widget) -> None:
            self.widgets.append(widget)

        def setSizes(self, sizes: list[int]) -> None:
            self.sizes = list(sizes)

        def count(self) -> int:
            return len(self.widgets)

    class _StackedWidget(_Widget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.widgets: list[object] = []
            self._current_index = -1

        def addWidget(self, widget) -> int:
            self.widgets.append(widget)
            if self._current_index == -1:
                self._current_index = 0
            return len(self.widgets) - 1

        def setCurrentIndex(self, index: int) -> None:
            self._current_index = index

        def currentIndex(self) -> int:
            return self._current_index

        def currentWidget(self):
            return self.widgets[self._current_index]

    class _Application:
        _instance = None

        def __init__(self, args) -> None:
            type(self)._instance = self
            self.args = list(args)
            self.application_name = ""

        @classmethod
        def instance(cls):
            return cls._instance

        def setApplicationName(self, name: str) -> None:
            self.application_name = name

        def exec(self) -> int:
            return 0

    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtwidgets.QApplication = _Application
    qtwidgets.QFrame = _Frame
    qtwidgets.QGroupBox = _GroupBox
    qtwidgets.QHBoxLayout = _HBoxLayout
    qtwidgets.QLabel = _Label
    qtwidgets.QLineEdit = _LineEdit
    qtwidgets.QMainWindow = _MainWindow
    qtwidgets.QPushButton = _PushButton
    qtwidgets.QSplitter = _Splitter
    qtwidgets.QStackedWidget = _StackedWidget
    qtwidgets.QVBoxLayout = _VBoxLayout
    qtwidgets.QWidget = _Widget

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = types.SimpleNamespace(Horizontal=1)

    pyside6 = types.ModuleType("PySide6")
    pyside6.QtCore = qtcore
    pyside6.QtWidgets = qtwidgets

    monkeypatch.setitem(sys.modules, "PySide6", pyside6)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)


@pytest.fixture
def gui_modules(monkeypatch: pytest.MonkeyPatch):
    _clear_lit_gui_modules()
    _install_fake_pyside6(monkeypatch)
    return types.SimpleNamespace(
        app=importlib.import_module("lit_gui.app"),
        contracts=importlib.import_module("lit_gui.contracts"),
        persistence=importlib.import_module("lit_gui.persistence"),
        session=importlib.import_module("lit_gui.session"),
    )
