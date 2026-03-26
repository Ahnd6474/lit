# lit

`lit` means "local git." It is a lightweight, local-only, offline-only version control prototype for one computer.

The project goal is simple: keep Git-like local checkpoints and branch workflows without any server, account, remote, sync service, or network dependency.

## Current status

Today, the verified CLI supports repository bootstrap:

- `lit init`

The rest of the Git-like command names already exist in the CLI, but they are reserved and **not implemented yet**:

- `lit add`
- `lit commit`
- `lit log`
- `lit status`
- `lit diff`
- `lit restore`
- `lit checkout`
- `lit branch`
- `lit merge`
- `lit rebase`

If you run one of those reserved commands now, `lit` prints a "not implemented yet" message and exits with a non-zero status.

## Why local-only and offline-only

`lit` is intentionally narrow.

- It works on a single machine.
- It is designed to work fully offline.
- It does not have `push`, `pull`, `fetch`, `clone`, remotes, accounts, or collaboration features.
- It keeps the storage model deterministic and easy to inspect inside `.lit/`.

This makes `lit` a good fit for fast local checkpoints, experiments, and learning, especially when you do not want a hosted workflow.

## Installation

`lit` currently targets Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

After installation, either of these should work:

```bash
lit --help
python -m lit --help
```

## Quick start

Create a new repository in the current folder:

```bash
python -m lit init .
```

Create a new repository in another folder:

```bash
python -m lit init my-project
```

Successful bootstrap creates a `.lit/` directory with deterministic local storage files:

- `.lit/config.json`
- `.lit/HEAD`
- `.lit/index.json`
- `.lit/objects/blobs`
- `.lit/objects/trees`
- `.lit/objects/commits`
- `.lit/refs/heads`
- `.lit/refs/tags`
- `.lit/state/merge.json`
- `.lit/state/rebase.json`

## Command overview

| Command | Status | What it means |
| --- | --- | --- |
| `lit init` | Works now | Create or reinitialize a local repository. |
| `lit add` | Reserved | Planned staging command for files. |
| `lit commit` | Reserved | Planned checkpoint creation command. |
| `lit log` | Reserved | Planned history viewer. |
| `lit status` | Reserved | Planned working tree summary. |
| `lit diff` | Reserved | Planned file comparison command. |
| `lit restore` | Reserved | Planned file restore command. |
| `lit checkout` | Reserved | Planned branch or commit switch command. |
| `lit branch` | Reserved | Planned branch management command. |
| `lit merge` | Reserved | Planned local branch merge command. |
| `lit rebase` | Reserved | Planned local rebase command. |

## Beginner workflow

The intended workflow is Git-like, but only the first step is available today.

1. Run `python -m lit init .`
2. Edit files in your project
3. Run `lit add <files>` once staging is implemented
4. Run `lit commit -m "message"` once commit support lands
5. Create a side branch with `lit branch`
6. Merge or rebase locally with `lit merge` or `lit rebase`
7. Restore files or move between checkpoints with `lit restore` or `lit checkout`

Right now, steps 3 through 7 are documentation for the planned workflow only. They are not implemented yet.

## Git similarities and differences

Similarities:

- familiar command names
- local repository metadata in a hidden directory
- planned staging, commit, branch, merge, and rebase flow
- deterministic object and reference storage

Differences:

- strictly local-only
- fully offline-only by design
- no remotes and no network operations
- narrower scope than Git
- current implementation is still at the bootstrap stage

## Local docs website

A simple static docs site lives in `website/`.

- Open `website/index.html` directly in a browser, or
- serve it locally with `python -m http.server --directory website 8000`

The website repeats the beginner guide in a format that is easy to browse locally without extra tooling.

## Current limitations

Current limitations:

- only `lit init` is implemented today
- the Git-like workflow is planned but not available yet
- there is no object writing flow for staged files or commits yet
- there is no working tree diff, restore, branch switching, merge execution, or rebase execution yet

Non-goals:

- cloud sync
- remotes
- multi-user collaboration
- hosted accounts
- background services
- heavy infrastructure
