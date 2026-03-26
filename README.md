# lit

`lit` means "local git." It is a lightweight, local-only version control prototype for one computer.

`lit` is useful when you want Git-like checkpoints without any server, account, remote, or network dependency. It works fully offline and focuses on small, practical local workflows instead of collaboration features.

## What lit Does

- Initializes a repository inside any local folder.
- Stages files and directories with `lit add`.
- Creates local commits with `lit commit -m`.
- Shows local history with `lit log`.
- Reports staged, modified, deleted, and untracked files with `lit status`.
- Shows working tree diffs against the current commit with `lit diff`.
- Restores tracked files from a revision with `lit restore`.
- Switches branches or detaches `HEAD` with `lit checkout`.
- Creates and lists local branches with `lit branch`.
- Merges another local branch or commit with `lit merge`.
- Rebases the current branch onto another local branch or commit with `lit rebase`.

## Local-Only Design

`lit` is intentionally local-only and offline-only.

- No remote repositories
- No `push`, `pull`, `fetch`, or `clone`
- No accounts, login, sync, or cloud service
- No collaboration workflow
- No background daemon or server

If you need multi-machine sync or team collaboration, use Git instead.

## Installation

`lit` targets Python 3.12+.

From the repository root:

```bash
python -m pip install -e .
```

That installs the `lit` console command. During development, you can also run commands as `python -m lit ...` after installation.

## Quick Start

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

To open the static local website, open `website/index.html` in a browser.

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

## Example Workflows

### Basic Checkpointing

```bash
lit init
lit add src
lit commit -m "Save working version"
lit status
lit diff
lit log
```

### Branching and Merge

```bash
lit branch feature
lit checkout feature
lit add src
lit commit -m "Work on feature"
lit checkout main
lit merge feature
```

If both sides edit the same tracked lines, `lit merge` writes conflict markers into the file and stores merge state. You can inspect the conflict, fix the file manually, or abort with `lit merge --abort`.

### Rebase

```bash
lit checkout feature
lit rebase main
```

`lit rebase` replays the current branch's local first-parent commits onto another local revision. On conflict, it writes conflict markers and stores rebase state. You can clean up manually or abort with `lit rebase --abort`.

### Restore and Checkout

```bash
lit restore docs --source HEAD
lit checkout main
lit checkout <commit-id>
```

Use `restore` when you want files back from a revision without moving `HEAD`. Use `checkout` when you want to move `HEAD` to a branch or commit and rewrite the working tree.

## Git Similarities and Differences

Similar to Git:

- Snapshot-based local commits
- Index/staging area before commit
- Branch, merge, checkout, and rebase workflows
- Detached `HEAD` when checking out a commit directly

Different from Git:

- Only local workflows are supported
- No remotes and no network commands
- Simpler merge and rebase behavior
- Smaller command surface
- Designed for one machine, not team collaboration

## Current Limitations

- `lit diff` compares the working tree to the current commit; it is not a full staged-vs-unstaged diff suite.
- `lit log` walks first-parent history from `HEAD`.
- Merge and rebase are real, but intentionally simplified for ordinary local cases.
- Conflict handling is manual: `lit` writes conflict markers and keeps operation state, but it does not provide an interactive resolver.
- Checkout requires a clean index and tracked working tree, and it refuses to overwrite certain untracked files.
- The project is a prototype, so on-disk formats and edge-case behavior may still evolve.

## Non-Goals

- Remote hosting
- `push`, `pull`, `fetch`, or `clone`
- Authentication, user accounts, or permissions
- Multi-user collaboration
- Cloud backup or sync
- Large distributed workflows

For a browser-friendly version of the same guidance, open `website/index.html`.
