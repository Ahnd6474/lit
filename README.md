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

`lit` requires Python `3.12+`.

### CLI only

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m lit init my-project
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m lit init my-project
```

If you prefer the installed command:

```bash
pip install -e .
lit init my-project
```

### With the desktop GUI

```bash
python -m pip install -e ".[gui]"
lit-gui
```

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
- `HEAD` points to `refs/heads/<branch>` until you detach it to a revision.
- Object identifiers are SHA-256 hashes of raw bytes.
- The richer `v1/` records cover revisions, checkpoints, lineages, verifications, artifacts, workspaces, operations, journals, and locks.

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

Non-goals:

- Hosted sync or remote collaboration
- Accounts, authentication, or permissions infrastructure
- Background daemons or heavy server-side services

## Verification

Run the test suite with:

```bash
python -m pytest
```

