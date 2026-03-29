from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from lit.backend_api import LitBackendService
from lit.repository import Repository


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )


def current_repository() -> Repository:
    return Repository.discover(Path.cwd())


def current_root() -> Path:
    return current_repository().root


def backend() -> LitBackendService:
    return LitBackendService()


def short_id(value: str | None) -> str:
    if not value:
        return "none"
    return value[:12]


def emit(args: argparse.Namespace, payload: Any, render_human) -> None:
    if getattr(args, "json", False):
        json.dump(_json_ready(payload), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return
    text = render_human(payload)
    if text:
        print(text)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if is_dataclass(value):
        return {
            field.name: _json_ready(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    return str(value)
