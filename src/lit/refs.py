from __future__ import annotations

from pathlib import Path

from lit.storage import read_text, write_text

SYMBOLIC_REF_PREFIX = "ref: "
HEADS_PREFIX = "refs/heads/"


def normalize_branch_name(branch_name: str) -> str:
    normalized = branch_name.strip().replace("\\", "/")
    if normalized.startswith(HEADS_PREFIX):
        normalized = normalized[len(HEADS_PREFIX) :]
    normalized = normalized.strip("/")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid branch name: {branch_name}")
    return normalized


def branch_ref(branch_name: str) -> str:
    return f"{HEADS_PREFIX}{normalize_branch_name(branch_name)}"


def branch_name_from_ref(ref_name: str | None) -> str | None:
    if ref_name is None or not ref_name.startswith(HEADS_PREFIX):
        return None
    return ref_name[len(HEADS_PREFIX) :]


def iter_ref_names(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    refs = [
        candidate.relative_to(root).as_posix()
        for candidate in root.rglob("*")
        if candidate.is_file()
    ]
    return tuple(sorted(refs))


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
