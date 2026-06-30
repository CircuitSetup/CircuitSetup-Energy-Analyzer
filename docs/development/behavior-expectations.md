# Behavior Expectations Design

Milestone: Behavior Expectations and Today vs Normal.

## Goal

Translate existing analyzer state into plain-language appliance expectations.
This layer should explain whether behavior is expected, worth watching, a
possible issue, or not yet supported by enough data.

## Data Sources

Expectation recipes should use existing analyzer outputs:

- activity and run-cycle state;
- daily energy usage evidence;
- electrical health, capacity, demand, and leg imbalance state;
- weather context for HVAC;
- rain and water-flow context for pumps, water heaters, and washers;
- setup/data-quality state;
- maintenance state;
- active alert evidence;
- NILM assignment confidence and validation state.

The layer must not duplicate processor algorithms. It should interpret existing
state and evidence.

## Initial Semantics

Statuses:

- `ok`: observed behavior looks normal.
- `watch`: review soon, but do not imply a fault.
- `possible_issue`: existing evidence indicates a likely problem.
- `expected`: context explains the behavior.
- `not_enough_data`: analyzer is still learning or source data is absent.
- `not_applicable`: the recipe does not apply to this appliance/source.

Source types:

- direct metered expectations use `direct_meter`.
- NILM expectations use `nilm_estimate` and should include confidence.

## Recipe Priorities

1. Maintenance state suppresses fault language.
2. Data-quality/setup gaps produce `not_enough_data`.
3. NILM low confidence produces validation guidance, not appliance fault alerts.
4. Context explanations such as hot weather or rain can convert watch conditions
   into `expected`.
5. Electrical safety and capacity signals may still produce `possible_issue`.

## Today vs Normal

Metric comparisons should prefer contextual baselines when available, then fall
back to stored `BaselineStats`. A comparison is shown only when both the current
value and a meaningful normal range exist; otherwise the status is `learning` or
`missing_data`.

## Initial Implementation

The branch implements the first read-model version in `appliance_detail.py`.
It covers direct appliances and NILM virtual appliances, produces bounded
expectations for the highest-signal current condition, and exposes Today vs
Normal metric comparisons for energy, runtime, run count, and current power
when baselines exist. Remaining recipe expansion stays staged so later PRs can
add richer appliance-specific timelines and panel visuals without changing the
public payload contract again.
