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
`daily_energy_deltas` segments for cumulative kWh replay.
