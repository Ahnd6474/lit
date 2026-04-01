# lit

`lit` means "local git". It is a lightweight, local-only, offline-only version control prototype for one computer.

The project aims to feel familiar if you already know Git, but it intentionally removes anything that depends on remotes, accounts, servers, syncing, or network access. Everything lives in a local `.lit/` directory inside your project.

`lit init` is the only implemented end-to-end command today.

## Why lit exists

Use `lit` if you want simple local checkpoints without turning on a hosted workflow.

- Keep history on one machine.
- Work fully offline.
- Use Git-like ideas for staging, commits, branches, merges, and rebases.
- Keep the storage format deterministic and easy to inspect.

## Current status

This repository is in the bootstrap stage.

| Command | Status | Notes |
| --- | --- | --- |
| `lit init` | Implemented | Creates a deterministic `.lit/` repository. |
| `lit add` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit commit` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit log` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit status` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit diff` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit restore` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit checkout` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit branch` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit merge` | Reserved | Prints a not-implemented message and exits with code `2`. |
| `lit rebase` | Reserved | Prints a not-implemented message and exits with code `2`. |

## Install and run locally

`lit` currently targets Python 3.12 or newer.

```bash
git clone https://github.com/Ahnd6474/lit.git
cd lit
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Then initialize a repository:

```bash
python -m lit init
```

Or install the console script and use:

```bash
lit init
```

To initialize a different folder or choose another default branch:

```bash
python -m lit init my-project
python -m lit init --branch trunk my-project
```

## What `lit init` creates

The current bootstrap layout is:

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

Notes:

- `HEAD` points at the current branch reference, such as `refs/heads/main`.
- `config.json` stores deterministic repository settings.
- `index.json` is the future staging area file.
- `objects/` is reserved for content-addressed blobs, trees, and commits.
- `state/merge.json` and `state/rebase.json` are reserved for in-progress operations.

## Beginner quick start

What you can run today:

```bash
mkdir notes
cd notes
python -m lit init
```

Expected result:

- A `.lit/` directory appears in the current folder.
- The default branch is `main` unless you override it.
- Running `python -m lit init` again reinitializes the same repository safely.

If you try a planned command now, you will see the current limitation clearly:

```bash
python -m lit add README.md
```

That command is reserved, but it is not implemented yet.

## Planned command workflow

The intended local workflow is Git-like, but most of it is still ahead of this bootstrap milestone.

```text
lit init
lit add <files>
lit commit -m "message"
lit branch feature-x
lit checkout feature-x
lit merge feature-x
lit rebase main
lit restore <path>
lit log
lit status
lit diff
```

Treat that sequence as the product direction, not as a promise that the commands already work in this revision.

## Git similarities and differences

Similar to Git:

- Repository-per-folder model.
- A hidden metadata directory.
- Planned staging, commits, branches, merges, rebases, diffs, and restore flows.
- Content-addressed objects and branch references.

Different from Git:

- `lit` is local-only by design.
- `lit` is offline-only by design.
- There is no clone, fetch, pull, push, remote, account, or collaboration model.
- The scope is intentionally smaller and easier to understand.

## Local-only and offline-only design

These are product rules, not temporary omissions.

- No network access is required to use `lit`.
- No server process is required.
- No remote repository concept is planned.
- No sync service, cloud storage, login, or hosted control plane is part of the design.

## Website

A simple local docs site lives in `website/`.

- Open `website/index.html` directly in a browser.
- Or serve it locally with `python -m http.server` and visit the generated local URL.
- The site is plain static HTML and CSS with no build step.

## Limitations and non-goals

Current limitations:

- Only repository initialization is implemented.
- There is no working staging, commit history, diff output, restore flow, branch switching, merge logic, or rebase engine yet.
- The documentation shows both the verified current state and the intended future workflow. Do not assume reserved commands work until tests and code land for them.

Non-goals:

- Remote repositories.
- Multi-user collaboration.
- Cloud sync.
- Accounts, logins, or hosted infrastructure.
- Heavy web stacks or documentation tooling for the local docs site.
