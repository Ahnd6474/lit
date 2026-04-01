# lit

`lit` means "local git". It is a lightweight, local-only, offline-only version control prototype for one computer.

The repository currently provides a working bootstrap command, `lit init`, plus reserved command names for the rest of the planned workflow. The README and website describe both the current verified behavior and the intended direction, with the current limitations called out clearly.

## What lit is

- A local checkpointing and version control tool for a single machine.
- A Git-like CLI with a simpler scope.
- A project that stores its repository data in a deterministic `.lit/` folder.
- A prototype designed to work with no network, account, server, sync service, or remote repository.

## Why local-only and offline-only

`lit` is meant for people who want fast local history without bringing in hosting, remotes, or collaboration infrastructure.

- No `push`, `pull`, `fetch`, or `clone`.
- No cloud sync.
- No account, login, token, or background service.
- No online dependency once the tool is installed.
- One repository lives fully inside one working folder on one computer.

That narrow scope keeps the tool small and makes the repository format easier to inspect and reason about.

## Current status

As of this prototype revision:

- `lit init` works and creates a deterministic `.lit/` repository layout.
- `add`, `commit`, `log`, `status`, `diff`, `restore`, `checkout`, `branch`, `merge`, and `rebase` are present as reserved CLI commands.
- Those reserved commands currently print `` `lit <command>` is reserved but not implemented yet. `` and exit with code `2`.

The docs below keep the planned workflow visible because those command names are already fixed in the CLI, but only the `init` behavior is implemented today.

## Install and run locally

`lit` requires Python `3.12+`.

### Option 1: Run from source without installing a script

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m lit init my-project
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m lit init my-project
```

### Option 2: Install the `lit` command locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
lit init my-project
```

## Quick start

Create a new folder and initialize `.lit` inside it:

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

Re-running `lit init` in the same folder keeps the existing repository and prints a reinitialization message.

## Main commands

| Command | Status today | Notes |
| --- | --- | --- |
| `lit init [path]` | Working | Creates `.lit/`, `HEAD`, `index.json`, object folders, refs, and merge/rebase state files. |
| `lit add` | Reserved | Planned staging command. Not implemented yet. |
| `lit commit` | Reserved | Planned checkpoint creation command. Not implemented yet. |
| `lit log` | Reserved | Planned history viewer. Not implemented yet. |
| `lit status` | Reserved | Planned working tree summary. Not implemented yet. |
| `lit diff` | Reserved | Planned local comparison command. Not implemented yet. |
| `lit restore` | Reserved | Planned file restore command. Not implemented yet. |
| `lit checkout` | Reserved | Planned branch or commit switching command. Not implemented yet. |
| `lit branch` | Reserved | Planned branch management command. Not implemented yet. |
| `lit merge` | Reserved | Planned local merge command. Not implemented yet. |
| `lit rebase` | Reserved | Planned local rebase command. Not implemented yet. |

## Beginner-friendly workflow

This is the intended local workflow once the reserved commands are implemented:

1. `lit init` to create the repository.
2. `lit add` to stage changed files.
3. `lit commit -m "message"` to save a checkpoint.
4. `lit branch feature-name` to create a side branch.
5. `lit checkout feature-name` to switch to it.
6. `lit merge feature-name` to bring work back together locally.
7. `lit rebase main` to replay local work on top of another branch when that fits better.
8. `lit restore <path>` to discard a local file change.

Today, only step 1 is operational. The rest are planned and already reserved in the command-line interface so naming stays stable as the implementation grows.

## Example session

### What you can do right now

```bash
mkdir notes
cd notes
lit init
```

That creates a `.lit/` directory with the repository metadata inside your local project folder.

### What the intended future flow looks like

```bash
lit init
lit add journal.txt
lit commit -m "Create first note"
lit branch experiment
lit checkout experiment
lit add ideas.txt
lit commit -m "Draft experiments"
lit checkout main
lit merge experiment
lit rebase main
lit restore ideas.txt
```

Treat that sequence as a roadmap example, not a promise of current behavior in this revision.

## Git similarities

- Similar command names and mental model.
- A repository metadata directory inside the working tree.
- Planned staging, commit, branch, merge, rebase, restore, and checkout flow.
- Deterministic object and ref storage intended for local history.

## Git differences

- `lit` is intentionally local-only.
- No remote hosting workflow exists.
- No collaboration features are planned.
- The current prototype is much smaller in scope than Git.
- The on-disk layout is simplified for readability and predictable local behavior.

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
  state/
    merge.json
    rebase.json
```

Notable details from the current implementation:

- `config.json` stores `default_branch` and `schema_version`.
- `HEAD` points to `refs/heads/<branch>`.
- `refs/heads/<branch>` starts empty until commits exist.
- `merge.json` and `rebase.json` start as `null`.
- Object identifiers use SHA-256 hashes of raw bytes.

## Local docs website

A simple static site lives in `website/`.

- Open `website/index.html` directly in a browser.
- Or serve it locally with `python -m http.server` and open the shown local URL.
- No build step, package manager, or framework is required.

## Limitations and non-goals

Current limitations:

- Only `init` is implemented.
- There is no verified staging, commit history, diffing, restore, branch switching, merge, or rebase behavior yet.
- The docs include planned workflows, but those sections are clearly marked as planned.

Non-goals:

- Any remote or hosted workflow.
- Multi-user collaboration features.
- Accounts, authentication, permissions, or network sync.
- Heavy infrastructure such as database servers or background daemons.

## Verification

This documentation is aligned with the currently verified bootstrap implementation and its test suite. Run:

```bash
python -m pytest
```
