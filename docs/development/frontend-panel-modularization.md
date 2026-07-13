# Frontend And Panel Modularization

The public panel entrypoint remains `energy-analyzer-panel.js`. It loads every
frontend module with the same `PANEL_MODULE_VERSION` query so Home Assistant
keeps one stable resource URL without mixing cached module revisions.

Frontend responsibilities are split into:

- `energy-analyzer-panel-main.js` for the panel host, routing, and shared state;
- `energy-analyzer-panel-shell.js` for rendering and event wiring;
- `energy-analyzer-appliance-views.js` for Appliance Insights, Appliance Detail,
  Setup Health, schedules, and weekly digest views;
- `energy-analyzer-nilm-workspace.js` for NILM review workflows;
- `energy-analyzer-evidence-views.js` for evidence, recommendations, history,
  and graph helpers;
- `energy-analyzer-dashboard-graphs.js` for dashboard graph rendering.

Route modules receive their shared constants from the versioned main module
through small method-group factories. They do not import an unversioned copy of
the main module.

Backend route constants and payload contracts live in `panel_contracts.py`.
NILM workspace payload construction lives in `panel_nilm.py`, while the small
cross-panel helpers live in `panel_common.py`. Registration and compatibility
exports remain in `panel.py`, and authenticated views remain in
`panel_views.py`. Existing imports from `panel.py` continue to work.

The split preserves the panel path, API paths, service names, dashboard links,
and coordinator imports. `tests/test_modularization.py` checks the compatibility
facades, responsibility modules, route entrypoint, and version propagation.
