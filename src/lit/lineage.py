from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from lit.domain import LineageRecord as DomainLineageRecord
from lit.layout import LitLayout
from lit.refs import delete_ref, normalize_branch_name, write_ref
from lit.storage import FileMutationWriter, read_json, write_json
from lit.transactions import JournaledTransaction, utc_now

if TYPE_CHECKING:
    from lit.repository import Repository, TrackedFile


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _string(value: object | None, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Path)):
        return (str(value),)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def _append_unique(existing: tuple[str, ...], additional: tuple[str, ...]) -> tuple[str, ...]:
    ordered = list(existing)
    seen = set(existing)
    for item in additional:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return tuple(ordered)


def normalize_owned_path(path: str | Path) -> str:
    normalized = str(path).strip().replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError(f"invalid owned path: {path}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid owned path: {path}")
    return normalized


def _normalize_owned_paths(paths: Iterable[str | Path]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for path in paths:
        candidate = normalize_owned_path(path)
        if candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return tuple(normalized)


def _path_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _path_within_scopes(path: str, scopes: tuple[str, ...]) -> bool:
    return any(_path_overlap(path, scope) for scope in scopes)


class LineageStatus(StrEnum):
    ACTIVE = "active"
    PROMOTED = "promoted"
    DISCARDED = "discarded"

    @classmethod
    def coerce(cls, value: object | None) -> "LineageStatus":
        if value is None:
            return cls.ACTIVE
        try:
            return cls(str(value))
        except ValueError:
            return cls.ACTIVE


class PromotionConflictType(StrEnum):
    DESTINATION_CHANGED = "destination_changed"
    OWNERSHIP_VIOLATION = "ownership_violation"
    RESERVED_BY_LINEAGE = "reserved_by_lineage"
    INACTIVE_SOURCE = "inactive_source"
    INACTIVE_DESTINATION = "inactive_destination"


@dataclass(frozen=True, slots=True)
class ManagedLineage:
    schema_version: int = 1
    lineage_id: str = "main"
    head_revision: str | None = None
    base_checkpoint_id: str | None = None
    forked_from: str | None = None
    promoted_from: str | None = None
    promoted_to: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    promoted_at: str | None = None
    discarded_at: str | None = None
    last_switched_at: str | None = None
    title: str = ""
    description: str = ""
    status: LineageStatus = LineageStatus.ACTIVE
    checkpoint_ids: tuple[str, ...] = ()
    owned_paths: tuple[str, ...] = ()
    allow_owned_path_overlap_with: tuple[str, ...] = ()

    @property
    def current_head_revision(self) -> str | None:
        return self.head_revision

    def allows_overlap_with(self, lineage_id: str) -> bool:
        return lineage_id in self.allow_owned_path_overlap_with

    def to_dict(self) -> dict[str, object]:
        return {
            "allow_owned_path_overlap_with": list(self.allow_owned_path_overlap_with),
            "base_checkpoint_id": self.base_checkpoint_id,
            "checkpoint_ids": list(self.checkpoint_ids),
            "created_at": self.created_at,
            "description": self.description,
            "discarded_at": self.discarded_at,
            "forked_from": self.forked_from,
            "head_revision": self.head_revision,
            "last_switched_at": self.last_switched_at,
            "lineage_id": self.lineage_id,
            "owned_paths": list(self.owned_paths),
            "promoted_at": self.promoted_at,
            "promoted_from": self.promoted_from,
            "promoted_to": self.promoted_to,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "title": self.title,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ManagedLineage":
        if not data:
            return cls()
        discarded_at = _optional_string(data.get("discarded_at"))
        status = LineageStatus.coerce(data.get("status"))
        if "status" not in data and discarded_at is not None:
            status = LineageStatus.DISCARDED
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            lineage_id=_string(data.get("lineage_id"), default="main"),
            head_revision=_optional_string(data.get("head_revision")),
            base_checkpoint_id=_optional_string(data.get("base_checkpoint_id")),
            forked_from=_optional_string(data.get("forked_from")),
            promoted_from=_optional_string(data.get("promoted_from")),
            promoted_to=_optional_string(data.get("promoted_to")),
            created_at=_optional_string(data.get("created_at")),
            updated_at=_optional_string(data.get("updated_at")),
            promoted_at=_optional_string(data.get("promoted_at")),
            discarded_at=discarded_at,
            last_switched_at=_optional_string(data.get("last_switched_at")),
            title=_string(data.get("title")),
            description=_string(data.get("description")),
            status=status,
            checkpoint_ids=_string_tuple(data.get("checkpoint_ids")),
            owned_paths=_normalize_owned_paths(_string_tuple(data.get("owned_paths"))),
            allow_owned_path_overlap_with=_string_tuple(data.get("allow_owned_path_overlap_with")),
        )

    def to_domain_record(self) -> DomainLineageRecord:
        return DomainLineageRecord(
            schema_version=self.schema_version,
            lineage_id=self.lineage_id,
            head_revision=self.head_revision,
            forked_from=self.forked_from,
            promoted_from=self.promoted_from,
            created_at=self.created_at,
            updated_at=self.updated_at,
            title=self.title,
            description=self.description,
            checkpoint_ids=self.checkpoint_ids,
        )


@dataclass(frozen=True, slots=True)
class ReservationConflict:
    requested_lineage_id: str
    existing_lineage_id: str
    requested_path: str
    existing_path: str


@dataclass(frozen=True, slots=True)
class PromotionConflict:
    conflict_type: PromotionConflictType
    path: str | None = None
    related_lineage_id: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PromotionPreview:
    source_lineage_id: str
    destination_lineage_id: str
    base_checkpoint_id: str | None = None
    baseline_revision: str | None = None
    source_head_revision: str | None = None
    destination_head_revision: str | None = None
    source_changed_paths: tuple[str, ...] = ()
    destination_changed_paths: tuple[str, ...] = ()
    conflicts: tuple[PromotionConflict, ...] = ()

    @property
    def can_promote(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True, slots=True)
class PromotionResult:
    source: ManagedLineage
    destination: ManagedLineage
    preview: PromotionPreview


class PathReservationError(ValueError):
    def __init__(self, conflicts: tuple[ReservationConflict, ...]) -> None:
        self.conflicts = conflicts
        detail = ", ".join(
            f"{conflict.requested_path} overlaps {conflict.existing_lineage_id}:{conflict.existing_path}"
            for conflict in conflicts
        )
        super().__init__(f"owned paths are already reserved: {detail}")


class PromotionConflictError(ValueError):
    def __init__(self, preview: PromotionPreview) -> None:
        self.preview = preview
        detail = ", ".join(
            conflict.path or conflict.conflict_type.value for conflict in preview.conflicts
        )
        super().__init__(
            f"cannot promote {preview.source_lineage_id} into {preview.destination_lineage_id}: {detail}"
        )


def list_lineage_records(layout: LitLayout) -> tuple[ManagedLineage, ...]:
    records = [
        ManagedLineage.from_dict(read_json(path, default=None))
        for path in sorted(layout.lineages.glob("*.json"))
    ]
    records.sort(key=lambda record: (record.created_at or "", record.lineage_id))
    return tuple(records)


def load_lineage_record(layout: LitLayout, lineage_id: str) -> ManagedLineage:
    normalized = normalize_branch_name(lineage_id)
    path = layout.lineage_path(normalized)
    if not path.exists():
        raise FileNotFoundError(f"lineage not found: {normalized}")
    return ManagedLineage.from_dict(read_json(path, default=None))


def write_lineage_record(
    layout: LitLayout,
    record: ManagedLineage,
    *,
    mutation: FileMutationWriter | None = None,
) -> None:
    write_json(layout.lineage_path(record.lineage_id), record.to_dict(), mutation=mutation)


def upsert_lineage_record(
    layout: LitLayout,
    lineage_id: str,
    *,
    head_revision: str | None = None,
    base_checkpoint_id: str | None = None,
    forked_from: str | None = None,
    promoted_from: str | None = None,
    promoted_to: str | None = None,
    promoted_at: str | None = None,
    discarded_at: str | None = None,
    last_switched_at: str | None = None,
    checkpoint_id: str | None = None,
    checkpoint_ids: tuple[str, ...] | None = None,
    owned_paths: tuple[str, ...] | None = None,
    allow_owned_path_overlap_with: tuple[str, ...] | None = None,
    status: LineageStatus | None = None,
    title: str | None = None,
    description: str | None = None,
    mutation: FileMutationWriter | None = None,
) -> ManagedLineage:
    normalized = normalize_branch_name(lineage_id)
    path = layout.lineage_path(normalized)
    now = utc_now()
    existing = (
        ManagedLineage.from_dict(read_json(path, default=None))
        if path.exists()
        else ManagedLineage(
            lineage_id=normalized,
            created_at=now,
            updated_at=now,
            title=title or normalized,
            description=description or "",
        )
    )
    updated = ManagedLineage(
        schema_version=existing.schema_version,
        lineage_id=normalized,
        head_revision=existing.head_revision if head_revision is None else head_revision,
        base_checkpoint_id=existing.base_checkpoint_id if base_checkpoint_id is None else base_checkpoint_id,
        forked_from=existing.forked_from or forked_from,
        promoted_from=existing.promoted_from if promoted_from is None else promoted_from,
        promoted_to=existing.promoted_to if promoted_to is None else promoted_to,
        created_at=existing.created_at or now,
        updated_at=now,
        promoted_at=existing.promoted_at if promoted_at is None else promoted_at,
        discarded_at=existing.discarded_at if discarded_at is None else discarded_at,
        last_switched_at=existing.last_switched_at if last_switched_at is None else last_switched_at,
        title=existing.title if title is None else title,
        description=existing.description if description is None else description,
        status=existing.status if status is None else status,
        checkpoint_ids=(
            _append_unique(
                existing.checkpoint_ids,
                () if checkpoint_id is None else (checkpoint_id,),
            )
            if checkpoint_ids is None
            else _append_unique((), checkpoint_ids)
        ),
        owned_paths=existing.owned_paths if owned_paths is None else _normalize_owned_paths(owned_paths),
        allow_owned_path_overlap_with=(
            existing.allow_owned_path_overlap_with
            if allow_owned_path_overlap_with is None
            else _string_tuple(allow_owned_path_overlap_with)
        ),
    )
    write_lineage_record(layout, updated, mutation=mutation)
    return updated


class LineageService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.layout = LitLayout(self.root)

    @classmethod
    def open(cls, root: str | Path) -> "LineageService":
        from lit.repository import Repository

        Repository.open(root)
        return cls(root)

    def list_lineages(self, *, include_inactive: bool = True) -> tuple[ManagedLineage, ...]:
        records = list_lineage_records(self.layout)
        if include_inactive:
            return records
        return tuple(record for record in records if record.status is LineageStatus.ACTIVE)

    def get_lineage(self, lineage_id: str) -> ManagedLineage:
        return load_lineage_record(self.layout, lineage_id)

    def create_lineage(
        self,
        lineage_id: str,
        *,
        forked_from: str | None = None,
        base_checkpoint_id: str | None = None,
        owned_paths: tuple[str | Path, ...] = (),
        allow_owned_path_overlap_with: tuple[str, ...] = (),
        title: str = "",
        description: str = "",
    ) -> ManagedLineage:
        from lit.repository import Repository

        repo = Repository.open(self.root)
        normalized = normalize_branch_name(lineage_id)
        if self.layout.lineage_path(normalized).exists() or self.layout.branch_path(normalized).exists():
            raise ValueError(f"lineage already exists: {normalized}")
        resolved_head = repo.resolve_revision(forked_from or "HEAD")
        resolved_base_checkpoint = self._resolve_base_checkpoint(
            repo,
            forked_from=forked_from,
            base_checkpoint_id=base_checkpoint_id,
        )
        normalized_owned_paths = _normalize_owned_paths(owned_paths)
        allow_overlap = _string_tuple(allow_owned_path_overlap_with)
        conflicts = self._reservation_conflicts(
            requested_lineage_id=normalized,
            owned_paths=normalized_owned_paths,
            allow_owned_path_overlap_with=allow_overlap,
        )
        if conflicts:
            raise PathReservationError(conflicts)

        now = utc_now()
        record = ManagedLineage(
            lineage_id=normalized,
            head_revision=resolved_head,
            base_checkpoint_id=resolved_base_checkpoint,
            forked_from=forked_from or repo.current_branch_name(),
            created_at=now,
            updated_at=now,
            title=title or normalized,
            description=description,
            status=LineageStatus.ACTIVE,
            checkpoint_ids=() if resolved_base_checkpoint is None else (resolved_base_checkpoint,),
            owned_paths=normalized_owned_paths,
            allow_owned_path_overlap_with=allow_overlap,
        )
        with JournaledTransaction(self.layout, kind="create-lineage", message=f"create lineage {normalized}") as tx:
            write_ref(self.layout.branch_path(normalized), resolved_head, mutation=tx)
            write_lineage_record(self.layout, record, mutation=tx)
        return record

    def switch_lineage(self, lineage_id: str) -> ManagedLineage:
        from lit.repository import Repository

        record = self.get_lineage(lineage_id)
        if record.status is not LineageStatus.ACTIVE:
            raise ValueError(f"cannot switch to {record.status.value} lineage: {record.lineage_id}")
        with JournaledTransaction(self.layout, kind="switch-lineage", message=f"switch lineage {record.lineage_id}") as tx:
            write_ref(self.layout.branch_path(record.lineage_id), record.head_revision, mutation=tx)
        repo = Repository.open(self.root)
        repo.checkout(record.lineage_id)
        return upsert_lineage_record(
            self.layout,
            record.lineage_id,
            head_revision=record.head_revision,
            last_switched_at=utc_now(),
        )

    def preview_promotion_conflicts(
        self,
        lineage_id: str,
        destination_lineage_id: str | None = None,
    ) -> PromotionPreview:
        repo = self._repository()
        source = self.get_lineage(lineage_id)
        destination_id = normalize_branch_name(
            destination_lineage_id or repo.current_branch_name() or repo.config.default_branch
        )
        destination = self.get_lineage(destination_id)
        baseline_revision = self._baseline_revision(repo, source, destination)
        source_changed_paths = self._changed_paths(repo, baseline_revision, source.head_revision)
        destination_changed_paths = self._changed_paths(repo, baseline_revision, destination.head_revision)
        paths_under_promotion = source_changed_paths or source.owned_paths

        conflicts: dict[tuple[str, str | None, str | None], PromotionConflict] = {}

        if source.status is not LineageStatus.ACTIVE:
            conflicts[(PromotionConflictType.INACTIVE_SOURCE.value, None, source.lineage_id)] = PromotionConflict(
                conflict_type=PromotionConflictType.INACTIVE_SOURCE,
                related_lineage_id=source.lineage_id,
                detail=f"source lineage is {source.status.value}",
            )
        if destination.status is LineageStatus.DISCARDED:
            conflicts[(PromotionConflictType.INACTIVE_DESTINATION.value, None, destination.lineage_id)] = PromotionConflict(
                conflict_type=PromotionConflictType.INACTIVE_DESTINATION,
                related_lineage_id=destination.lineage_id,
                detail="destination lineage is discarded",
            )

        for path in source_changed_paths:
            if source.owned_paths and not _path_within_scopes(path, source.owned_paths):
                conflicts[(PromotionConflictType.OWNERSHIP_VIOLATION.value, path, None)] = PromotionConflict(
                    conflict_type=PromotionConflictType.OWNERSHIP_VIOLATION,
                    path=path,
                    detail="source changed a path outside its owned reservation",
                )

        for path in sorted(set(source_changed_paths) & set(destination_changed_paths)):
            conflicts[(PromotionConflictType.DESTINATION_CHANGED.value, path, destination.lineage_id)] = PromotionConflict(
                conflict_type=PromotionConflictType.DESTINATION_CHANGED,
                path=path,
                related_lineage_id=destination.lineage_id,
                detail="destination changed the same path after the lineage base checkpoint",
            )

        for other in self.list_lineages(include_inactive=False):
            if other.lineage_id in {source.lineage_id, destination.lineage_id}:
                continue
            if not other.owned_paths:
                continue
            for path in paths_under_promotion:
                if not _path_within_scopes(path, other.owned_paths):
                    continue
                if self._overlap_allowed(source, other) or self._overlap_allowed(destination, other):
                    continue
                conflicts[(PromotionConflictType.RESERVED_BY_LINEAGE.value, path, other.lineage_id)] = PromotionConflict(
                    conflict_type=PromotionConflictType.RESERVED_BY_LINEAGE,
                    path=path,
                    related_lineage_id=other.lineage_id,
                    detail="path is reserved by another active lineage",
                )

        return PromotionPreview(
            source_lineage_id=source.lineage_id,
            destination_lineage_id=destination.lineage_id,
            base_checkpoint_id=source.base_checkpoint_id,
            baseline_revision=baseline_revision,
            source_head_revision=source.head_revision,
            destination_head_revision=destination.head_revision,
            source_changed_paths=source_changed_paths,
            destination_changed_paths=destination_changed_paths,
            conflicts=tuple(conflicts.values()),
        )

    def promote_lineage(
        self,
        lineage_id: str,
        *,
        destination_lineage_id: str | None = None,
        expected_head_revision: str | None = None,
        allow_conflicts: bool = False,
    ) -> PromotionResult:
        source = self.get_lineage(lineage_id)
        if expected_head_revision is not None and source.head_revision != expected_head_revision:
            raise ValueError(
                f"lineage {source.lineage_id} moved to {source.head_revision}; expected {expected_head_revision}"
            )
        preview = self.preview_promotion_conflicts(source.lineage_id, destination_lineage_id)
        if preview.conflicts and not allow_conflicts:
            raise PromotionConflictError(preview)

        destination = self.get_lineage(preview.destination_lineage_id)
        now = utc_now()
        updated_source = ManagedLineage(
            schema_version=source.schema_version,
            lineage_id=source.lineage_id,
            head_revision=source.head_revision,
            base_checkpoint_id=source.base_checkpoint_id,
            forked_from=source.forked_from,
            promoted_from=source.promoted_from,
            promoted_to=destination.lineage_id,
            created_at=source.created_at,
            updated_at=now,
            promoted_at=now,
            discarded_at=source.discarded_at,
            last_switched_at=source.last_switched_at,
            title=source.title,
            description=source.description,
            status=LineageStatus.PROMOTED,
            checkpoint_ids=source.checkpoint_ids,
            owned_paths=source.owned_paths,
            allow_owned_path_overlap_with=source.allow_owned_path_overlap_with,
        )
        updated_destination = ManagedLineage(
            schema_version=destination.schema_version,
            lineage_id=destination.lineage_id,
            head_revision=source.head_revision,
            base_checkpoint_id=destination.base_checkpoint_id or source.base_checkpoint_id,
            forked_from=destination.forked_from,
            promoted_from=source.lineage_id,
            promoted_to=destination.promoted_to,
            created_at=destination.created_at,
            updated_at=now,
            promoted_at=destination.promoted_at,
            discarded_at=destination.discarded_at,
            last_switched_at=destination.last_switched_at,
            title=destination.title,
            description=destination.description,
            status=destination.status,
            checkpoint_ids=_append_unique(destination.checkpoint_ids, source.checkpoint_ids),
            owned_paths=_append_unique(destination.owned_paths, source.owned_paths),
            allow_owned_path_overlap_with=_append_unique(
                destination.allow_owned_path_overlap_with,
                source.allow_owned_path_overlap_with,
            ),
        )
        with JournaledTransaction(
            self.layout,
            kind="promote-lineage",
            message=f"promote {source.lineage_id} to {destination.lineage_id}",
        ) as tx:
            write_lineage_record(self.layout, updated_source, mutation=tx)
            write_lineage_record(self.layout, updated_destination, mutation=tx)
            write_ref(
                self.layout.branch_path(destination.lineage_id),
                source.head_revision,
                mutation=tx,
            )
        return PromotionResult(source=updated_source, destination=updated_destination, preview=preview)

    def discard_lineage(self, lineage_id: str) -> ManagedLineage:
        record = self.get_lineage(lineage_id)
        current = self._repository().current_branch_name()
        if current == record.lineage_id:
            raise ValueError(f"cannot discard the current lineage: {record.lineage_id}")
        now = utc_now()
        updated = ManagedLineage(
            schema_version=record.schema_version,
            lineage_id=record.lineage_id,
            head_revision=record.head_revision,
            base_checkpoint_id=record.base_checkpoint_id,
            forked_from=record.forked_from,
            promoted_from=record.promoted_from,
            promoted_to=record.promoted_to,
            created_at=record.created_at,
            updated_at=now,
            promoted_at=record.promoted_at,
            discarded_at=now,
            last_switched_at=record.last_switched_at,
            title=record.title,
            description=record.description,
            status=LineageStatus.DISCARDED,
            checkpoint_ids=record.checkpoint_ids,
            owned_paths=record.owned_paths,
            allow_owned_path_overlap_with=record.allow_owned_path_overlap_with,
        )
        with JournaledTransaction(self.layout, kind="discard-lineage", message=f"discard {record.lineage_id}") as tx:
            write_lineage_record(self.layout, updated, mutation=tx)
            delete_ref(self.layout.branch_path(record.lineage_id), mutation=tx)
        return updated

    def _repository(self) -> "Repository":
        from lit.repository import Repository

        return Repository.open(self.root)

    def _resolve_base_checkpoint(
        self,
        repo: "Repository",
        *,
        forked_from: str | None,
        base_checkpoint_id: str | None,
    ) -> str | None:
        if base_checkpoint_id is not None:
            repo.get_checkpoint(base_checkpoint_id)
            return base_checkpoint_id
        if forked_from is not None and self.layout.checkpoint_path(forked_from).exists():
            repo.get_checkpoint(forked_from)
            return forked_from
        lineage_id = repo.resolve_branch_name(forked_from) if forked_from is not None else repo.current_branch_name()
        if lineage_id is not None:
            checkpoint_id = repo.latest_safe_checkpoint_id(lineage_id=lineage_id)
            if checkpoint_id is not None:
                return checkpoint_id
            lineage_checkpoints = repo.list_checkpoints(lineage_id=lineage_id)
            if lineage_checkpoints:
                return lineage_checkpoints[-1].checkpoint_id
        checkpoint_id = repo.latest_safe_checkpoint_id()
        if checkpoint_id is not None:
            return checkpoint_id
        checkpoints = repo.list_checkpoints()
        return None if not checkpoints else checkpoints[-1].checkpoint_id

    def _reservation_conflicts(
        self,
        *,
        requested_lineage_id: str,
        owned_paths: tuple[str, ...],
        allow_owned_path_overlap_with: tuple[str, ...],
    ) -> tuple[ReservationConflict, ...]:
        conflicts: list[ReservationConflict] = []
        allow_overlap = set(allow_owned_path_overlap_with)
        for existing in self.list_lineages(include_inactive=False):
            if existing.lineage_id == requested_lineage_id:
                continue
            for requested_path in owned_paths:
                for existing_path in existing.owned_paths:
                    if not _path_overlap(requested_path, existing_path):
                        continue
                    if existing.lineage_id in allow_overlap or requested_lineage_id in existing.allow_owned_path_overlap_with:
                        continue
                    conflicts.append(
                        ReservationConflict(
                            requested_lineage_id=requested_lineage_id,
                            existing_lineage_id=existing.lineage_id,
                            requested_path=requested_path,
                            existing_path=existing_path,
                        )
                    )
        return tuple(conflicts)

    def _overlap_allowed(self, left: ManagedLineage, right: ManagedLineage) -> bool:
        return left.allows_overlap_with(right.lineage_id) or right.allows_overlap_with(left.lineage_id)

    def _baseline_revision(
        self,
        repo: "Repository",
        source: ManagedLineage,
        destination: ManagedLineage,
    ) -> str | None:
        for checkpoint_id in (source.base_checkpoint_id, destination.base_checkpoint_id):
            if checkpoint_id is None:
                continue
            try:
                checkpoint = repo.get_checkpoint(checkpoint_id)
            except FileNotFoundError:
                continue
            return checkpoint.revision_id
        return repo.merge_base(source.head_revision, destination.head_revision)

    def _changed_paths(
        self,
        repo: "Repository",
        before_revision: str | None,
        after_revision: str | None,
    ) -> tuple[str, ...]:
        before = {} if before_revision is None else repo.read_commit_tree(before_revision)
        after = {} if after_revision is None else repo.read_commit_tree(after_revision)
        changed: list[str] = []
        for path in sorted(set(before) | set(after)):
            left = before.get(path)
            right = after.get(path)
            if self._tracked_file_equal(left, right):
                continue
            changed.append(path)
        return tuple(changed)

    def _tracked_file_equal(
        self,
        left: "TrackedFile | None",
        right: "TrackedFile | None",
    ) -> bool:
        if left is None or right is None:
            return left is right
        return left.digest == right.digest and left.executable == right.executable


__all__ = [
    "LineageService",
    "LineageStatus",
    "ManagedLineage",
    "PathReservationError",
    "PromotionConflict",
    "PromotionConflictError",
    "PromotionConflictType",
    "PromotionPreview",
    "PromotionResult",
    "ReservationConflict",
    "list_lineage_records",
    "load_lineage_record",
    "normalize_owned_path",
    "upsert_lineage_record",
    "write_lineage_record",
]
