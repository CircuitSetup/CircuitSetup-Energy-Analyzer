# Appliance Detail Design

Milestone: Appliance Detail model and API payload.

## Boundary

`appliance_detail.py` is a read-model layer. It does not create Home Assistant
entities, change coordinator lifecycle behavior, or write storage. It assembles
existing analyzer state into one JSON-friendly object for panel, dashboard, and
diagnostics consumers.

## API

The panel registers:

`GET /api/circuitsetup_energy_analyzer/appliance_detail`

Supported selectors:

- `?circuit_id=<circuit>` for configured direct, mixed, or mains circuits.
- `?assignment_id=<assignment>` for NILM virtual appliance assignments.

The payload is read-only and returns service/navigation action descriptors with
internal IDs already filled in.

## Source Types

The detail payload always includes `source_type`:

- `direct_meter`
- `nilm_estimate`
- `mixed`
- `mains`
- `unknown`

Direct appliances omit `confidence` because direct metering is not a model
confidence score. NILM appliances include `confidence`, `model_status`,
`assignment_id`, and `mains_source` when available.

## Current Data Sources

Direct appliances reuse existing summary helpers:

- Health Summary for `health_state` and `next_step`.
- Activity Summary for `activity_state`, runtime, and run count.
- Electrical Health for `electrical_state` and `what_to_check_first`.
- Energy Summary and Daily Energy Usage for `energy_state` and kWh.
- Active alerts for bounded `active_alerts`.

NILM appliances reuse `nilm_virtual_appliance_states()` and mark the detail as
estimated. Low-confidence or review-state assignments use validation language
instead of appliance-fault language.

## Today vs Normal And Expectations

`today_vs_normal` contains bounded metric comparisons for daily energy, runtime,
run count, and current power when current values and baselines are available.
The helper prefers contextual baseline evidence, then falls back to stored
`BaselineStats`. Missing baselines produce `learning`; missing current values
produce `missing_data`.

`expectations` contains one highest-signal appliance expectation for the first
implementation pass. Maintenance state suppresses fault language, data-quality
gaps produce `not_enough_data`, direct electrical issues can produce
`possible_issue`, contextual HVAC/rain evidence can explain high runtime as
`expected`, and low-confidence NILM appliances ask for validation instead of
claiming an appliance fault.

## Missing Data

Missing measurements remain `null`; the payload does not invent zeros except
where existing NILM virtual state already reports estimated zero power. A
not-found selector returns a friendly message and points users back to the
generated dashboard or summary sensors.
