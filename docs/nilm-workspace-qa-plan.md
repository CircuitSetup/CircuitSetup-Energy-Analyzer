# NILM Workspace QA Plan

**Goal:** Verify the demo workspace can exercise the newly added NILM graph, review, labeling, assignment, validation, and known-load flows without waiting for live learning.

**Scope:** Use the bundled demo source toggle, the existing NILM workspace APIs, and Chrome against Home Assistant. Do not create separate QA-only APIs or alternate fixtures.

## Demo Data Contract

- Enable **Load Bundled Demo Sources** and **Enable Experimental NILM**.
- Confirm the demo mains NILM circuit has mains L1/L2 power, voltage, current, power factor, reactive power, apparent power, and energy entities.
- Confirm the NILM workspace payload includes signatures, unknown loads, edges, sessions, label intervals, assignments, virtual appliances, and validation metrics.
- Confirm demo sessions include one closed labeled session and one open session.
- Confirm validation has at least one ground-truth interval and at least one prediction.

## Graph And Review Workspace

- Open `/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains_nilm`.
- Confirm the NILM graph renders multiple timestamps, not a single x-axis point.
- Click **Show on Graph** on a NILM signature and confirm history reloads for the relevant interval.
- Confirm signature labels appear on the graph for matching sessions or highlighted edges.
- Click the same **Show on Graph** target again and confirm focus clears.
- Confirm known-load overlays are grouped by load/circuit, not listed once per sensor.

## Review Actions

- Confirm each signature has label, assign, ignore, expected, and merge actions where applicable.
- Save a signature label and confirm the review state changes to labeled.
- Assign a signature or session to an appliance and confirm it appears under assignments.
- Confirm assignment cards support rename, profile change, merge, publish, unpublish, and retire states.
- Confirm **Validate History** uses the demo ground-truth interval and shows precision/recall counts.

## Compatibility Checks

- Open the existing **NILM Review** evidence path and confirm it still shows the same review inventory.
- Confirm configured **known load circuits** are available as ground-truth sources and overlays.
- Confirm setups with no mains source show the existing mains/NILM setup guidance instead of an empty graph.
- Confirm no production circuits receive demo-only assignments or label intervals.

## Verification Commands

- `rtk pytest tests\test_coordinator.py::test_demo_mains_nilm_history_is_seeded_after_learning -q`
- `rtk pytest tests\test_panel.py tests\test_user_facing_text.py -q`
- `rtk ruff check custom_components tests`
- `.\.codex\scripts\verify-pr.ps1 -HomeAssistant`
