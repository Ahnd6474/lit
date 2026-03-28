from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from lit.domain import ArtifactRecord
from lit.storage import hash_bytes
from lit.transactions import next_identifier, utc_now

ARTIFACTS_SCHEMA_VERSION = 1
CONTENT_ADDRESS_ALGORITHM = "sha256"
DEFAULT_ARTIFACT_HOME_ENV = "LIT_ARTIFACT_HOME"

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _string(value: object | None, *, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: object | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Path)):
        return (str(value),)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def normalize_artifact_relative_path(path: str | Path | None) -> str:
    if path in (None, "", "."):
        return ""
    value = str(path).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


def validate_digest(digest: str) -> str:
    lowered = digest.lower()
    if not _DIGEST_PATTERN.fullmatch(lowered):
        raise ValueError(f"invalid sha256 digest: {digest}")
    return lowered


def split_content_address(address: str) -> tuple[str, str]:
    if ":" in address:
        algorithm, digest = address.split(":", 1)
    else:
        algorithm, digest = CONTENT_ADDRESS_ALGORITHM, address
    normalized_algorithm = algorithm.strip().lower()
    if normalized_algorithm != CONTENT_ADDRESS_ALGORITHM:
        raise ValueError(f"unsupported artifact address algorithm: {algorithm}")
    return normalized_algorithm, validate_digest(digest.strip())


