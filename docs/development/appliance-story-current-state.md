# Appliance Story Current State

Generated for the appliance-centered usability PR 1 audit.

Baseline commit: `f25ea915d275f4673667b9a7ec01b0b046980cc7`
Integration version: `0.10.5`

## Summary Entities

Current summary-first entities are centered on compact rollups, not on one
appliance detail object.

| Entity family | State | Key attributes | Notes |
| --- | --- | --- | --- |
| Setup Health | Highest-priority setup action, or `Ready` | `ready`, `issue_count`, `next_step`, `recommended_action`, `affected_circuits`, `open_path`, bounded `issues` | Global setup surface and repair target. |
| Health Summary | `Ready`, `Learning`, `Needs data`, `Observation recorded`, `Paused`, `Possible issue`, `Mixed observation`, `NILM review` | `raw_status`, `status_explanation`, `learning_progress`, `readiness`, `data_quality_problem`, `maintenance_active`, `active_alert_count`, `next_step` | Best current per-appliance next-step source. |
| Activity Summary | `Running`, `Idle`, `Unavailable`, `Standby`, `On`, `Off`, `No Activity` | `run_cycle_status`, `standby_status`, `run_cycle_count`, `run_cycle_runtime_seconds`, `duty_cycle_percent`, `summary_explanation`, optional operating state | Best current "what is it doing now" source. |
| Electrical Health | `Normal`, `Needs Metrics`, `Possible Imbalance`, `Possible Metric Mismatch`, `Possible Power Quality Change` | Metric consistency, leg imbalance, power-quality values, `status_explanation`, `what_to_check_first` | Best current "what should I check first" source. |
| Energy Summary | `Normal`, `Learning`, `Needs Energy Data`, `Watch`, `High Usage` | `energy_data_available`, usage/goal/billing/cost statuses, daily kWh, usage share, billing/cost forecasts, explanations | Best current daily energy rollup. |
| Daily Energy Usage | Numeric kWh | Energy usage evidence | Separate numeric entity used by dashboard and Energy tracking. |
| Running binary sensor | `on`/`off` | Standard binary sensor attributes | Not created for mixed, mains NILM, or solar inverter profiles. |
| NILM discovered signatures / unknown loads | Counts or bounded unknown-load state | NILM review attributes | Only present for mains NILM circuits. |
| NILM virtual appliance entities | Estimated health/activity/energy/power | `estimated: true`, `source: nilm`, `assignment_id`, `mains_source`, `confidence`, `model_status`, `last_validation` | The clearest current direct-vs-estimated signal. |

## Dashboard

Dashboard layout is generated in `dashboard.py`. It currently builds:

- Appliance Status.
- Optional Mains, Solar, and NILM.
- Energy Tracking.
- Optional HVAC Weather Context.
- Expert Diagnostics and Evidence.

The dashboard already resolves entity IDs through the entity registry when Home
Assistant and a config entry are available. Missing, disabled, unavailable, or
ambiguous entities produce notes instead of guessed cards.

Current appliance cards are compact. They include summary entities and evidence
buttons when feature cards are enabled. They do not yet show a single Today vs
Normal comparison, behavior watchlist, or run timeline.

Current mains/NILM cards include rollups, known-load share, mains load match,
unknown load inventory, signals, `Open NILM Graph & Review`, and optional expert
NILM graph cards. There is no explicit backend lane model yet.

## Evidence Panel

The panel registers authenticated GET routes for:

- `/api/circuitsetup_energy_analyzer/alert_evidence`
- `/api/circuitsetup_energy_analyzer/nilm_workspace`
- `/api/circuitsetup_energy_analyzer/nilm_workspace_history`

The panel is URL-accessible at `/circuitsetup-energy-analyzer-evidence` and is
not a sidebar-first panel.

Alert evidence lookup supports:

- exact alert ID;
- latest alert for circuit;
- state-detail fallback;
- known circuit with no current evidence;
- not-found responses.

Current evidence actions are:

- acknowledge;
- mark expected;
- mark unhelpful;
- pause alerts;
- relearn baseline;
- open Advanced Circuit Settings;
- recommendation preview/apply/dismiss/undo/reset where available.

## NILM Workspace

The NILM workspace selects an explicit mains NILM circuit first, with a
sensor-backed mains fallback. Payloads include:

- bounded history;
- known-load overlays;
- solar overlays;
- signatures;
- label intervals;
- assignments;
- virtual appliances;
- validation payloads;
- edges;
- sessions.

Actions already cover signature labeling, assignment, ignore/expected/merge,
interval labeling, assignment publish/unpublish/retire/rename/profile changes,
validation history, and session confirm/reject/assign.

The frontend has review-first behavior for the next unlabelled or unfinished
signature. It does not yet expose formal lanes such as Needs Review, Assigned,
Needs Validation, Ready to Publish, Published, and Ignored.

## Confidence And Source Visibility

Confidence is visible today in:

- NILM signature labels and workspace cards;
- NILM estimated appliance attributes;
- NILM session/assignment displays;
- settings recommendations.

Direct-vs-estimated source is explicit for NILM virtual appliances through
`estimated`, `source: nilm`, and `mains_source`. Direct appliances generally do
not expose an equivalent `source_type` badge.

## What Changed And What To Check First

What changed is strongest in alert evidence and notifications:

- observed value;
- baseline value;
- change ratio;
- repeated count;
- first and last seen;
- feature-specific explanation.

What to check first exists on Electrical Health and some evidence paths. It is
not yet consistently available for activity, energy, NILM validation, and no
alert/no evidence states.

## User-Visible Gaps

- No single Appliance Detail payload combines now, today, source, confidence,
  daily usage, alerts, recommendations, and actions.
- Direct appliances do not get the same explicit source badge as estimated NILM
  appliances.
- Today vs Normal exists only indirectly through alert evidence and summary
  statuses.
- Behavior Watchlist is not a first-class payload or dashboard section.
- Run timeline is not assembled as a per-appliance view.
- NILM review has strong primitives but no explicit lane model.
- The current no-evidence fallback page still asks users to jump between summary
  sensors and actions instead of showing an appliance-centered story.
