# lit

`lit` is a local execution VCS for autonomous coding workflows on one machine.

It is local-only, offline-first, and intentionally narrower than Git. Repository data lives inside a deterministic `.lit/` folder, and once `lit` is installed it does not depend on remotes, cloud sync, accounts, or a background service.

## What lit does today

- Core local workflow: `init`, `add`, `commit`, `log`, `status`, `diff`, `restore`, `checkout`, `branch`, `merge`, and `rebase`.
- Safety and workflow control: `checkpoint`, `rollback`, `verify`, `lineage`, `artifact`, `gc`, `doctor`, and `export`.
- Optional desktop GUI: `lit-gui` when installed with the `gui` extra.
- Machine-readable output: many automation-oriented commands support `--json`.

## Design boundaries

- No `push`, `pull`, `fetch`, or `clone`.
- No hosted collaboration model.
- No login, token, or permissions system.
- One repository lives inside one working tree on one computer.
- `export` is a compatibility bridge, not Git parity.

## Install

`lit` requires Python `3.11+`.

The recommended workflow is an editable install into a virtual environment. This installs the `lit` command (a console script) into that environment, so you can run `lit ...` once the environment is active.

### 1) Create and activate a virtual environment

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If activation is blocked by your PowerShell execution policy, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2) Install (CLI-only)

```bash
python -m pip install -e .
```

You can now run either:

```bash
lit --help
python -m lit --help
```

`python -m lit` is the no-PATH fallback and always runs `lit` using the current Python interpreter.

If you want a regular non-editable install from a checkout instead, use:

```bash
python -m pip install .
```

### 3) Optional: install the desktop GUI

From a repository checkout (editable install):

```bash
python -m pip install -e ".[gui]"
```

From PyPI:

```bash
python -m pip install "lit[gui]"
```

Launch the app with:

```bash
lit-gui
```

If `lit-gui` is not on your PATH, you can launch the same app with:

```bash
python -m lit_gui.app
```

### 4) Build a wheel or source distribution

If you want to produce installable artifacts for another environment:

```bash
python -m pip install build
python -m build
```

This creates files under `dist/`, for example:

```text
dist/lit-1.0.0-py3-none-any.whl
dist/lit-1.0.0.tar.gz
```

Install from the wheel with:

```bash
python -m pip install dist/lit-1.0.0-py3-none-any.whl
```

### PATH notes (especially on Windows)

If `lit` is not found after installing, it usually means you are running a different Python environment than the one you installed into (for example: a different venv, or no venv). Use `python -m lit ...` to avoid PATH issues, and prefer `python -m pip ...` so you install into the same interpreter you are running.

### Published package name

The PyPI distribution name is `lit`.

Install commands for published releases are:

```bash
python -m pip install lit
python -m pip install "lit[gui]"
```

The installed commands are still `lit` and `lit-gui`.

## Quick start

```bash
mkdir demo-project
cd demo-project
lit init
```

Expected output:

```text
Initialized empty lit repository in /path/to/demo-project/.lit
```

You can also choose the initial branch name:

```bash
lit init --branch trunk
```

Re-running `lit init` in the same folder keeps the repository and prints a reinitialization message.

## Command groups

### Core workflow

- `lit init [path]` initializes a repository in the target folder.
- `lit add` stages files or directories.
- `lit commit -m <message>` creates a revision from the index.
- `lit log` shows commit history.
- `lit status` summarizes the working tree.
- `lit diff` shows changes against the last commit.
- `lit restore` restores tracked files from a revision without moving `HEAD`.
- `lit checkout` switches the working tree to a branch or detached revision.
- `lit branch` lists branches or creates a new local branch.
- `lit merge` merges another local revision into the current branch.
- `lit rebase` rebases the current branch onto another local revision.

### Safety and workflow control

- `lit checkpoint create|list|show|latest` records safe boundaries for rollback, review, and lineage work.
- `lit rollback` restores the working tree to the latest safe checkpoint or a selected checkpoint.
- `lit verify run|status` records or inspects verification results for a revision, checkpoint, or lineage head.
- `lit lineage list|show|create|switch|promote|discard` manages isolated lineages for parallel local work.
- `lit lineage workspace materialize|create|attach|list|gc` manages materialized workspace records.
- `lit artifact list|show|link|usage` inspects artifact manifests and ownership links.
- `lit gc` inspects or collects reclaimable global artifact objects.
- `lit doctor` inspects repository health, locks, and unfinished transactions.
- `lit export` builds a Git-facing export plan for compatibility workflows.

