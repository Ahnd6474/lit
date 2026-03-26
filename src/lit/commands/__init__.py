from __future__ import annotations

import argparse

from lit.commands import (
    add,
    branch,
    checkout,
    commit,
    diff,
    init,
    log,
    merge,
    rebase,
    restore,
    status,
)

COMMAND_MODULES = (
    init,
    add,
    commit,
    log,
    status,
    diff,
    restore,
    checkout,
    branch,
    merge,
    rebase,
)


def register_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    for module in COMMAND_MODULES:
        module.register(subparsers)
