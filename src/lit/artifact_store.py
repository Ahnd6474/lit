from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from lit.artifacts import (
    ARTIFACTS_SCHEMA_VERSION,
    DEFAULT_ARTIFACT_HOME_ENV,
    ArtifactLink,
    ArtifactManifest,
    ArtifactPin,
    ArtifactReference,
    normalize_artifact_relative_path,
    split_content_address,
    validate_digest,
)
from lit.layout import LitLayout
from lit.storage import read_json, write_bytes, write_json
from lit.transactions import next_identifier, utc_now


def default_artifact_home() -> Path:
    configured = os.environ.get(DEFAULT_ARTIFACT_HOME_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".lit" / "artifacts").resolve()


def _prune_empty_directories(root: Path, start: Path) -> None:
    current = start
    while current != root and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


@dataclass(frozen=True, slots=True)
class ArtifactStoreConfig:
    schema_version: int = ARTIFACTS_SCHEMA_VERSION
    quota_bytes: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "quota_bytes": self.quota_bytes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactStoreConfig":
        if not data:
            return cls()
        quota = data.get("quota_bytes")
        return cls(
            schema_version=int(data.get("schema_version", ARTIFACTS_SCHEMA_VERSION)),
            quota_bytes=None if quota in (None, "") else int(quota),
        )


@dataclass(frozen=True, slots=True)
class ArtifactWriteSessionState:
    session_id: str
    kind: str = "generic"
    relative_path: str = ""
    content_type: str | None = None
    artifact_id: str | None = None
    pinned: bool = False
    created_at: str | None = None
    expected_size: int | None = None
    labels: tuple[str, ...] = ()
    links: tuple[ArtifactLink, ...] = ()

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "artifact_id": self.artifact_id,
            "created_at": self.created_at,
            "expected_size": self.expected_size,
            "kind": self.kind,
            "labels": list(self.labels),
            "pinned": self.pinned,
            "relative_path": self.relative_path,
            "session_id": self.session_id,
        }
        if self.content_type is not None:
            data["content_type"] = self.content_type
        if self.links:
            data["links"] = [link.to_dict() for link in self.links]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactWriteSessionState":
        if not data:
            raise ValueError("artifact write session is missing metadata")
        raw_links = data.get("links")
        links: list[ArtifactLink] = []
        if isinstance(raw_links, Iterable) and not isinstance(raw_links, (str, bytes)):
            for item in raw_links:
                if isinstance(item, Mapping):
                    link = ArtifactLink.from_dict(item)
                    if link is not None:
                        links.append(link)
        raw_labels = data.get("labels")
        labels = ()
        if isinstance(raw_labels, Iterable) and not isinstance(raw_labels, (str, bytes)):
            labels = tuple(str(item) for item in raw_labels)
        return cls(
            session_id=str(data["session_id"]),
            kind=str(data.get("kind", "generic")),
            relative_path=normalize_artifact_relative_path(data.get("relative_path")),
            content_type=None
            if data.get("content_type") is None
            else str(data.get("content_type")),
            artifact_id=None if data.get("artifact_id") is None else str(data.get("artifact_id")),
            pinned=bool(data.get("pinned", False)),
            created_at=None if data.get("created_at") is None else str(data.get("created_at")),
            expected_size=None
            if data.get("expected_size") in (None, "")
            else int(data.get("expected_size")),
            labels=labels,
            links=tuple(links),
        )


@dataclass(frozen=True, slots=True)
class ArtifactGCInputs:
    retained_digests: tuple[str, ...]
    pinned_digests: tuple[str, ...]
    linked_digests: tuple[str, ...]
    candidate_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactUsageReport:
    total_objects: int
    total_bytes: int
    pinned_objects: int
    pinned_bytes: int
    linked_objects: int
    linked_bytes: int
    reclaimable_objects: int
    reclaimable_bytes: int
    quota_bytes: int | None = None

    @property
    def over_quota(self) -> bool:
        return self.quota_bytes is not None and self.total_bytes > self.quota_bytes


