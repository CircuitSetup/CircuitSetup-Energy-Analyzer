# Home Assistant Compact Entity Results

This report records the automated compact-entity validation run for the
`feature/compact-entity-model` worktree. The repository keeps development
evidence in `docs/development`; do not move this report to `docs/qa`.

## Environment

- Base HEAD before the validation diff: `369a26f52d4ca5802d9b22f66b50452e02ebe2d8`
- Integration version: `0.9.1`
- Python: `3.12.10`
- Home Assistant package: `2025.1.4`

## Count Results

Generated with:

```powershell
.\.venv\Scripts\python.exe scripts\report_compact_entity_inventory.py
```

Summary from `docs/development/entity-count-comparison.md`:

- Simple maximum: 10 per-circuit entities.
- Standard maximum: 17 per-circuit entities.
- Expert without selected groups maximum: 17 per-circuit entities.
- Expert with every group selected maximum: 50 per-circuit entities.

## Verification

Fresh verification commands run against this worktree:

```powershell
rtk git diff --check
.\.codex\scripts\verify-pr.ps1
.\.codex\scripts\verify-pr.ps1 -HomeAssistant
.\.codex\scripts\update-codegraph.ps1
```

Results:

- `rtk git diff --check`: clean.
- Normal PR verification: Ruff no issues; Pytest 1074 passed.
- Home Assistant verification: Ruff no issues; Pytest 1074 passed; Home
  Assistant contract suite 166 passed.
- Codegraph regeneration: 166 files, 152 Python modules, 3317 symbols, 0 import
  cycles.

## Lifecycle Coverage

The automated Home Assistant suite covers config-entry setup, reload, unload,
remove, runtime contract checks, platform entity creation, maintenance switch
actions, generated dashboard references, and logs blocklist behavior.

## Known Limits

- A separate disposable Home Assistant Core restart was not run in this pass.
- Recorder-row and setup-duration performance measurements were not run in this
  pass.
