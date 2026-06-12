# Release Process

This project publishes Home Assistant custom integration releases through GitHub
tags and GitHub Releases. HACS uses the repository release metadata to surface
updates to users.

## Versioning

Use SemVer-style versions:

- Patch, `X.Y.Z`: bug fixes and compatibility fixes.
- Minor, `X.Y.0`: new entities, new UI behavior, or new non-breaking features.
- Major, `X.0.0`: breaking configuration, storage, service, or migration changes.

Every release updates both files:

- `pyproject.toml`
- `custom_components/circuitsetup_energy_analyzer/manifest.json`

The tag must be `vX.Y.Z` and must match those file versions.

## Release PR

Create a release PR for planned releases:

```powershell
git switch -c release/vX.Y.Z
```

The PR should include:

- Version bump in `pyproject.toml`.
- Version bump in `custom_components/circuitsetup_energy_analyzer/manifest.json`.
- Any release-specific docs or notes.
- Passing CI.

Run local checks before pushing:

```powershell
rtk ruff check .
rtk pytest -q
```

If Home Assistant entity/platform behavior changed, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_control_entities.py -q
```

Merge the release PR into `master` after required checks pass.

## Tag And Publish

After the release PR is merged and `master` is up to date:

```powershell
git switch master
git pull --ff-only origin master
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The `Publish Release` GitHub Actions workflow validates that the tag matches
`pyproject.toml` and `manifest.json`, then creates a GitHub Release with generated
release notes.

## Manual Release Fallback

If GitHub Actions cannot publish the release, create or update the release manually:

```powershell
gh release create vX.Y.Z --title vX.Y.Z --generate-notes
```

If `gh` is unavailable or unauthenticated, use the GitHub web UI for the pushed tag.

## Post-Release Checks

After publishing:

1. Confirm the release exists at:

   `https://github.com/CircuitSetup/CircuitSetup-Energy-Analyzer/releases/tag/vX.Y.Z`

2. Confirm HACS sees the new version. This may require waiting for HACS metadata refresh.
3. In a live Home Assistant instance, install the update and restart Home Assistant when custom integration code changed.
4. Confirm the integration manifest reports the new version after restart.

## Hotfix Release

For urgent production breakages:

1. Branch from current `master`.
2. Fix only the bug.
3. Add or update the regression test.
4. Run required checks.
5. Merge through PR when possible.
6. Publish the next patch version.

Do not bundle unrelated cleanup into hotfix releases.