@dataclass(frozen=True, slots=True)
class ArtifactGCResult:
    removed_digests: tuple[str, ...]
    removed_bytes: int
    retained_digests: tuple[str, ...]
    retained_bytes: int
    dry_run: bool = False


class ArtifactWriteSession:
    def __init__(self, store: "ArtifactStore", state: ArtifactWriteSessionState) -> None:
        self.store = store
        self.state = state

    @property
    def session_id(self) -> str:
        return self.state.session_id

    @property
    def bytes_written(self) -> int:
        if not self.store.session_data_path(self.session_id).exists():
            return 0
        return self.store.session_data_path(self.session_id).stat().st_size

    def append(self, data: bytes) -> int:
        self.store.ensure_layout()
        with self.store.session_data_path(self.session_id).open("ab") as handle:
            handle.write(data)
        return self.bytes_written

    def finalize(
        self,
        *,
        repository_root: str | Path | None = None,
        links: Iterable[ArtifactLink] = (),
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        manifest = self.store._finalize_session(
            self.state,
            repository_root=repository_root,
            links=tuple(links),
            pinned=pinned,
        )
        self.store._delete_session(self.session_id)
        return manifest

    def abort(self) -> None:
        self.store._delete_session(self.session_id)


class ArtifactStore:
    def __init__(self, home: str | Path | None = None) -> None:
        self.home = default_artifact_home() if home is None else Path(home).expanduser().resolve()

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def objects_dir(self) -> Path:
        return self.home / "objects" / "sha256"

    @property
    def pins_dir(self) -> Path:
        return self.home / "pins"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    def ensure_layout(self) -> None:
        for directory in (self.home, self.objects_dir, self.pins_dir, self.sessions_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            write_json(self.config_path, ArtifactStoreConfig().to_dict())

    def read_config(self) -> ArtifactStoreConfig:
        self.ensure_layout()
        return ArtifactStoreConfig.from_dict(read_json(self.config_path, default=None))

    def write_config(self, config: ArtifactStoreConfig) -> ArtifactStoreConfig:
        self.ensure_layout()
        write_json(self.config_path, config.to_dict())
        return config

    def set_quota(self, quota_bytes: int | None) -> ArtifactStoreConfig:
        if quota_bytes is not None and quota_bytes < 0:
            raise ValueError("artifact quota cannot be negative")
        return self.write_config(ArtifactStoreConfig(quota_bytes=quota_bytes))

    def object_path(self, digest_or_address: str) -> Path:
        _, digest = split_content_address(digest_or_address)
        return self.objects_dir / digest[:2] / digest[2:]

    def session_state_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def session_data_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.part"

    def pin_path(self, digest: str) -> Path:
        normalized = validate_digest(digest)
        return self.pins_dir / f"{normalized}.json"

    def has_object(self, digest_or_address: str) -> bool:
        return self.object_path(digest_or_address).exists()

    def read_bytes(self, digest_or_address: str) -> bytes:
        path = self.object_path(digest_or_address)
        if not path.exists():
            raise FileNotFoundError(f"artifact object not found: {digest_or_address}")
        return path.read_bytes()

    def open_bytes(self, digest_or_address: str) -> bytes:
        return self.read_bytes(digest_or_address)

    def store_bytes(
        self,
        data: bytes,
        *,
        repository_root: str | Path | None = None,
        artifact_id: str | None = None,
        kind: str = "generic",
        relative_path: str | Path | None = None,
        content_type: str | None = None,
        links: Iterable[ArtifactLink] = (),
        pinned: bool = False,
        labels: Iterable[str] = (),
    ) -> ArtifactManifest:
        self.ensure_layout()
        reference = ArtifactReference.from_bytes(data)
        object_path = self.object_path(reference.content_address)
        if not object_path.exists():
            write_bytes(object_path, data)
        manifest = self._build_manifest(
            artifact_id=artifact_id,
            kind=kind,
            relative_path=relative_path,
            content_type=content_type,
            reference=reference,
            links=tuple(links),
            pinned=pinned,
            labels=tuple(str(label) for label in labels),
        )
        if pinned:
            self.pin(
                reference.digest,
                artifact_id=manifest.artifact_id,
                owner_kind=manifest.owner_kind,
                owner_id=manifest.owner_id,
                reason="manifest",
            )
        if repository_root is not None:
            self.write_manifest(repository_root, manifest)
        return manifest

    def begin_write(
        self,
        *,
        session_id: str | None = None,
        artifact_id: str | None = None,
        kind: str = "generic",
        relative_path: str | Path | None = None,
        content_type: str | None = None,
        links: Iterable[ArtifactLink] = (),
        pinned: bool = False,
        expected_size: int | None = None,
        labels: Iterable[str] = (),
    ) -> ArtifactWriteSession:
        self.ensure_layout()
        resolved_session_id = session_id or next_identifier("artifact-upload")
        state = ArtifactWriteSessionState(
            session_id=resolved_session_id,
            kind=kind,
            relative_path=normalize_artifact_relative_path(relative_path),
            content_type=content_type,
            artifact_id=artifact_id,
            pinned=pinned,
            created_at=utc_now(),
            expected_size=expected_size,
            labels=tuple(str(label) for label in labels),
            links=tuple(links),
        )
        write_json(self.session_state_path(resolved_session_id), state.to_dict())
        data_path = self.session_data_path(resolved_session_id)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.touch(exist_ok=True)
        return ArtifactWriteSession(self, state)

    def open_session(self, session_id: str) -> ArtifactWriteSession:
        state = ArtifactWriteSessionState.from_dict(
            read_json(self.session_state_path(session_id), default=None)
        )
        return ArtifactWriteSession(self, state)

    def write_manifest(self, repository_root: str | Path, manifest: ArtifactManifest) -> Path:
        if manifest.artifact_id is None:
            raise ValueError("artifact manifests require an identifier")
        layout = LitLayout(Path(repository_root).resolve())
        path = layout.artifact_record_path(manifest.artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, manifest.to_dict())
        return path

    def read_manifest(self, repository_root: str | Path, artifact_id: str) -> ArtifactManifest:
        layout = LitLayout(Path(repository_root).resolve())
        path = layout.artifact_record_path(artifact_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact manifest not found: {artifact_id}")
        return ArtifactManifest.from_dict(read_json(path, default=None))

    def list_manifests(
        self,
        repository_root: str | Path,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> tuple[ArtifactManifest, ...]:
        layout = LitLayout(Path(repository_root).resolve())
        manifests: list[ArtifactManifest] = []
        for path in sorted(layout.artifacts.glob("*/artifact.json")):
            manifest = ArtifactManifest.from_dict(read_json(path, default=None))
            if owner_kind is None and owner_id is None:
                manifests.append(manifest)
                continue
            if any(
                (owner_kind is None or link.owner_kind == owner_kind)
                and (owner_id is None or link.owner_id == owner_id)
                for link in manifest.all_links
            ):
                manifests.append(manifest)
        return tuple(manifests)

    def list_linked_manifests(
        self,
        repository_root: str | Path,
        *,
        owner_kind: str,
        owner_id: str,
    ) -> tuple[ArtifactManifest, ...]:
        return self.list_manifests(
            repository_root,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )

    def list_revision_manifests(
        self,
        repository_root: str | Path,
        revision_id: str,
    ) -> tuple[ArtifactManifest, ...]:
        return self.list_linked_manifests(
            repository_root,
            owner_kind="revision",
            owner_id=revision_id,
        )

    def list_commit_manifests(
        self,
        repository_root: str | Path,
        revision_id: str,
    ) -> tuple[ArtifactManifest, ...]:
        return self.list_revision_manifests(repository_root, revision_id)

    def list_checkpoint_manifests(
        self,
        repository_root: str | Path,
        checkpoint_id: str,
    ) -> tuple[ArtifactManifest, ...]:
        return self.list_linked_manifests(
            repository_root,
            owner_kind="checkpoint",
            owner_id=checkpoint_id,
        )

    def list_lineage_manifests(
        self,
        repository_root: str | Path,
        lineage_id: str,
    ) -> tuple[ArtifactManifest, ...]:
        return self.list_linked_manifests(
            repository_root,
            owner_kind="lineage",
            owner_id=lineage_id,
        )

    def link_artifact(
        self,
        repository_root: str | Path,
        artifact_id: str,
        *links: ArtifactLink,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        manifest = self.read_manifest(repository_root, artifact_id)
        updated = manifest.with_links(*links)
        if pinned is not None:
            updated = updated.with_pinned(pinned)
        self.write_manifest(repository_root, updated)
        if updated.pinned and updated.digest is not None:
            self.pin(
                updated.digest,
                artifact_id=updated.artifact_id,
                owner_kind=updated.owner_kind,
                owner_id=updated.owner_id,
                reason="manifest",
            )
        elif updated.digest is not None:
            self.unpin(
                updated.digest,
                artifact_id=updated.artifact_id,
                owner_kind=updated.owner_kind,
                owner_id=updated.owner_id,
                reason="manifest",
            )
        return updated

    def link_artifact_to_owner(
        self,
        repository_root: str | Path,
        artifact_id: str,
        *,
        owner_kind: str,
        owner_id: str,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        return self.link_artifact(
            repository_root,
            artifact_id,
            ArtifactLink.owner(
                owner_kind,
                owner_id,
                relationship=relationship,
                note=note,
            ),
            pinned=pinned,
        )

    def link_revision_artifact(
        self,
        repository_root: str | Path,
        artifact_id: str,
        revision_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        return self.link_artifact(
            repository_root,
            artifact_id,
            ArtifactLink.revision(
                revision_id,
                relationship=relationship,
                note=note,
            ),
            pinned=pinned,
        )

    def link_commit_artifact(
        self,
        repository_root: str | Path,
        artifact_id: str,
        revision_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        return self.link_revision_artifact(
            repository_root,
            artifact_id,
            revision_id,
            relationship=relationship,
            note=note,
            pinned=pinned,
        )

    def link_checkpoint_artifact(
        self,
        repository_root: str | Path,
        artifact_id: str,
        checkpoint_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        return self.link_artifact(
            repository_root,
            artifact_id,
            ArtifactLink.checkpoint(
                checkpoint_id,
                relationship=relationship,
                note=note,
            ),
            pinned=pinned,
        )

    def link_lineage_artifact(
        self,
        repository_root: str | Path,
        artifact_id: str,
        lineage_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
        pinned: bool | None = None,
    ) -> ArtifactManifest:
        return self.link_artifact(
            repository_root,
            artifact_id,
            ArtifactLink.lineage(
                lineage_id,
                relationship=relationship,
                note=note,
            ),
            pinned=pinned,
        )

    def pin(
        self,
        digest_or_address: str,
        *,
        artifact_id: str | None = None,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        reason: str | None = None,
    ) -> tuple[ArtifactPin, ...]:
        self.ensure_layout()
        digest = split_content_address(digest_or_address)[1]
        existing = list(self.read_pins(digest))
        candidate = ArtifactPin(
            digest=digest,
            artifact_id=artifact_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            reason=reason,
            created_at=utc_now(),
        )
        key = (
            candidate.artifact_id,
            candidate.owner_kind,
            candidate.owner_id,
            candidate.reason,
        )
        if key not in {
            (pin.artifact_id, pin.owner_kind, pin.owner_id, pin.reason)
            for pin in existing
        }:
            existing.append(candidate)
            write_json(self.pin_path(digest), {"pins": [pin.to_dict() for pin in existing]})
        return tuple(existing)

    def read_pins(self, digest_or_address: str) -> tuple[ArtifactPin, ...]:
        digest = split_content_address(digest_or_address)[1]
        payload = read_json(self.pin_path(digest), default=None)
        if not payload:
            return ()
        raw_pins = payload.get("pins", [])
        pins: list[ArtifactPin] = []
        if isinstance(raw_pins, Iterable):
            for item in raw_pins:
                if isinstance(item, Mapping):
                    pin = ArtifactPin.from_dict(item)
                    if pin is not None:
                        pins.append(pin)
        return tuple(pins)

    def unpin(
        self,
        digest_or_address: str,
        *,
        artifact_id: str | None = None,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        reason: str | None = None,
    ) -> tuple[ArtifactPin, ...]:
        digest = split_content_address(digest_or_address)[1]
        existing = list(self.read_pins(digest))
        remaining = [
            pin
            for pin in existing
            if not (
                (artifact_id is None or pin.artifact_id == artifact_id)
                and (owner_kind is None or pin.owner_kind == owner_kind)
                and (owner_id is None or pin.owner_id == owner_id)
                and (reason is None or pin.reason == reason)
            )
        ]
        pin_path = self.pin_path(digest)
        if remaining:
            write_json(pin_path, {"pins": [pin.to_dict() for pin in remaining]})
        else:
            pin_path.unlink(missing_ok=True)
        return tuple(remaining)

    def iter_objects(self) -> tuple[str, ...]:
        if not self.objects_dir.exists():
            return ()
        digests: list[str] = []
        for directory in sorted(self.objects_dir.glob("*")):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*")):
                digest = f"{directory.name}{path.name}"
                if len(digest) == 64:
                    digests.append(digest)
        return tuple(digests)

    def artifact_gc_inputs(
        self,
        repo_roots: Iterable[str | Path] = (),
        *,
        keep_digests: Iterable[str] = (),
    ) -> ArtifactGCInputs:
        existing = set(self.iter_objects())
        pinned_digests = {
            path.stem
            for path in sorted(self.pins_dir.glob("*.json"))
            if path.stem in existing
        }
        linked_digests: set[str] = set()
        for repo_root in repo_roots:
            for manifest in self.list_manifests(repo_root):
                if manifest.digest is not None and manifest.all_links:
                    linked_digests.add(manifest.digest)
        retained = existing & (
            pinned_digests
            | linked_digests
            | {validate_digest(digest) for digest in keep_digests}
        )
        candidates = existing - retained
        return ArtifactGCInputs(
            retained_digests=tuple(sorted(retained)),
            pinned_digests=tuple(sorted(pinned_digests)),
            linked_digests=tuple(sorted(linked_digests)),
            candidate_digests=tuple(sorted(candidates)),
        )

    def usage_report(
        self,
        repo_roots: Iterable[str | Path] = (),
        *,
        keep_digests: Iterable[str] = (),
    ) -> ArtifactUsageReport:
        objects = {digest: self.object_path(digest).stat().st_size for digest in self.iter_objects()}
        inputs = self.artifact_gc_inputs(repo_roots, keep_digests=keep_digests)
        pinned = set(inputs.pinned_digests)
        linked = set(inputs.linked_digests)
        reclaimable = set(inputs.candidate_digests)
        return ArtifactUsageReport(
            total_objects=len(objects),
            total_bytes=sum(objects.values()),
            pinned_objects=sum(1 for digest in objects if digest in pinned),
            pinned_bytes=sum(size for digest, size in objects.items() if digest in pinned),
            linked_objects=sum(1 for digest in objects if digest in linked),
            linked_bytes=sum(size for digest, size in objects.items() if digest in linked),
            reclaimable_objects=sum(1 for digest in objects if digest in reclaimable),
            reclaimable_bytes=sum(size for digest, size in objects.items() if digest in reclaimable),
            quota_bytes=self.read_config().quota_bytes,
        )

    def size_report(
        self,
        repo_roots: Iterable[str | Path] = (),
        *,
        keep_digests: Iterable[str] = (),
    ) -> ArtifactUsageReport:
        return self.usage_report(repo_roots, keep_digests=keep_digests)

    def collect_garbage(
        self,
        repo_roots: Iterable[str | Path] = (),
        *,
        keep_digests: Iterable[str] = (),
        dry_run: bool = False,
    ) -> ArtifactGCResult:
        objects = {digest: self.object_path(digest).stat().st_size for digest in self.iter_objects()}
        inputs = self.artifact_gc_inputs(repo_roots, keep_digests=keep_digests)
        removed = tuple(sorted(inputs.candidate_digests))
        removed_bytes = sum(objects[digest] for digest in removed)
        if not dry_run:
            for digest in removed:
                path = self.object_path(digest)
                if path.exists():
                    path.unlink()
                    _prune_empty_directories(self.objects_dir, path.parent)
        retained = tuple(sorted(inputs.retained_digests))
        retained_bytes = sum(objects[digest] for digest in retained)
        return ArtifactGCResult(
            removed_digests=removed,
            removed_bytes=removed_bytes,
            retained_digests=retained,
            retained_bytes=retained_bytes,
            dry_run=dry_run,
        )

    def garbage_collection_inputs(
        self,
        repo_roots: Iterable[str | Path] = (),
        *,
        keep_digests: Iterable[str] = (),
    ) -> ArtifactGCInputs:
        return self.artifact_gc_inputs(repo_roots, keep_digests=keep_digests)

    def _build_manifest(
        self,
        *,
        artifact_id: str | None,
        kind: str,
        relative_path: str | Path | None,
        content_type: str | None,
        reference: ArtifactReference,
        links: tuple[ArtifactLink, ...],
        pinned: bool,
        labels: tuple[str, ...],
    ) -> ArtifactManifest:
        primary = links[0] if links else None
        return ArtifactManifest(
            artifact_id=artifact_id or next_identifier("artifact"),
            owner_kind="generic" if primary is None else primary.owner_kind,
            owner_id=None if primary is None else primary.owner_id,
            kind=kind,
            relative_path=normalize_artifact_relative_path(relative_path),
            content_type=content_type,
            digest=reference.digest,
            size_bytes=reference.size_bytes,
            created_at=utc_now(),
            pinned=pinned,
            reference=reference,
            links=links,
            labels=labels,
        )

    def _finalize_session(
        self,
        state: ArtifactWriteSessionState,
        *,
        repository_root: str | Path | None,
        links: tuple[ArtifactLink, ...],
        pinned: bool | None,
    ) -> ArtifactManifest:
        data_path = self.session_data_path(state.session_id)
        if not data_path.exists():
            raise FileNotFoundError(f"artifact session payload not found: {state.session_id}")
        data = data_path.read_bytes()
        if state.expected_size is not None and len(data) != state.expected_size:
            raise ValueError(
                f"artifact session {state.session_id} expected {state.expected_size} bytes, found {len(data)}"
            )
        return self.store_bytes(
            data,
            repository_root=repository_root,
            artifact_id=state.artifact_id,
            kind=state.kind,
            relative_path=state.relative_path,
            content_type=state.content_type,
            links=state.links + links,
            pinned=state.pinned if pinned is None else pinned,
            labels=state.labels,
        )

    def _delete_session(self, session_id: str) -> None:
        self.session_state_path(session_id).unlink(missing_ok=True)
        self.session_data_path(session_id).unlink(missing_ok=True)


__all__ = [
    "ArtifactGCInputs",
    "ArtifactGCResult",
    "ArtifactStore",
    "ArtifactStoreConfig",
    "ArtifactUsageReport",
    "ArtifactWriteSession",
    "ArtifactWriteSessionState",
    "default_artifact_home",
]
