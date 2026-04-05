# Releasing lit

This repository ships to PyPI as `lit`.

Supported runtime versions are Python 3.11, 3.12, and 3.13.

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
python -m tox
```

`tox` runs the supported interpreter matrix when available locally and also executes the packaging build plus `twine check`.

If you want to run only the packaging validation:

```bash
python -m tox -e pkg
```

If you want to sanity-check installation from a built artifact:

```bash
python -m pip install --force-reinstall dist/lit-1.0.0-py3-none-any.whl
lit --help
python -m lit --help
```

## Trusted publishing setup

Configure trusted publishing in both PyPI and TestPyPI before the first release:

1. Create the `lit` project on PyPI and TestPyPI.
2. In GitHub, create the `pypi` and `testpypi` environments.
3. In PyPI, add a trusted publisher for this repository, the `release.yml` workflow, and the `pypi` environment.
4. In TestPyPI, add a trusted publisher for this repository, the `testpypi.yml` workflow, and the `testpypi` environment.

The repository includes two publish workflows:

- `testpypi.yml` for a manual dry run to TestPyPI
- `release.yml` for tag-based GitHub Release creation and live PyPI publishing

## Tag and publish

1. Commit the release changes.
2. Optionally run the `Publish TestPyPI` workflow from GitHub Actions.
3. Create an annotated tag such as `v1.0.0`.
4. Push the branch and tag to GitHub.

The `release.yml` workflow then:

- builds the sdist and wheel
- runs `twine check`
- uploads the artifacts to the workflow run
- creates or updates a GitHub Release for the tag
- publishes to PyPI through trusted publishing

## Install commands

Published install commands should use the distribution name, not the CLI name:

```bash
python -m pip install lit
python -m pip install "lit[gui]"
```

## Open-source note

This repository does not currently declare a license file in the distribution metadata.
If you intend a public open-source release, add the license you want before publishing.
