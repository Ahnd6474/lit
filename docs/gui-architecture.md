# GUI Architecture

`lit_gui` is a thin PySide6 desktop shell over the existing local-only `lit` backend.

## Run Locally

From a repository checkout (run from the repository root):

```bash
python -m pip install -e ".[gui]"
lit-gui
```

From a published build:

```bash
python -m pip install "jakal-lit[gui]"
lit-gui
```

You can also launch the same app with:

```bash
python -m lit_gui.app
```

Run the verified test suite with:

```bash
python -m pytest
```

## Shell Layout

- Left sidebar: repository identity, current branch, repository status, and high-attention workflow state.
- Center view: Home, Changes, History, Branches, and Files.
- Right detail panel: selected item details, metadata, and action guidance for the active view.

`LitShellWindow` owns that three-pane shell. Feature views do not mutate repositories directly.

## Session Boundary

`lit_gui.contracts.RepositorySession` is the only GUI mutation and query boundary. `LitRepositorySession` rebuilds immutable DTO snapshots after each action and keeps selection state stable when possible.

The important rule is: views render DTOs and call session methods. They do not import `lit.repository` directly.

## Current Branch And Operation Flows

- `Changes` handles staging, commit creation, and working-tree diff selection.
- `History` handles commit timeline selection and per-path commit previews.
- `Branches` handles branch creation plus restore, checkout, merge, rebase, and abort entry points.
- Active merge or rebase state is surfaced in both the sidebar and the right detail panel, with conflicted paths called out for manual resolution.

## Test Strategy

- `tests/gui/backend/test_session.py` covers repository snapshot shaping and operation state behavior.
- `tests/gui/views/` covers shell wiring and view-level workflows.
- GUI tests install a narrow fake `PySide6` module from `tests/test_lit_gui_bootstrap.py`, so the view logic is exercised without requiring a desktop runtime during automated verification.