def content_address_for_digest(digest: str, *, algorithm: str = CONTENT_ADDRESS_ALGORITHM) -> str:
    normalized_algorithm = algorithm.strip().lower()
    if normalized_algorithm != CONTENT_ADDRESS_ALGORITHM:
        raise ValueError(f"unsupported artifact address algorithm: {algorithm}")
    return f"{normalized_algorithm}:{validate_digest(digest)}"


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    algorithm: str = CONTENT_ADDRESS_ALGORITHM
    digest: str = ""
    size_bytes: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm", self.algorithm.strip().lower())
        if self.algorithm != CONTENT_ADDRESS_ALGORITHM:
            raise ValueError(f"unsupported artifact address algorithm: {self.algorithm}")
        object.__setattr__(self, "digest", validate_digest(self.digest))
        if self.size_bytes < 0:
            raise ValueError("artifact size cannot be negative")

    @property
    def content_address(self) -> str:
        return content_address_for_digest(self.digest, algorithm=self.algorithm)

    @classmethod
    def from_bytes(cls, data: bytes) -> "ArtifactReference":
        return cls(digest=hash_bytes(data), size_bytes=len(data))

    @classmethod
    def from_address(
        cls,
        address: str,
        *,
        size_bytes: int,
    ) -> "ArtifactReference":
        algorithm, digest = split_content_address(address)
        return cls(algorithm=algorithm, digest=digest, size_bytes=size_bytes)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactReference | None":
        if not data:
            return None
        address = _optional_string(data.get("content_address"))
        if address is not None:
            return cls.from_address(address, size_bytes=int(data.get("size_bytes", 0)))
        return cls(
            algorithm=_string(data.get("algorithm"), default=CONTENT_ADDRESS_ALGORITHM),
            digest=_string(data.get("digest")),
            size_bytes=int(data.get("size_bytes", 0)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "content_address": self.content_address,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ArtifactLink:
    owner_kind: str
    owner_id: str
    relationship: str = "attached"
    note: str | None = None
    linked_at: str | None = None

    def __post_init__(self) -> None:
        if not self.owner_kind:
            raise ValueError("artifact links require an owner kind")
        if not self.owner_id:
            raise ValueError("artifact links require an owner identifier")

    @classmethod
    def owner(
        cls,
        owner_kind: str,
        owner_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls(
            owner_kind=owner_kind,
            owner_id=owner_id,
            relationship=relationship,
            note=note,
            linked_at=utc_now(),
        )

    @classmethod
    def revision(
        cls,
        revision_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls.owner(
            "revision",
            revision_id,
            relationship=relationship,
            note=note,
        )

    @classmethod
    def commit(
        cls,
        revision_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls.revision(
            revision_id,
            relationship=relationship,
            note=note,
        )

    @classmethod
    def checkpoint(
        cls,
        checkpoint_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls.owner(
            "checkpoint",
            checkpoint_id,
            relationship=relationship,
            note=note,
        )

    @classmethod
    def lineage(
        cls,
        lineage_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls.owner(
            "lineage",
            lineage_id,
            relationship=relationship,
            note=note,
        )

    @classmethod
    def verification(
        cls,
        verification_id: str,
        *,
        relationship: str = "attached",
        note: str | None = None,
    ) -> "ArtifactLink":
        return cls.owner(
            "verification",
            verification_id,
            relationship=relationship,
            note=note,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactLink | None":
        if not data:
            return None
        owner_kind = _optional_string(data.get("owner_kind"))
        owner_id = _optional_string(data.get("owner_id"))
        if owner_kind is None or owner_id is None:
            return None
        return cls(
            owner_kind=owner_kind,
            owner_id=owner_id,
            relationship=_string(data.get("relationship"), default="attached"),
            note=_optional_string(data.get("note")),
            linked_at=_optional_string(data.get("linked_at")),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "linked_at": self.linked_at,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "relationship": self.relationship,
        }
        if self.note is not None:
            data["note"] = self.note
        return data


@dataclass(frozen=True, slots=True)
class ArtifactPin:
    digest: str
    artifact_id: str | None = None
    owner_kind: str | None = None
    owner_id: str | None = None
    reason: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", validate_digest(self.digest))

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactPin | None":
        if not data:
            return None
        digest = _optional_string(data.get("digest"))
        if digest is None:
            return None
        return cls(
            digest=digest,
            artifact_id=_optional_string(data.get("artifact_id")),
            owner_kind=_optional_string(data.get("owner_kind")),
            owner_id=_optional_string(data.get("owner_id")),
            reason=_optional_string(data.get("reason")),
            created_at=_optional_string(data.get("created_at")),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "created_at": self.created_at,
            "digest": self.digest,
        }
        if self.artifact_id is not None:
            data["artifact_id"] = self.artifact_id
        if self.owner_kind is not None:
            data["owner_kind"] = self.owner_kind
        if self.owner_id is not None:
            data["owner_id"] = self.owner_id
        if self.reason is not None:
            data["reason"] = self.reason
        return data


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    schema_version: int = ARTIFACTS_SCHEMA_VERSION
    artifact_id: str | None = None
    owner_kind: str = "generic"
    owner_id: str | None = None
    kind: str = "generic"
    relative_path: str = ""
    content_type: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None
    pinned: bool = False
    reference: ArtifactReference | None = None
    links: tuple[ArtifactLink, ...] = ()
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            normalize_artifact_relative_path(self.relative_path),
        )
        if self.reference is not None:
            object.__setattr__(self, "digest", self.reference.digest)
            object.__setattr__(self, "size_bytes", self.reference.size_bytes)
        elif self.digest is not None:
            object.__setattr__(self, "digest", validate_digest(self.digest))
        if self.digest is not None and self.size_bytes is None:
            raise ValueError("artifact manifests with digests require a size")
        if self.reference is None and self.digest is not None and self.size_bytes is not None:
            object.__setattr__(
                self,
                "reference",
                ArtifactReference(digest=self.digest, size_bytes=self.size_bytes),
            )
        if self.artifact_id is None and self.reference is not None:
            object.__setattr__(self, "artifact_id", next_identifier("artifact"))
        if self.owner_id is None and self.links:
            object.__setattr__(self, "owner_kind", self.links[0].owner_kind)
            object.__setattr__(self, "owner_id", self.links[0].owner_id)

    @property
    def content_address(self) -> str | None:
        return None if self.reference is None else self.reference.content_address

    @property
    def primary_link(self) -> ArtifactLink | None:
        links = self.all_links
        return None if not links else links[0]

    @property
    def all_links(self) -> tuple[ArtifactLink, ...]:
        if self.links:
            return self.links
        if self.owner_id is None:
            return ()
        return (
            ArtifactLink(
                owner_kind=self.owner_kind,
                owner_id=self.owner_id,
                linked_at=self.created_at,
            ),
        )

    def is_linked_to(self, owner_kind: str, owner_id: str) -> bool:
        return any(
            link.owner_kind == owner_kind and link.owner_id == owner_id
            for link in self.all_links
        )

    def to_record(self) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=self.artifact_id,
            owner_kind=self.owner_kind,
            owner_id=self.owner_id,
            kind=self.kind,
            relative_path=self.relative_path,
            content_type=self.content_type,
            digest=self.digest,
            size_bytes=self.size_bytes,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, object]:
        data = self.to_record().to_dict()
        data["schema_version"] = self.schema_version
        data["pinned"] = self.pinned
        data["labels"] = list(self.labels)
        if self.content_address is not None:
            data["content_address"] = self.content_address
        if self.reference is not None:
            data["reference"] = self.reference.to_dict()
        if self.all_links:
            data["links"] = [link.to_dict() for link in self.all_links]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "ArtifactManifest":
        if not data:
            return cls()
        raw_reference = data.get("reference")
        reference = ArtifactReference.from_dict(
            raw_reference if isinstance(raw_reference, Mapping) else None
        )
        if reference is None:
            digest = _optional_string(data.get("digest"))
            size_bytes = _optional_int(data.get("size_bytes"))
            content_address = _optional_string(data.get("content_address"))
            if content_address is not None and size_bytes is not None:
                reference = ArtifactReference.from_address(
                    content_address,
                    size_bytes=size_bytes,
                )
            elif digest is not None and size_bytes is not None:
                reference = ArtifactReference(digest=digest, size_bytes=size_bytes)
        raw_links = data.get("links")
        links = ()
        if isinstance(raw_links, Iterable) and not isinstance(raw_links, (str, bytes)):
            materialized: list[ArtifactLink] = []
            for item in raw_links:
                if isinstance(item, Mapping):
                    link = ArtifactLink.from_dict(item)
                    if link is not None:
                        materialized.append(link)
            links = tuple(materialized)
        if not links:
            owner_kind = _optional_string(data.get("owner_kind"))
            owner_id = _optional_string(data.get("owner_id"))
            if owner_kind is not None and owner_id is not None:
                links = (
                    ArtifactLink(
                        owner_kind=owner_kind,
                        owner_id=owner_id,
                        linked_at=_optional_string(data.get("created_at")),
                    ),
                )
        return cls(
            schema_version=int(data.get("schema_version", ARTIFACTS_SCHEMA_VERSION)),
            artifact_id=_optional_string(data.get("artifact_id")),
            owner_kind=_string(
                data.get("owner_kind"),
                default=links[0].owner_kind if links else "generic",
            ),
            owner_id=_optional_string(data.get("owner_id"))
            or (links[0].owner_id if links else None),
            kind=_string(data.get("kind"), default="generic"),
            relative_path=_string(data.get("relative_path")),
            content_type=_optional_string(data.get("content_type")),
            digest=_optional_string(data.get("digest")),
            size_bytes=_optional_int(data.get("size_bytes")),
            created_at=_optional_string(data.get("created_at")),
            pinned=bool(data.get("pinned", False)),
            reference=reference,
            links=links,
            labels=_string_tuple(data.get("labels")),
        )

    def with_links(self, *links: ArtifactLink) -> "ArtifactManifest":
        ordered = list(self.all_links)
        seen = {(link.owner_kind, link.owner_id, link.relationship, link.note) for link in ordered}
        for link in links:
            key = (link.owner_kind, link.owner_id, link.relationship, link.note)
            if key not in seen:
                ordered.append(link)
                seen.add(key)
        primary = ordered[0] if ordered else None
        return ArtifactManifest(
            schema_version=self.schema_version,
            artifact_id=self.artifact_id,
            owner_kind=self.owner_kind if primary is None else primary.owner_kind,
            owner_id=self.owner_id if primary is None else primary.owner_id,
            kind=self.kind,
            relative_path=self.relative_path,
            content_type=self.content_type,
            digest=self.digest,
            size_bytes=self.size_bytes,
            created_at=self.created_at,
            pinned=self.pinned,
            reference=self.reference,
            links=tuple(ordered),
            labels=self.labels,
        )

    def with_pinned(self, pinned: bool) -> "ArtifactManifest":
        return ArtifactManifest(
            schema_version=self.schema_version,
            artifact_id=self.artifact_id,
            owner_kind=self.owner_kind,
            owner_id=self.owner_id,
            kind=self.kind,
            relative_path=self.relative_path,
            content_type=self.content_type,
            digest=self.digest,
            size_bytes=self.size_bytes,
            created_at=self.created_at,
            pinned=pinned,
            reference=self.reference,
            links=self.all_links,
            labels=self.labels,
        )


__all__ = [
    "ARTIFACTS_SCHEMA_VERSION",
    "CONTENT_ADDRESS_ALGORITHM",
    "DEFAULT_ARTIFACT_HOME_ENV",
    "ArtifactLink",
    "ArtifactManifest",
    "ArtifactPin",
    "ArtifactReference",
    "content_address_for_digest",
    "normalize_artifact_relative_path",
    "split_content_address",
    "validate_digest",
]
