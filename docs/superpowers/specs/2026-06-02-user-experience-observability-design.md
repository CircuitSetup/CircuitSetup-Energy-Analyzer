# User Experience Observability Design

## Goal

Add user-facing clarity and control to CircuitSetup Energy Analyzer so users can understand what the integration is doing, why a circuit is or is not alerting, and how to respond when learned behavior changes.

These features build on the existing v1 architecture. They do not introduce a custom Lovelace card, cloud service, external database, or definitive appliance diagnosis. The integration remains evidence-first and Home Assistant-native.

## Scope

This design adds:

- Per-circuit readiness and learning-progress diagnostics.
- A compact circuit health summary.
- Richer alert evidence details.
- Guided mapping-review output with confidence reasons.
- Maintenance and expected-change handling.
- Per-circuit sensitivity presets.
- NILM signature review diagnostics and controls.
- Data-quality checklist diagnostics.
- A richer suggested dashboard example.
- False-positive feedback actions.

## User Experience Principles

Users should be able to answer four questions without reading logs:

- Is this circuit ready, learning, paused, or blocked by missing data?
- What evidence caused this alert or diagnostic state?
- What can I do next: accept, pause, relearn, label, ignore, or mark expected?
- Which parts of the analysis are strong evidence and which are exploratory hints?

The integration should continue to phrase appliance behavior as possible issues, with observed evidence. Repairs remain limited to setup, configuration, and source-data quality problems.

## Architecture

The current coordinator remains the source of runtime analysis state. New UX features are expressed through:

- Additional diagnostic sensor entities and attributes.
- Additional binary sensor state where a simple on/off concept is useful.
- Services/actions for user feedback and lifecycle control.
- Integration-owned storage for user feedback, maintenance windows, sensitivity presets, and NILM review decisions.
- An expanded dashboard example that uses standard Home Assistant cards.

No custom frontend panel is required for v1. The design should use standard Home Assistant entity state, attributes, services, persistent notifications, and Repairs.

## Circuit Readiness And Learning Progress

Each configured circuit should expose a readiness summary with:

- Current status: `learning`, `ready`, `needs_data`, `paused`, `possible_issue`, `mixed_observation`, or `nilm_review`.
- Baseline age in days.
- Observed cycle count or event count.
- Baseline confidence.
- Required metric coverage.
- Optional metric coverage.
- Last valid sample timestamp.
- Alert readiness.
- Suppression reason, if alerts are blocked.

Learning progress should be available even when no alert is active. This makes it clear whether the integration is working, waiting for enough cycles, blocked by missing data, or intentionally paused.

## Circuit Health Summary

Each circuit should expose a compact health summary sensor. The state should be short and dashboard-friendly:

- `Learning`
- `Ready`
- `Needs data`
- `Paused`
- `Possible issue`
- `Mixed observation`
- `NILM review`

Attributes should include the machine-readable status, circuit mode, appliance profile, active alert count, learning progress, and the strongest evidence summary.

Mixed circuits should not appear as failed or unhealthy simply because they contain multiple loads. Their status should distinguish observation-only behavior from appliance-specific alerts.

## Alert Evidence Detail

Alert evidence should include structured details that can be shown in sensor attributes and diagnostics export:

- Alert id.
- Circuit id.
- Feature or metric family.
- Baseline value.
- Observed value.
- Percent change, where meaningful.
- Repeated evidence count.
- Baseline confidence.
- Time window.
- Contributing metric relationships.
- Human-readable evidence text.

Persistent notifications should stay concise. The richer detail belongs in diagnostic entities and export data so advanced users can inspect what changed without making the notification noisy.

## Guided Setup Review

Auto-suggested mappings should include confidence and reasons. Reasons may include:

- Entity naming similarity.
- Device or meter name similarity.
- Expected phase pairing.
- Correlated load changes.
- Similar voltage behavior.
- Required metric availability.
- Optional metric availability.

The setup text should make clear that suggestions require confirmation. Users should be able to accept suggestions, manually edit mappings, mark a circuit as mixed, or exclude a circuit.

For v1, this can remain a config-flow text summary plus validated JSON/YAML-style mapping input. A future UI can turn the same data into richer selection controls.

## Maintenance And Expected-Change Mode

Users should be able to mark a circuit as intentionally changed after events such as:

- Replacing or servicing an appliance.
- Cleaning coils or filters.
- Moving loads between circuits.
- Seasonal HVAC startup.
- Known electrical work.

Maintenance mode should:

- Pause appliance-behavior notifications for that circuit.
- Preserve data-quality Repairs.
- Optionally clear learned baselines immediately or relearn after the maintenance window.
- Store a note and timestamp in diagnostics.

This prevents intentional changes from being treated as suspicious behavior.

