from __future__ import annotations

import argparse

from lit.commands import (
    add,
    artifact,
    branch,
    checkout,
    checkpoint,
    commit,
    doctor,
    diff,
    export,
    gc,
    init,
    lineage,
    log,
    merge,
    rebase,
    rollback,
    restore,
    status,
    verify,
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
    checkpoint,
    rollback,
    verify,
    lineage,
    artifact,
    gc,
    doctor,
    export,
)


def register_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    for module in COMMAND_MODULES:
        module.register(subparsers)
