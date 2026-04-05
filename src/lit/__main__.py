"""Module entrypoints for the installed `lit` commands.

Install contract:
- Preferred CLI: `lit` console script.
- No-PATH fallback: `python -m lit`.
- Published distribution: `lit`.
- Optional GUI: `lit-gui` (requires `pip install "lit[gui]"`).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from lit import cli


def main(argv: Sequence[str] | None = None) -> int:
    return cli.main(list(argv) if argv is not None else None)


def gui_main(argv: Sequence[str] | None = None) -> int:
    try:
        from importlib import import_module

        app = import_module("lit_gui.app")
    except ModuleNotFoundError as error:
        print(
            'lit-gui requires the "gui" extra. Install with: pip install "lit[gui]"',
            file=sys.stderr,
        )
        return 1

    return app.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
