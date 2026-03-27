from __future__ import annotations

import json
import os
from pathlib import Path


def default_app_data_dir(app_name: str = "lit") -> Path:
    override = os.environ.get("LIT_GUI_APPDATA_DIR")
    if override:
        return Path(override).expanduser().resolve() / app_name

    for candidate in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
        if candidate:
            return Path(candidate).expanduser().resolve() / app_name

    return (Path.home() / ".local" / "state" / app_name).resolve()


class RecentRepositoriesStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = (
            Path(storage_path).expanduser().resolve()
            if storage_path is not None
            else default_app_data_dir() / "recent_repositories.json"
        )

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def load(self) -> tuple[Path, ...]:
        if not self._storage_path.exists():
            return ()

        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()

        roots = payload.get("roots", ()) if isinstance(payload, dict) else ()
        ordered: list[Path] = []
        for raw_root in roots:
            if not isinstance(raw_root, str):
                continue
            resolved = Path(raw_root).expanduser().resolve()
            if resolved not in ordered:
                ordered.append(resolved)
        return tuple(ordered)

    def save(self, roots: tuple[Path, ...]) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"roots": [str(Path(root).resolve()) for root in roots]}
        self._storage_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
