from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lit.layout import LitLayout
from lit.storage import (
    TEXT_ENCODING,
    _atomic_write_bytes,
    delete_path,
    dump_json,
    read_json,
    read_text,
    write_json,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def next_identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class JournalBackup:
    target_path: str
    existed: bool
    backup_file: str | None = None
    mode: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "JournalBackup":
        return cls(
            target_path=str(data["target_path"]),
            existed=bool(data["existed"]),
            backup_file=None if data.get("backup_file") is None else str(data["backup_file"]),
            mode=None if data.get("mode") is None else int(data["mode"]),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "event": "backup",
            "existed": self.existed,
            "target_path": self.target_path,
        }
        if self.backup_file is not None:
            data["backup_file"] = self.backup_file
        if self.mode is not None:
            data["mode"] = self.mode
        return data


class RepositoryLock(AbstractContextManager["RepositoryLock"]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.owner = {
            "created_at": utc_now(),
            "pid": os.getpid(),
            "token": uuid.uuid4().hex,
        }
        self._acquired = False

    def acquire(self) -> "RepositoryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dump_json(self.owner).encode(TEXT_ENCODING)
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                if not _clear_stale_lock(self.path):
                    owner = read_json(self.path, default={}) or {}
                    pid = owner.get("pid")
                    raise RuntimeError(
                        f"repository is locked by pid {pid if pid is not None else 'unknown'}"
                    )
                continue
            try:
                os.write(descriptor, payload)
            finally:
                os.close(descriptor)
            self._acquired = True
            return self

    def release(self) -> None:
        if self._acquired and self.path.exists():
            self.path.unlink()
        self._acquired = False

    def __enter__(self) -> "RepositoryLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class JournaledTransaction(AbstractContextManager["JournaledTransaction"]):
    def __init__(self, layout: LitLayout, *, kind: str, message: str | None = None) -> None:
        self.layout = layout
        self.kind = kind
        self.message = message
        self.operation_id = next_identifier(kind)
        self.journal_path = layout.journal_path(self.operation_id)
        self.backup_dir = layout.journal_dir(self.operation_id)
        self.lock = RepositoryLock(layout.lock_path())
        self._backups: dict[str, JournalBackup] = {}
        self._finished = False

    def __enter__(self) -> "JournaledTransaction":
        self.lock.acquire()
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._append(
            {
                "event": "begin",
                "kind": self.kind,
                "message": self.message,
                "operation_id": self.operation_id,
                "repository_root": self.layout.root.as_posix(),
                "started_at": utc_now(),
            }
        )
        return self

    def write_bytes(self, path: Path, data: bytes) -> None:
        self._record_backup(path)
        _atomic_write_bytes(path, data)

    def write_json(self, path: Path, data: Any) -> None:
        self.write_bytes(path, dump_json(data).encode(TEXT_ENCODING))

    def write_text(self, path: Path, value: str) -> None:
        self.write_bytes(path, value.encode(TEXT_ENCODING))

    def delete_path(self, path: Path) -> None:
        if not path.exists():
            return
        self._record_backup(path)
        delete_path(path)

    def commit(self) -> None:
        if self._finished:
            return
        self._append({"event": "commit", "finished_at": utc_now()})
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        self._finished = True

    def rollback(self) -> None:
        if self._finished:
            return
        _restore_backups(self.backup_dir, tuple(self._backups.values()))
        self._append({"event": "rollback", "finished_at": utc_now()})
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        self._finished = True

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.lock.release()

    def _record_backup(self, path: Path) -> None:
        key = str(path.resolve())
        if key in self._backups:
            return
        if path.exists():
            backup_name = f"{len(self._backups):04d}.bak"
            backup_path = self.backup_dir / backup_name
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(path, backup_path)
            else:
                _atomic_write_bytes(backup_path, path.read_bytes())
            backup = JournalBackup(
                target_path=key,
                existed=True,
                backup_file=backup_name,
                mode=path.stat().st_mode,
            )
        else:
            backup = JournalBackup(target_path=key, existed=False)
        self._backups[key] = backup
        self._append(backup.to_dict())

    def _append(self, entry: dict[str, object]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding=TEXT_ENCODING) as handle:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")


def recover_pending_transactions(layout: LitLayout) -> tuple[str, ...]:
    layout.journals.mkdir(parents=True, exist_ok=True)
    recovered: list[str] = []
    for journal_path in sorted(layout.journals.glob("*.jsonl")):
        entries = [
            json.loads(line)
            for line in read_text(journal_path).splitlines()
            if line.strip()
        ]
        if not entries:
            continue
        terminal_event = str(entries[-1].get("event", ""))
        operation_id = str(entries[0].get("operation_id", journal_path.stem))
        backup_entries = tuple(
            JournalBackup.from_dict(entry)
            for entry in entries
            if entry.get("event") == "backup"
        )
        if terminal_event in {"commit", "rollback"}:
            backup_dir = layout.journal_dir(operation_id)
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            continue

        _restore_backups(layout.journal_dir(operation_id), backup_entries)
        recovered.append(operation_id)

        operation_path = layout.operation_path(operation_id)
        record = read_json(operation_path, default=None)
        if record is not None:
            record["status"] = "failed"
            record["finished_at"] = utc_now()
            message = str(record.get("message", "")).strip()
            record["message"] = (
                f"{message}; recovered by aborting an unfinished transaction"
                if message
                else "Recovered by aborting an unfinished transaction."
            )
            write_json(operation_path, record)

        with journal_path.open("a", encoding=TEXT_ENCODING) as handle:
            handle.write(json.dumps({"event": "rollback", "finished_at": utc_now()}, sort_keys=True))
            handle.write("\n")

        backup_dir = layout.journal_dir(operation_id)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    _clear_stale_lock(layout.lock_path())
    return tuple(recovered)


def _restore_backups(backup_dir: Path, backups: tuple[JournalBackup, ...]) -> None:
    for backup in reversed(backups):
        target = Path(backup.target_path)
        if backup.existed:
            if backup.backup_file is None:
                continue
            source = backup_dir / backup.backup_file
            if source.is_dir():
                if target.exists():
                    delete_path(target)
                shutil.copytree(source, target)
            else:
                _atomic_write_bytes(target, source.read_bytes())
            if backup.mode is not None and target.exists():
                target.chmod(backup.mode)
            continue
        if target.exists():
            delete_path(target)


def _clear_stale_lock(path: Path) -> bool:
    if not path.exists():
        return True
    owner = read_json(path, default={}) or {}
    pid = owner.get("pid")
    if isinstance(pid, int) and _pid_is_alive(pid):
        return False
    path.unlink(missing_ok=True)
    return True


__all__ = [
    "JournaledTransaction",
    "RepositoryLock",
    "next_identifier",
    "recover_pending_transactions",
    "utc_now",
]
