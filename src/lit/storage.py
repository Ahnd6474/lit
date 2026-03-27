from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol

TEXT_ENCODING = "utf-8"


class FileMutationWriter(Protocol):
    def write_bytes(self, path: Path, data: bytes) -> None: ...

    def write_json(self, path: Path, data: Any) -> None: ...

    def write_text(self, path: Path, value: str) -> None: ...

    def delete_path(self, path: Path) -> None: ...


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def read_json(path: Path, *, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding=TEXT_ENCODING))


def read_bytes(path: Path, *, default: bytes = b"") -> bytes:
    if not path.exists():
        return default
    return path.read_bytes()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_bytes(path: Path, data: bytes, *, mutation: FileMutationWriter | None = None) -> None:
    if mutation is not None:
        mutation.write_bytes(path, data)
        return
    _atomic_write_bytes(path, data)


def write_json(
    path: Path,
    data: Any,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    if mutation is not None:
        mutation.write_json(path, data)
        return
    write_bytes(path, dump_json(data).encode(TEXT_ENCODING))


def read_text(path: Path, *, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding=TEXT_ENCODING)


def write_text(
    path: Path,
    value: str,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    if mutation is not None:
        mutation.write_text(path, value)
        return
    write_bytes(path, value.encode(TEXT_ENCODING))


def delete_path(path: Path, *, mutation: FileMutationWriter | None = None) -> None:
    if mutation is not None:
        mutation.delete_path(path)
        return
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
