from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("init", help="Initialize a lit repository.")
    parser.add_argument("path", nargs="?", default=".", help="Repository root.")
    parser.add_argument(
        "-b",
        "--branch",
        default="main",
        help="Name of the initial branch.",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    target_root = Path(args.path).resolve()
    existed = (target_root / ".lit").exists()
    Repository.create(target_root, default_branch=args.branch)
    if existed:
        print(f"Reinitialized existing lit repository in {target_root / '.lit'}")
    else:
        print(f"Initialized empty lit repository in {target_root / '.lit'}")
    return 0
