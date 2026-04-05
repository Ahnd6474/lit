# Releasing lit

This repository ships to PyPI as `lit-local-vcs`.

The installed commands remain:

- `lit`
- `lit-gui`
- `python -m lit`

## Version sources

Keep these version strings in sync before cutting a release:

- `pyproject.toml`
- `src/lit/__init__.py`
- `src/lit_gui/__init__.py`
- `CHANGELOG.md`

## Local release verification

From the repository root:

```bash
python -m pip install -e ".[dev,gui]"
python -m pytest
python -m build
python -m twine check dist/*
```

If you want to sanity-check installation from a built artifact:

```bash
python -m pip install --force-reinstall dist/lit_local_vcs-1.0.0-py3-none-any.whl
lit --help
python -m lit --help
```

## Tag and publish

1. Commit the release changes.
2. Create an annotated tag such as `v1.0.0`.
3. Push the branch and tag to GitHub.

The `release.yml` workflow then:

- builds the sdist and wheel
- runs `twine check`
- uploads the artifacts to the workflow run
- creates or updates a GitHub Release for the tag
- publishes to PyPI through trusted publishing

## Install commands

Published install commands should use the distribution name, not the CLI name:

```bash
python -m pip install lit-local-vcs
python -m pip install "lit-local-vcs[gui]"
```

## Open-source note

This repository does not currently declare a license file in the distribution metadata.
If you intend a public open-source release, add the license you want before publishing.

