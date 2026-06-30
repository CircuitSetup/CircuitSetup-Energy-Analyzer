# Home Assistant Appliance Workflow Results

Branch: `feature/appliance-story-usability`

## Current Gate

The branch uses the repository Home Assistant contract tests as the disposable
HA workflow gate:

```powershell
.\.venv\Scripts\python.exe -m pytest tests_homeassistant -q
```

This gate covers integration setup contracts, control entities, config-flow
behavior, reload/unload-sensitive entity registration paths, and fake-HA
compatibility used by the test harness.

## Workflow Areas Covered By Unit/HA Tests

- Fresh config-flow and options-flow paths.
- Entity registry/device registry compatibility.
- Dashboard creation/update/remove orchestration.
- Appliance detail API payloads for direct and NILM appliances.
- Alert evidence and recommendation action payloads.
- Maintenance, pause alerts, and feedback service routing.
- NILM workspace payload lanes and internal-ID action data.
- Setup Health checklist attributes.
- Advanced setting recommendation values, defaults, explanations, reset, undo,
  and dismissal.

## Required Live Browser Smoke Before Release

The following still need a real Home Assistant browser session before release:

- install and configure from the UI;
- create the recommended dashboard;
- open appliance detail and Today vs Normal sections;
- review Behavior Watchlist;
- open evidence from notification/dashboard links;
- assign/review NILM in the workspace;
- use maintenance and settings actions;
- reload, restart, unload, and remove without tracebacks;
- inspect desktop/mobile layout screenshots for overlap or broken controls.

## Known Limitation

No Playwright/browser screenshot run against a live Home Assistant frontend has
been captured yet on this branch. Do not treat this as final release evidence
until that smoke is run and recorded.
