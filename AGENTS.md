# Repository Instructions

@C:\Users\John\.codex\RTK.md

## Project Workflow

- This repository uses GitHub Flow with protected `master`.
- Create short-lived branches for normal work: `feature/<short-name>`, `fix/<short-name>`, `chore/<short-name>`, or `release/vX.Y.Z`.
- Do not commit directly to `master` except for an explicitly requested emergency hotfix.
- Before starting follow-up work on an existing PR branch, check `git worktree list`; this repo often uses `.worktrees`.
- Keep unrelated work out of PRs and stage only the intended files.

## Codex Local Environment

- For a new Codex worktree on Windows, run `.codex/scripts/setup-windows.ps1`.
- For cleanup, run `.codex/scripts/cleanup-windows.ps1`; it removes Python/tool caches only and does not delete branches, tags, `.venv`, or source files.
- Use `.codex/scripts/verify-pr.ps1` for the normal PR verification pass.
- Use `.codex/scripts/verify-pr.ps1 -HomeAssistant` when entity, config-flow, or Home Assistant platform behavior changes.
- Use `.codex/scripts/verify-release.ps1` before tagging or publishing releases.

## Codegraph

- Read `docs/codegraph/CODEGRAPH.md` before cross-cutting changes or unfamiliar module work.
- Before editing a module, inspect its node in `docs/codegraph/codegraph.json`, inspect inbound and outbound imports in `docs/codegraph/generated/codegraph.generated.json`, and identify related tests in `tests/` and `tests_homeassistant/`.
- Use `docs/codegraph/CODEGRAPH.md` for semantic ownership and `docs/codegraph/generated/CODEGRAPH.generated.md` for exact AST-derived imports, definitions, entrypoints, and import cycles.
- Regenerate the checked-out graph after adding, removing, or moving modules; changing imports, entrypoints, processor registration, platform surfaces, panel API endpoints, storage ownership, or coordinator pipeline structure.
- Regenerate with `.codex/scripts/update-codegraph.ps1`, which writes to `docs/codegraph/generated`.
- Include generated graph changes in the same commit/PR as the structural code changes that required regeneration.

## Structural Search

- Use `rg` or `rtk grep` for plain-text search, file discovery, logs, and exact string checks.
- Use ast-grep via `sg` when matching Python or JavaScript syntax, validating structural refactors, finding call/class/function shapes, or checking patterns where comments/strings should not count.
- Example Python search: `sg run --lang python --pattern 'class $CLASS: $$$BODY' custom_components tests`.
- Example JavaScript search: `sg run --lang javascript --pattern 'async function $NAME($$$ARGS) { $$$BODY }' custom_components/circuitsetup_energy_analyzer/frontend`.
- For large structural changes, combine codegraph impact review with `sg` searches before editing and rerun relevant tests afterward.

## JSON Workflow

- Use `jq` for reading, filtering, validating, and compactly transforming JSON files or JSON command output.
- Prefer `jq -r` for extracting scalar values for shell logic, and keep JSON transformations in `jq` instead of ad hoc string parsing.
- In PowerShell, pass literal strings with `--arg` to avoid quote-stripping surprises, for example: `jq -r --arg key version '.[$key]' file.json`.
- Use `jq empty file.json` as a quick JSON validity check.

## YAML Workflow

- Use `yq` for reading, filtering, validating, and searching YAML files; use `rg` only for plain text around YAML when structure does not matter.
- Prefer `yq e '<expression>' file.yaml` for scalar extraction and structural searches instead of ad hoc string parsing.
- `yq` can also inspect TOML and JSON when useful, but keep JSON-first workflows on `jq`.
- Use `yq e '.' file.yaml` as a quick YAML validity check.

## Verification

- Normal PR verification:
  - `rtk git diff --check`
  - `rtk ruff check .`
  - `rtk pytest -q`
- Home Assistant contract verification when entity/platform/config-flow behavior changes:
  - `.\.venv\Scripts\python.exe -m pytest tests\test_control_entities.py tests\test_config_flow.py tests_homeassistant -q`
- Required GitHub checks for `master` are:
  - `Unit tests and lint`
  - `Home Assistant control entity contract`
  - `validate-hacs`
  - `validate`
- Do not assume a required check exists because similar tests run; inspect actual workflow job and check names before changing CI.

## GitHub And PRs

- Confirm `gh auth status` before GitHub work. In this environment `gh` is expected to be authenticated.
- Prefer `gh` for GitHub Actions logs, workflow runs, release operations, and thread-aware review state.
- Use the GitHub connector when it gives cleaner structured PR metadata, PR creation from a pushed branch, comments, or Codex app workflow context.
- Do not prefix PR titles with `[codex]`.
- When the user asks to create a PR and the branch is verified and committed, push the branch and open a draft PR without asking again unless scope is ambiguous.
- For PR comments from `chatgpt-codex-connector`, inspect review-thread state, not just flat PR comments.
- Treat actionable connector suggestions as part of the merge gate. Implement accepted suggestions on the same PR branch, add or update regression tests when behavior changes, rerun verification, and push the follow-up commit.
- Do not merge while unresolved actionable connector suggestions remain.
- If a review comment is intentionally not applied, leave or draft a technical explanation.
- Re-poll checks and review comments before merge or release; earlier runs here surfaced late connector feedback.
- After merge, delete the remote branch. After syncing `master`, delete the local feature branch once no work depends on it.
- After a squash merge, `git branch -d` may fail because ancestry is not preserved; verify the branch tree matches `master` before using `git branch -D`.

## Releases

- Releases are tag-driven through `.github/workflows/release.yml`.
- The version in `pyproject.toml`, `custom_components/circuitsetup_energy_analyzer/manifest.json`, and the tag `vX.Y.Z` must match.
- Verify current version files and remote tags before editing version numbers; the repo may already be at the target version.
- A release must include more than one merged substantive code-change PR. Do not create single-PR releases or version-only release PRs unless the user explicitly overrides this rule.
- The version bump should ride with one of the substantive PRs in the release batch.
- If `master` already contains the target version and the tag does not exist, create and push the annotated tag instead of making another version commit.
- After pushing a tag, confirm the GitHub release and workflow result before claiming the release is complete.

## Repo-Specific Pitfalls

- PR CI can differ from local branch results because GitHub evaluates the merge commit against current `master`.
- When a requirement refers to what is currently on GitHub, compare against current `master`, not only the branch point.
- Do not create QA docs in this repo unless the user explicitly asks for them.
- For frontend panel changes, bump `custom_components/circuitsetup_energy_analyzer/panel.py::PANEL_MODULE_VERSION` so the browser cache-buster tracks shipped JavaScript.