Many of these commands also support `--json` and are intended to expose the same canonical repository snapshot and blockage diagnostics that the GUI uses.

## Beginner workflow

This is the everyday local flow the tool is built around:

1. `lit init` to create the repository.
2. `lit add` to stage changes.
3. `lit commit -m "message"` to save a checkpoint.
4. `lit branch feature-name` to create a side branch.
5. `lit checkout feature-name` to switch to it.
6. `lit merge feature-name` or `lit rebase main` to bring work back together locally.
7. `lit restore <path>` to discard a local file change.

## Repository layout

After `lit init`, the repository contains:

```text
.lit/
  HEAD
  config.json
  index.json
  objects/
    blobs/
    commits/
    trees/
  refs/
    heads/
    tags/
    checkpoints/
      safe/
  state/
    merge.json
    rebase.json
  v1/
    revisions/
    checkpoints/
    lineages/
    verifications/
    artifacts/
    workspaces/
    operations/
    journals/
    locks/
```

Notable details:

- `config.json` stores `default_branch` and `schema_version`.
- `.lit/config.json` is also the explicit policy surface for verification, checkpoint, artifact, lineage, and resumable operation defaults.
- `HEAD` points to `refs/heads/<branch>` until you detach it to a revision.
- Object identifiers are SHA-256 hashes of raw bytes.
- The richer `v1/` records cover revisions, checkpoints, lineages, verifications, artifacts, workspaces, operations, journals, and locks.

## Policy config

`lit` loads machine-facing policy from `.lit/config.json`. The current policy groups are:

- `verification`: default definition name and command, cache behavior, and whether verification is required before commit.
- `checkpoints`: safe-by-default behavior, approval requirements, and auto-pinning for safe checkpoints.
- `artifacts`: artifact storage location and rollback preservation behavior.
- `lineage`: default base checkpoint strategy, owned-path enforcement, overlap allowlists, and affected-lineage scope defaults.
- `operations`: whether merge/rebase resume is allowed, how safe rollback targets are chosen, and whether blockage reasons are exposed.

These settings are consumed through `src/lit/config.py` and surfaced through the shared backend service instead of being inferred separately by CLI and GUI callers.

## Architecture notes

The current v1 structure is intentionally split across a few boundaries:

- `src/lit/domain.py` defines the canonical records for revisions, checkpoints, lineages, verifications, resumable operations, and repository snapshots.
- `src/lit/backend_api.py` is the shared service boundary for CLI, GUI, and automation-oriented JSON surfaces.
- `src/lit/workflows.py` owns merge, rebase, checkpoint, rollback, verification, and resume/abort orchestration.
- `src/lit/repository.py` remains the storage and mutation engine under that service layer.
- `src/lit_gui/session.py` wraps the same backend service rather than shaping repository state independently.

If you are adding features, prefer extending these shared contracts and service paths instead of inventing CLI-only or GUI-only state models.

## Recovery and operator guidance

- Run `lit doctor --json` when automation needs a machine-readable reason for why work is blocked.
- Active merge and rebase state include resumable operation metadata, conflict paths, and the current safe rollback target.
- `lit rollback` uses the configured safe checkpoint preference, so the default recovery target can be lineage-scoped or repository-wide by policy.
- Use `lit checkpoint create --json` before high-risk changes when you want an explicit rollback boundary that external orchestration can record.

## Local docs site

The repository also includes a simple static site in `website/`.

- Open `website/index.html` directly in a browser.
- Or serve it locally with `python -m http.server` and open the URL it prints.
- No build step, package manager, or framework is required.

## Limitations and non-goals

Current limits:

- `lit` is still a local-first tool, not a hosted collaboration platform.
- There is no remote repository workflow.
- Some compatibility surfaces, like `export`, are bridges rather than full Git parity.
- GUI support is optional and requires the `gui` extra.

Non-goals:

- Hosted sync or remote collaboration
- Accounts, authentication, or permissions infrastructure
- Background daemons or heavy server-side services

## Verification

Run the test suite with:

```bash
python -m pytest
```

Run the supported multi-version matrix with:

```bash
python -m pip install -e ".[dev]"
python -m tox
```

`tox` targets Python 3.11, 3.12, 3.13, plus a packaging check environment. Missing local interpreters are skipped so one machine can still exercise the subset it has installed.

Release and publish steps are documented in [`docs/releasing.md`](docs/releasing.md).
