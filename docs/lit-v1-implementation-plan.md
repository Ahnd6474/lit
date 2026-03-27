# lit v1 implementation plan

This step freezes the shared v1 vocabulary before broader repository, CLI, GUI, and Jakal Flow refactors start.

## Contract boundary

- `src/lit/domain.py` is the canonical record surface for revisions, checkpoints, lineages, verification, artifacts, and operations.
- `src/lit/layout.py` is the only place that should define canonical `.lit` paths for v1 records, journals, locks, and artifact storage.
- `src/lit/backend_api.py` is the narrow service boundary that higher-level clients should target instead of importing storage paths or repository internals directly.

## Compatibility rules

- V1 readers must accept legacy v0 commit JSON and absent fields.
- Existing repository behavior stays in place until later steps migrate engine code onto the frozen contracts.
- New metadata keys should be added through these versioned records, not ad hoc dict writes in CLI, GUI, or adapters.

## Follow-on work

1. Migrate repository persistence from ad hoc commit metadata to the frozen revision and checkpoint contracts.
2. Route storage callers through `LitLayout` so `.lit` path decisions live in one place.
3. Implement a concrete backend service that serves CLI, desktop UI, export, verification, rollback, and lineage workflows from the same API.
