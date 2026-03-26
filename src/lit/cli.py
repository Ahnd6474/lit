from __future__ import annotations

import argparse
from pathlib import Path

from lit.repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lit", description="Local-only version control.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a lit repository.")
    init_parser.add_argument("path", nargs="?", default=".", help="Repository root.")
    init_parser.add_argument(
        "-b",
        "--branch",
        default="main",
        help="Name of the initial branch.",
    )
    init_parser.set_defaults(handler=handle_init)

    for command_name in (
        "add",
        "commit",
        "log",
        "status",
        "diff",
        "restore",
        "checkout",
        "branch",
        "merge",
        "rebase",
    ):
        command_parser = subparsers.add_parser(command_name, help=f"{command_name} (pending)")
        command_parser.set_defaults(handler=handle_not_implemented)

    return parser


def handle_init(args: argparse.Namespace) -> int:
    target_root = Path(args.path).resolve()
    existed = (target_root / ".lit").exists()
    Repository.create(target_root, default_branch=args.branch)
    if existed:
        print(f"Reinitialized existing lit repository in {target_root / '.lit'}")
    else:
        print(f"Initialized empty lit repository in {target_root / '.lit'}")
    return 0


def handle_not_implemented(args: argparse.Namespace) -> int:
    print(f"`lit {args.command}` is reserved but not implemented yet.")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
