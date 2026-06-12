# Development Workflow

This repository uses GitHub Flow.

## Branches

- `master` is the only long-lived branch and should always be releasable.
- Create a short-lived branch for every change:
  - `feature/<short-name>` for user-facing features.
  - `fix/<short-name>` for bug fixes.
  - `chore/<short-name>` for process, docs, or maintenance work.
  - `release/vX.Y.Z` only when preparing a release-only version bump.
- Do not commit directly to `master` except for a documented emergency hotfix.

## Pull Requests

Every normal change goes through a pull request into `master`.

Before requesting review, the PR author should confirm:

- `ruff check .`
- `pytest -q`
- Home Assistant contract tests when entity/platform behavior changes.
- HACS validation and hassfest are passing in GitHub Actions.

Use the PR template to call out:

- What changed.
- What was tested.
- Whether a release is needed.
- Whether Home Assistant requires a restart, reload, or manual live check.

## Review Feedback

Treat ChatGPT Codex connector suggestions like normal PR review feedback.

Before merging:

1. Wait for GitHub Actions and automated review feedback to finish on the latest
   PR head.
2. Read each connector suggestion and separate actionable correctness,
   compatibility, test, and UX feedback from informational comments.
3. Implement accepted suggestions on the same PR branch.
4. Add or update tests when the accepted suggestion changes behavior.
5. Rerun the relevant local checks and push the follow-up commit.
6. Wait for the updated PR checks to pass.
7. Leave a reply or note on suggestions that are intentionally not applied,
   with the technical reason.

Do not merge while there are unresolved actionable connector suggestions.

## Merging

- Prefer squash merge for small single-purpose PRs.
- Use a normal merge commit only when preserving multiple commits helps review or audit.
- Rebase or update the branch before merge when required checks are stale.
- Keep unrelated work out of release PRs.
- Delete the remote branch after merge.
- After syncing `master`, delete the local feature branch once no work depends on it.

## Required Checks

Configure branch protection for `master` with:

- Require a pull request before merging.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.
- Required checks:
  - `Unit tests and lint`
  - `Home Assistant control entity contract`
  - `validate-hacs`
  - `validate`
- Restrict force pushes to administrators or disable them entirely.
- Require conversation resolution before merging.

## Local Verification

Use the same commands as CI before pushing a PR:

```powershell
rtk ruff check .
rtk pytest -q
```

When platform/entity behavior depends on Home Assistant base classes, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_control_entities.py -q
```

The full test suite currently targets the repository fallback environment. Do not make
the main CI job install Home Assistant until the entire suite has been converted to
real Home Assistant test fixtures.

## Emergency Hotfixes

Use the normal PR path whenever possible.

If a direct hotfix to `master` is unavoidable:

1. Make the smallest fix.
2. Run `rtk ruff check .` and `rtk pytest -q`.
3. Commit with a clear message.
4. Push `master`.
5. Immediately open a follow-up issue or PR documenting what happened and any missing cleanup.
6. Publish a patch release if HACS users need the fix.
