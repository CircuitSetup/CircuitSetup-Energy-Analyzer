# End-User Usability Audit

## Baseline

- Commit: `f66df7a4a9e18a773df16ab7549a60edf0ff8c91`
- Integration version: `0.11.1`
- Python: `3.12.10`
- Home Assistant test runtime: `2025.1.4`
- Unit tests: `1484 passed in 61.80s`
- Home Assistant lifecycle tests: `9 passed in 6.68s`
- Ruff: `All checks passed!`
- Generated codegraph: 234 files, 212 Python modules, 4,418 symbols, zero import cycles

## What Already Works

- Appliance Detail for direct and NILM-estimated loads
- Direct versus estimated source labels
- Current appliance state, energy, runtime, run count, cost estimate, and alerts
- A selectable 24-hour, 7-day, or 30-day appliance history graph
- Existing behavior expectations for setup, maintenance, electrical, weather,
  rain, and NILM validation context
- Setup Health, Advanced Settings explanations, evidence actions, NILM review,
  and generated dashboards
- Persisted NILM assignments and bounded NILM session history
- Home Assistant-local day handling for energy, cycles, and demand

## Partial Or Misleading Behavior

| Area | Current behavior | Gap |
|---|---|---|
| Today vs Normal | One observed value is compared with one baseline range. | Partial-day totals are not explicitly separated from expected-so-far or projected totals. |
| Current power | Latest real power is compared with a mixed-state baseline. | Running, idle, and mixed-circuit contexts are not separated. |
| Demand/capacity | Current and peak values exist in analyzer state. | Appliance Detail compares unlike concepts and omits configured limits. |
| Cost | Billing cost accumulates each delta at the active tariff. | Appliance Detail estimates today's cost with one rate and hardcodes dollars. |
| Expectations | An ordered early-return chain emits one finding. | No top-three ranking, semantic deduplication, or integration-wide attention list. |
| NILM identity | Assignments and sessions persist. | No canonical appliance key; detail and alerts can fall back to mains identity/history. |
| Session history | Graph and recent event list exist. | No shared direct/NILM session payload or accessible session strip. |
| Source trust | Setup Health exposes stale/missing data and readiness. | Appliance Detail does not separate source quality, readiness, and finding confidence. |
| Settings | Current/default/suggested values and bounded evidence are shown. | No pure historical current-versus-candidate replay. |
| Accessibility | Buttons, labels, live feedback, focus handling, and responsive CSS exist. | No browser gate, graph table fallback, contrast audit, or disposable-HA E2E run. |

## Missing Product Surfaces

- Needs Attention
- Appliance Insights index and filters
- Per-appliance notification preferences, quiet hours, cooldown, and summaries
- Weekly appliance digest
- Expected Schedule entity or local-window context
- Conservative energy-change factorization
- True direct/NILM session timeline
- Browser-driven Home Assistant and accessibility CI job

## Appliance Detail Data Sources

| Field | Source |
|---|---|
| Activity | `activity_summary_value` and operating state snapshot |
| Current power | `AnalyzerState.latest_real_power_w_by_circuit` |
| Daily energy | `AnalyzerState.daily_energy_usage_by_circuit` |
| Runtime / run count | `summarize_circuit_cycles` via `UxStateManager` |
| Cost | Current implementation multiplies daily kWh by `effective_electricity_rate` |
| Baselines | Contextual energy/demand evidence, then `FeatureStoreData.baselines` |
| Direct history | Recorder entity history selected by `panel._appliance_detail_history_payload` |
| NILM history | Assignment-filtered `nilm_session_history_by_circuit` |
| Alerts | `FeatureStoreData.alerts` filtered by circuit and, where available, assignment features |

## Routes And Drilldowns

Stable public paths that must not change:

- Dashboard: `/circuitsetup-energy-analyzer`
- Panel: `/circuitsetup-energy-analyzer-evidence`
- APIs: `/api/circuitsetup_energy_analyzer/alert_evidence`,
  `/appliance_detail`, `/setup_health`, `/nilm_workspace`, and
  `/nilm_workspace_history`
- Query modes: `appliance_detail=1`, `nilm_workspace=1`, `setup_health=1`, and
  `suggested_settings=1`

Evidence can open direct Appliance Detail. NILM virtual-appliance cards can open
assignment detail. Generated direct-appliance cards currently omit detail links;
Appliance Insights must add discoverability without breaking existing dashboard
paths.

## Notification And Storage Audit

Current notification controls are circuit-wide pause/maintenance, sensitivity,
and expected/not-helpful feedback. There are no appliance category preferences,
delivery modes, quiet hours, cooldown choices, or digest opt-in fields.

`FeatureStoreData` uses storage schema version 5. New durable sections require
explicit migrations for notification preferences/delivery state, digest opt-in
and idempotence, and schedule choices/repeated-window evidence. Comparisons,
attention items, previews, source quality, energy explanations, and direct
session payloads should remain derived. Existing assignment and NILM session
storage should be reused.

## Implementation Order

1. Correct comparison and cost semantics.
2. Establish stable NILM appliance identity and assignment-specific history.
3. Rank expectations and derive Needs Attention.
4. Add the shared session payload and accessible timeline.
5. Add pure bounded settings preview.
6. Add notification preferences, digest, and schedule context with migrations.
7. Add Appliance Insights, energy explanation, and trust presentation.
8. Finish modularization, browser E2E, accessibility, and documentation.
