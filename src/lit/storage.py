from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

TEXT_ENCODING = "utf-8"


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def read_json(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding=TEXT_ENCODING))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_json(data), encoding=TEXT_ENCODING)


def read_text(path: Path, *, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding=TEXT_ENCODING)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding=TEXT_ENCODING)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
