# lit v1 product design

## Product identity

`lit` is a local execution VCS for long-running autonomous coding workflows on one machine.

It is not a local Git clone. Git-like verbs remain only where they reduce operator friction for local work.

The primary user is Jakal Flow or a human supervising local autonomous agents. The core product promises are:

1. human-controlled autonomy
2. complete rollback
3. structured multi-agent provenance
4. safe validated checkpoints
5. parallel lineage isolation and promotion
6. local-first artifact and state management
7. installable CLI and desktop UI

## Backend boundary

`src/lit/backend_api.py` is the product seam shared by the CLI, desktop UI, export bridge, and future Jakal Flow adapters.

Clients should rely on:

- repository state handles
- revision, checkpoint, lineage, verification, artifact, and operation records
- service methods for checkpointing, rollback, verification, lineage management, doctor, and export

Clients should not hardcode `.lit` layout paths or invent parallel metadata formats.

## Shipped CLI surface

The v1 CLI keeps the earlier local authoring commands and adds release-grade inspection and orchestration surfaces:

- `lit checkpoint`
- `lit rollback`
- `lit verify`
- `lit lineage`
- `lit artifact`
- `lit gc`
- `lit doctor`
- `lit export`

Inspection-oriented commands support `--json` so Jakal Flow or local wrappers can consume the same backend state without screen-scraping human output.

## Shipped desktop UI surface

The desktop shell remains a three-pane client over the same backend and keeps the rule that views only communicate through the session/backend boundary.

The v1 shell surfaces:

- repository health and artifact usage on Home
- checkpoint timeline, provenance, and verification on History
- lineage state, promotion preview, rollback anchors, and conflict review on Branches

## Git interoperability

Git is a bridge target, not the source-of-truth model.

`lit export` exists so operators can project local history onto Git-facing refs and provenance trailers when needed. That bridge does not imply:

- remote support
- network workflows
- Git object parity
- Git conflict UX parity

## Packaging

The base package installs the CLI without forcing desktop dependencies.

The GUI dependency is optional through the `gui` extra so headless automation stays lightweight while `lit-gui` remains available when the extra is installed.
