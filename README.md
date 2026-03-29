# lit

`lit` is a **local-first version control project** that now has two parallel goals:

1. A practical Git-like local VCS CLI for everyday offline checkpointing.
2. A v1 foundation for richer local workflow records (revisions, checkpoints, lineages, verifications, artifacts, and operations) that both CLI and GUI can share.

The previous README focused mainly on the original CLI prototype. This version reflects the project's broader current direction and implementation status.

---

## Current Project Status (March 2026)

### Overall maturity

- **CLI local VCS workflow is implemented and test-covered** for init/add/commit/log/status/diff/restore/checkout/branch/merge/rebase.
- **Desktop GUI MVP is implemented** with PySide6 and covers Home/Changes/History/Branches/Files flows on top of the same local repository model.
- **v1 domain contracts are in place** for autonomous/local workflow metadata (revision/checkpoint/lineage/verification/artifact/operation records).
- **Migration is in progress** from legacy ad-hoc commit metadata and storage paths to the newer v1 contract/layout boundary.

In short: the project is no longer just a tiny CLI toy; it is now an evolving local workflow platform with both CLI and GUI clients.

### What is already working

- Local repository initialization and object storage under `.lit`.
- Staging and committing snapshots.
- Status and diff inspection for local working tree changes.
- Local branch creation/listing and checkout.
- Local merge and rebase with conflict marker writing + abort flows.
- Restore of tracked paths from a source revision.
- GUI operations for staging, commit creation, history browsing, branch operations, restore, and merge/rebase entry points.

### Current Limitations

- No remote or network workflows (`push`/`pull`/`fetch`/`clone` are out of scope).
- Merge/rebase behavior is real but intentionally simplified.
- Conflict resolution is manual (no built-in interactive conflict resolver).
- Some v1 contract surfaces are available before every engine/storage caller is fully migrated.

---

## Project Direction

`lit` is intentionally **offline and local-only**. The design target is dependable single-machine workflows with richer local provenance and operation records, not team sync infrastructure.

### Core architectural boundaries (active direction)

- `src/lit/domain.py` defines canonical v1 records and serialization compatibility behavior.
- `src/lit/layout.py` centralizes canonical `.lit` directory/file layout decisions.
- `src/lit/backend_api.py` defines a narrower backend service boundary so higher layers don't hardcode repository internals.
- `src/lit_gui/` is a thin GUI shell that renders immutable session DTO snapshots and calls session/backend boundaries.

This architecture is aimed at keeping CLI/GUI/export/future adapters consistent as the project grows.

---

## Feature Matrix

| Area | Status | Notes |
| --- | --- | --- |
| Local init/add/commit/log/status/diff | ✅ Implemented | Core local workflow commands exist and are tested. |
| Restore/checkout/branch | ✅ Implemented | Local branch & revision navigation is available. |
| Merge/rebase + abort | ✅ Implemented (simplified) | Conflicts write markers; user resolves manually or aborts. |
| Desktop GUI MVP | ✅ Implemented | Home, Changes, History, Branches, Files views. |
| v1 contracts (`domain.py`) | ✅ Introduced | Canonical typed records for revision/checkpoint/lineage/etc. |
| Canonical layout (`layout.py`) | ✅ Introduced | Centralized `.lit` path model for legacy + v1 surfaces. |
| Full backend migration to v1 | 🚧 In progress | Some legacy behaviors remain while migration continues. |
| Remote/team collaboration | ❌ Non-goal | Project remains local-only by design. |

---

## Installation

`lit` targets **Python 3.12+**.

From repo root:

```bash
python -m pip install -e .
```

CLI entry points:

```bash
lit --help
```

GUI entry points:

```bash
lit-gui
# or
python -m lit_gui.app
```

---

## Quick Start (CLI)

```bash
mkdir demo
cd demo
lit init
printf "hello\n" > note.txt
lit add note.txt
lit commit -m "Create first checkpoint"
lit status
lit log
```

---

## Command Overview

| Command | Purpose |
| --- | --- |
| `lit init [path]` | Create a `.lit` repository. |
| `lit add <paths...>` | Stage files or directories. |
| `lit commit -m "message"` | Write the staged snapshot as a commit. |
| `lit status` | Show staged, modified, deleted, and untracked files. |
| `lit diff` | Show the working tree diff against the current commit. |
| `lit log` | Show first-parent commit history from `HEAD`. |
| `lit restore [paths...] --source <rev>` | Restore tracked files from a revision without moving `HEAD`. |
| `lit checkout <branch-or-commit>` | Switch branches or detach `HEAD` at a commit. |
| `lit branch [name] [--start-point <rev>]` | List branches or create a new branch. |
| `lit merge <rev>` | Merge another local revision into the current branch. |
| `lit merge --abort` | Clear merge state and restore the pre-merge tree. |
| `lit rebase <rev>` | Rebase the current branch onto another local revision. |
| `lit rebase --abort` | Clear rebase state and restore the original branch tip. |

---

## GUI MVP Scope

After installing editable package (`pip install -e .`), run `lit-gui`.

The GUI currently supports:

1. Open/initialize local repository folders.
2. Stage files and create commits from Changes.
3. Inspect commit timeline and per-file diffs from History.
4. Create/switch branches, restore paths, and start merge/rebase from Branches.
5. Review operation/conflict state in sidebar + right detail panel.

GUI tests run in CI/local without a full desktop runtime by using a narrow fake `PySide6` module in tests.

---

## Testing

Run the full repository test suite:

```bash
python -m pytest
```

Test directories to know:

- `tests/` for CLI/backend coverage.
- `tests/gui/backend/` for repository session shaping and operation-state behavior.
- `tests/gui/views/` for view-level shell wiring and workflows.

---

## Non-Goals

`lit` intentionally does **not** aim to be a Git replacement for distributed team collaboration.

- No hosted remotes.
- No background sync.
- No account/auth model.
- No cross-machine collaboration pipeline.

If you need those capabilities, use Git.

---

## Developer Notes

- The v1 contract freeze and migration intent are described in `docs/lit-v1-implementation-plan.md`.
- GUI layering and session boundary details are described in `docs/gui-architecture.md`.
- A browser-friendly static project page is available at `website/index.html`.
