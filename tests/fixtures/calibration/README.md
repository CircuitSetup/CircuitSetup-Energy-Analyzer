# Confidence Calibration Fixtures

These fixtures replay synthetic CircuitSetup Energy Analyzer samples through
the processor-level calibration harness. Keep them small, deterministic, and
safe for CI.

Do not commit raw private household energy logs. Strip entity names that
identify people or addresses, use relative timestamps where possible, aggregate
to reviewable intervals, and remove account IDs, utility numbers, GPS data,
device serial numbers, and other private identifiers. Prefer synthetic or
anonymized data for public tests.

Each fixture has `schema_version: 1`, one or more circuit definitions, replay
samples or deterministic segments, ground-truth labels, and calibration
expectations. The first harness supports explicit samples plus
`daily_energy_deltas` segments for cumulative kWh replay and
`cold_storage_signature` segments for fixed-interval refrigerator/freezer
PF, real-power, and current pulses.

Mixed-load fixtures may add `source_kind` and `labels.component_truth`. Component
truth is keyed by assignment ID and may contain bounded expected `edges`,
`sessions`, and `energy_kwh`. Metrics are derived from replay output; fixtures
without component truth retain the original report format.

A `cold_storage_signature` segment requires `start_t`, `duration_seconds`,
`sample_interval_seconds`, `excursion_interval_seconds`, `base_power_w`,
`base_current_a`, `base_power_factor`, `excursion_power_w`,
`excursion_current_a`, and `excursion_power_factor`. The circuit must provide
`power`, `current`, and `power_factor` sources.