## Sensitivity Presets

Each circuit should support simple sensitivity presets:

- `quiet`: fewer notifications, higher repeated-evidence threshold.
- `balanced`: default v1 conservative behavior.
- `sensitive`: lower threshold for users actively troubleshooting a circuit.

Presets should adjust alert policy thresholds, not core data-quality validation. Data-quality problems should still surface when configured sensors are missing, stale, invalid, or phase-mismatched.

## NILM Signature Review

Experimental NILM should expose a reviewable list of recurring signatures. Each signature should include:

- Signature id.
- Approximate W, VAR, VA, and PF deltas.
- Confidence.
- Event count.
- Last seen timestamp.
- Optional user label.
- Review state: `new`, `labeled`, `ignored`, `expected`, or `merged`.

Services should allow users to label, ignore, mark expected, or merge signatures. NILM should continue to use possible/unknown wording until a user confirms a label.

## Data Quality Checklist

Each circuit should expose a checklist-style diagnostic attribute set:

- Required sensors present.
- Optional sensors present.
- Numeric states valid.
- Units valid or normalized.
- Source data fresh.
- Voltage/current pairing plausible.
- CT direction plausible.
- Dual-phase pairing plausible, where applicable.
- NILM mains sources present, where applicable.

This checklist should be reflected in diagnostics export and should drive Repairs only when setup or source-data quality is blocking analysis.

## Dashboard Example

The dashboard example should expand into sections:

- Setup health.
- Learning progress.
- Circuit summaries.
- Active evidence.
- Power-quality diagnostics.
- Experimental NILM review.

It should remain standard Home Assistant YAML. No custom card dependency should be required for v1.

## False-Positive Feedback

Users should be able to mark an alert as expected or unhelpful. The integration should store feedback locally and use it to suppress repeated notifications for the same circuit and feature unless evidence materially changes.

Feedback should not erase evidence. Diagnostics should still show that a change was observed, but notification behavior can become quieter for that user and circuit.

## Services

Existing services remain:

- `relearn_baseline`
- `pause_alerts`
- `acknowledge_alert`
- `export_diagnostics`
- `run_mapping_checks`
- `label_nilm_signature`
- `ignore_nilm_signature`

New or expanded services should include:

- `set_circuit_sensitivity`
- `start_maintenance`
- `end_maintenance`
- `mark_alert_expected`
- `mark_alert_unhelpful`
- `mark_nilm_signature_expected`
- `merge_nilm_signatures`

## Entity Additions

Each circuit should expose additional diagnostics:

- `sensor.<circuit>_health_summary`
- `sensor.<circuit>_readiness`
- `sensor.<circuit>_learning_progress`
- `sensor.<circuit>_data_quality_checklist`
- `sensor.<circuit>_alert_evidence`
- `sensor.<circuit>_sensitivity`
- `binary_sensor.<circuit>_maintenance`

Existing power-quality diagnostic sensors remain:

- `sensor.<circuit>_power_quality_score`
- `sensor.<circuit>_power_quality_evidence`
- `sensor.<circuit>_reactive_power_drift`
- `sensor.<circuit>_apparent_power_drift`
- `sensor.<circuit>_power_factor_drift`

NILM circuits should expose review attributes through the existing NILM signature sensor and additional review state where useful.

## Storage

The integration-owned store should persist:

- Per-circuit sensitivity preset.
- Per-circuit maintenance state, note, timestamps, and relearn preference.
- Alert feedback keyed by circuit and feature.
- NILM signature review state, labels, ignores, expected markers, and merges.

Storage should remain compact and JSON-safe.

## Error Handling

If new UX state cannot be computed because source data is missing, the integration should prefer `needs_data` with checklist attributes over silent failure.

Services should validate circuit ids, alert ids, signature ids, and preset names. Invalid service calls should raise clear Home Assistant service validation errors.

Maintenance and false-positive feedback should never suppress Repairs for missing or invalid source sensors.

## Testing

Tests should cover:

- Readiness and learning-progress state for learning, ready, paused, needs-data, mixed, NILM review, and possible-issue cases.
- Health summary priority order.
- Alert evidence serialization and entity attributes.
- Data-quality checklist generation from valid and invalid source samples.
- Maintenance mode service behavior.
- Sensitivity preset threshold behavior.
- False-positive feedback suppression.
- NILM signature label, ignore, expected, and merge service behavior.
- Dashboard example references to supported entities.
- Diagnostics export includes the new UX state without leaking private source entity ids beyond existing diagnostics behavior.

## Non-Goals

This design does not add:

- A custom Lovelace card.
- Deep-learning NILM.
- Cloud analysis.
- Raw high-frequency sample retention.
- Definitive appliance failure diagnosis.
- ESPHome firmware changes.

