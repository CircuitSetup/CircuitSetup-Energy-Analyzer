# Appliance Comparison Semantics

## Audit Finding

At `f66df7a`, all Appliance Detail comparisons use one generic operation:
compare the current scalar with one baseline range. That is unsafe for
partial-day energy, runtime, run count, and cost; current versus peak demand;
instantaneous capacity; and running versus idle power.

## Modes

Every comparison declares one of these modes:

- `same_time_of_day`: measured from local midnight through `as_of`, compared
  only with prior local days at the same progress bucket.
- `full_period_observed`: a completed measured period compared with completed
  periods.
- `projected_end_of_period`: an explicitly estimated end value, never labeled
  as measured.
- `current_state`: an instantaneous value and its current-context limits.
- `running_state`: instantaneous power compared only with learned running power.

## Daily Metrics

Energy, runtime, run count, and cost expose:

- observed so far;
- expected range by the same local-day progress bucket;
- projected end of day when both expected-so-far and completed-day history are
  adequate;
- normal completed-day range;
- an explanation when history is insufficient.

The current local date is never part of its own baseline. Legacy full-day
baselines are not reinterpreted as same-time baselines. Projections carry lower
confidence than observed comparisons and remain unavailable when the progress
denominator is too small or source gaps make extrapolation misleading.

## Power, Demand, And Capacity

- Running direct appliances compare with a running-power baseline.
- Idle/off appliances compare with an idle or standby baseline.
- Mixed circuits do not make appliance-specific running-power claims.
- Demand presents current demand, today's measured peak, normal peak by the
  same time, and configured limit as separate concepts.
- Capacity presents current usage and configured warning/maximum thresholds;
  unavailable current is not converted to zero.

## Cost And Currency

Daily cost is the accumulated sum of each measured energy delta multiplied by
the tariff active for that delta. A gap crossing midnight or a tariff boundary
is unavailable or explicitly approximate unless history can allocate it.

Currency is Home Assistant's configured ISO currency code and is formatted by
the frontend with `Intl.NumberFormat`. No code or translation hardcodes `$`.

## Confidence

Observed confidence reflects data freshness and baseline sample quality.
Projection confidence is capped below its observed comparison. Missing,
stale, mixed-context, or insufficient history produces a friendly explanation
instead of a directional claim.

## Compatibility

The Appliance Detail API remains additive: existing scalar and range fields stay
available while mode, `as_of`, projections, completed-period ranges, and
explanations are added. Existing panel/API paths and entity IDs do not change.
