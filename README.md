# lit

`lit` is a local execution VCS for autonomous coding workflows on one machine. It is local-only and offline-first, but it is not a local Git clone.

The v1 product is aimed at long-running local agent work and the future Jakal Flow repository backend. Its core surfaces are safe checkpoints, complete rollback, structured provenance, verification-aware history, lineage isolation, local artifact management, an installable CLI, and a desktop UI.

## What lit Does

- Initializes a repository inside any local folder with `lit init`.
- Stages files and directories with `lit add`.
- Creates local revisions with `lit commit -m`.
- Creates safe checkpoints with `lit checkpoint create`.
- Rolls back to the latest safe checkpoint or a selected checkpoint with `lit rollback`.
- Records or replays verification with `lit verify`.
- Isolates parallel local work with `lit lineage`.
- Tracks local artifact manifests, usage, and garbage collection with `lit artifact` and `lit gc`.
- Inspects repository health with `lit doctor`.
- Builds a Git-facing export plan with `lit export`.
- Still supports familiar local `lit branch`, `lit checkout`, `lit merge`, and `lit rebase` workflows.

## Local-Only Design

`lit` is intentionally local-only and offline-only.

- No remote repositories
- No `push`, `pull`, `fetch`, or `clone`
- No accounts, login, sync, or cloud service
- No team collaboration workflow
- No background daemon or server

If you need multi-machine sync or shared collaboration, use Git instead.

## Installation

`lit` targets Python 3.12+.

Base CLI install:

```bash
python -m pip install -e .
```

If the `lit` script directory is not on your `PATH`, use `python -m lit ...` instead of `lit ...`.

Optional desktop GUI install:

```bash
python -m pip install -e .[gui]
```

That installs the `lit` console command. The GUI entrypoint is `lit-gui` when the optional GUI dependency is installed.

## Quick Start

```bash
mkdir demo
cd demo
lit init
python -c "from pathlib import Path; Path('note.txt').write_text('hello\\n', encoding='utf-8')"
lit add note.txt
lit commit -m "Create first checkpoint"
lit checkpoint create --name safe-start
lit status
lit log
lit doctor
```

## Release Surface

### CLI

```bash
lit checkpoint list
lit rollback
lit verify status
lit lineage list
lit artifact usage
lit gc --dry-run
lit export --json
```

Most inspection workflows support `--json` for machine-readable output.

### Desktop GUI

After `python -m pip install -e .[gui]`, launch the desktop app with either command:

```bash
lit-gui
# or
python -m lit_gui.app
```

If `PySide6` is not installed, the desktop entrypoint will fail until the optional `gui` extra is installed.

The desktop shell uses the same backend records as the CLI and exposes:

- checkpoint timeline and rollback anchors
- commit provenance and verification state
- lineage state and promotion preview
- conflict review for merge and rebase
- artifact usage and repository health

## Git Bridge, Not Git Parity

`lit` keeps some Git-like commands for familiarity, but Git parity is not the goal.

Similar to Git:

- snapshot-based local commits
- an index/staging area before commit
- local branch, merge, checkout, and rebase workflows
- detached `HEAD` when checking out a commit directly

Different from Git:

- `lit` centers safe checkpoints, rollback, provenance, verification, and lineage isolation
- `lit export` produces a Git-facing plan; it does not turn `lit` into Git
- there are no remotes and no `push`, `pull`, `fetch`, or `clone`
- conflict handling is intentionally local and explicit

## Jakal Flow Path

`lit` is intended to be a credible future backend for Jakal Flow:

- planner and executor runs can record lineage, block, step, and run provenance
- verification results are attached to revision and checkpoint boundaries
- lineages provide isolated parallel worker lanes with promotion review
- safe checkpoints provide the canonical last-known-good rollback target

## Verification

Run the repository test suite locally with:

```bash
python -m pytest
```

You can also configure repository verification commands and record them with `lit verify run`.

The closeout pass verified:

- `python -m pytest`
- `python -m pip install -e .`
- `python -m lit --help`

## Current Limitations

- `lit export` is a Git interoperability bridge, not a full Git transport or object-compatibility layer.
- Conflict handling is manual: `lit` writes markers and preserves state, but it does not provide an interactive resolver.
- The desktop UI exposes verified repository state, but it still favors a narrow local workflow over a full IDE.
- On-disk formats are versioned and backward compatible with legacy commit metadata, but v1 remains intentionally scoped to one-machine execution workflows.

## Non-Goals

- Remote hosting
- `push`, `pull`, `fetch`, or `clone`
- Authentication, user accounts, or permissions
- Multi-user collaboration
- Cloud backup or sync
- Full Git compatibility

To open the static local website, open `website/index.html` in a browser.
