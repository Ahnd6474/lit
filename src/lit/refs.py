from __future__ import annotations

from pathlib import Path

from lit.storage import read_text, write_text

SYMBOLIC_REF_PREFIX = "ref: "


def branch_ref(branch_name: str) -> str:
    return f"refs/heads/{branch_name}"


def parse_symbolic_ref(raw_value: str) -> str | None:
    stripped = raw_value.strip()
    if not stripped.startswith(SYMBOLIC_REF_PREFIX):
        return None
    return stripped[len(SYMBOLIC_REF_PREFIX) :]


def read_head(path: Path) -> str | None:
    return parse_symbolic_ref(read_text(path))


def write_head(path: Path, ref_name: str) -> None:
    write_text(path, f"{SYMBOLIC_REF_PREFIX}{ref_name}\n")


def read_ref(path: Path) -> str | None:
    value = read_text(path).strip()
    return value or None


def write_ref(path: Path, value: str | None) -> None:
    write_text(path, "" if value is None else f"{value}\n")
