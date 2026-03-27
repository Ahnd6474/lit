from __future__ import annotations

import sys
from typing import Sequence

from PySide6 import QtWidgets

from lit_gui.contracts import RepositorySession
from lit_gui.shell import LitShellWindow
from lit_gui.session import LitRepositorySession


def create_application(argv: Sequence[str] | None = None) -> QtWidgets.QApplication:
    application = QtWidgets.QApplication.instance()
    if application is None:
        arguments = list(argv) if argv is not None else list(sys.argv)
        application = QtWidgets.QApplication(arguments)
        application.setApplicationName("lit")
    return application


def build_window(session: RepositorySession | None = None) -> LitShellWindow:
    create_application([])
    return LitShellWindow(session=session or LitRepositorySession())


def main(argv: Sequence[str] | None = None) -> int:
    application = create_application(argv)
    window = build_window()
    window.show()
    return application.exec()
