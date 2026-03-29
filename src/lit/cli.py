from __future__ import annotations

import argparse
import sys

from lit.commands import register_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lit",
        description="Local execution VCS for autonomous coding workflows on one machine.",
        epilog="Git export is a compatibility bridge. lit is not a drop-in Git clone.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_commands(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
