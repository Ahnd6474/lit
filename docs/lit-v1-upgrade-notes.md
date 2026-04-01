# lit v1 upgrade notes

## Identity shift

Older messaging described `lit` as "local git" or a lightweight local Git-like prototype.

V1 replaces that framing with:

- local execution VCS
- one-machine autonomous workflow focus
- safe checkpoint and rollback model
- lineage isolation and promotion
- verification-aware history

## Packaging change

The base install is now CLI-only (installs the `lit` console script into the active Python environment):

```bash
python -m pip install -e .
```

If you're installing from a published build instead of a repository checkout:

```bash
python -m pip install lit
```

If the `lit` command is not available on your PATH, the no-PATH fallback is:

```bash
python -m lit --help
```

Install the desktop dependency explicitly when needed:

```bash
python -m pip install -e ".[gui]"
```

From a published build:

```bash
python -m pip install "lit[gui]"
```

This also installs `lit-gui` (with `python -m lit_gui.app` as the no-PATH fallback).

## New public CLI surfaces

V1 adds:

- `lit checkpoint`
- `lit rollback`
- `lit verify`
- `lit lineage`
- `lit artifact`
- `lit gc`
- `lit doctor`
- `lit export`

These commands are the supported public release surface for checkpoint, verification, lineage, artifact, health, and Git-bridge workflows.

## Compatibility

V1 readers remain compatible with legacy revision metadata that only stored old commit-style authorship fields.

When older revision JSON is encountered:

- provenance fields are synthesized conservatively
- export trailers still include legacy authorship
- checkpoint and rollback workflows continue to function

## Git limits

If you previously treated `lit` as a Git substitute, the supported limit is now explicit:

- no remotes
- no `push`, `pull`, `fetch`, or `clone`
- no attempt at full Git parity

Use `lit export` when you need a Git-facing bridge for downstream tools.
