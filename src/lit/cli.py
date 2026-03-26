from __future__ import annotations

import argparse

from lit.commands import register_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lit", description="Local-only version control.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_commands(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
