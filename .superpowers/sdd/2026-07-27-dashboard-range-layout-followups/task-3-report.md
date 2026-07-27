# Task 3 Report: Date Reset And Range-Aware Rendering

## Status

Completed.

## Files Changed

- `custom_components/circuitsetup_energy_analyzer/frontend/energy-analyzer-dashboard-graphs.js`
  - Now resets to the bounded single-day Today range and stores the `today` preset.
  - House power flow is omitted for multi-day ranges.
  - Single-day appliance tiles show Health and Learning days remaining when valid.
- `custom_components/circuitsetup_energy_analyzer/translations/en.json`
  - Added `learning_days_left`.
- `custom_components/circuitsetup_energy_analyzer/panel_contracts.py`
  - Bumped `PANEL_MODULE_VERSION` to `20260727-5`.
- `tests/e2e/panel.spec.js`
  - Updated Now assertions and added range-aware flow and learning-tile coverage.

## Tests And Outputs

- `rtk npm run test:e2e -- --grep "Now|learning days|House power flow"`
  - Initial red run: expected failures for always-visible flow and missing learning suffix.
  - Final run: `4 passed`.
- `rtk npm run test:e2e -- --grep "Now|learning days|House power flow|dashboard date range is shared|stock month navigation|historical appliance grid"`
  - Final run: `10 passed` across Desktop and Mobile Chromium.
- `rtk git diff --check`
  - Passed.
- `jq empty custom_components/circuitsetup_energy_analyzer/translations/en.json`
  - Passed.

## Commit SHA

- Implementation: `3f0db78eb47e092443c44aecb8435075d9eddd85`

## Self-Review

- Now preserves only the Compare toggle and intentionally collapses every prior range to Today.
- Flow hiding is limited to `.flow`; top charts and other Home card content remain rendered.
- The health row uses calendar-day count, so past single-date selections retain Health while multi-day selections do not.
- Learning suffix requires normalized `Learning` status and finite non-negative progress values; remaining days are clamped to the required range.

## Concerns

None. `npm ci` was needed because this worktree had no local Playwright binary; it produced no tracked changes.
