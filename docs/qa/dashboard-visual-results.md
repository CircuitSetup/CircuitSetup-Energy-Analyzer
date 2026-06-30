# Dashboard Visual Results

Branch: `feature/appliance-story-usability`

## Generated Dashboard Story

The recommended dashboard now builds a first-stop energy view with these
sections:

- Household Overview
- Today's Energy
- Behavior Watchlist
- Appliance Status
- Mains, Solar, and NILM
- Energy Tracking
- Appliance Run Timeline
- NILM Review when NILM/mains data is available
- HVAC Weather Context when configured
- Expert Diagnostics on expert layout

## Data Contracts

- Entity cards resolve actual entity-registry IDs when Home Assistant registry
  data is available.
- Removed, disabled, or unavailable entities are represented as dashboard notes
  instead of guessed entity IDs.
- Dashboard preflight reports included sections, skipped items, missing source
  data, disabled entities, NILM enablement, and estimated appliance count.
- NILM sections are conditional on mains/NILM capability.

## Test Coverage

Primary tests:

- `tests/test_recommended_dashboard.py`
- `tests/test_dashboard_controller.py`
- `tests/test_user_facing_text.py`

Covered scenarios include registry-first IDs, idempotent update, NILM section
gating, behavior watchlist section data, dashboard preflight, and frontend graph
card registration.

## Remaining Visual QA

Browser screenshots inside a live Home Assistant instance are still required
before release. The current branch verifies dashboard structure and payloads but
does not yet attach screenshot evidence for desktop/mobile rendering.
