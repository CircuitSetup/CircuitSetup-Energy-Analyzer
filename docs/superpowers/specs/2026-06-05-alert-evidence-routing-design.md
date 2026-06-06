# Alert Evidence Routing Design

## Goal

Make notification evidence links land on the graph context for the appliance or
circuit that produced the alert. The V1 implementation should work with standard
Home Assistant dashboard YAML, preserve the current alert evidence attributes,
and avoid claiming that Lovelace cards can dynamically swap content from URL
query parameters when they cannot.

## Problem

The integration now adds `alert_id`, `circuit_id`, and `feature` query
parameters to notification links. Home Assistant preserves those parameters in
the browser URL, but standard Lovelace cards do not use them to choose entities.
That means a notification for a water heater, refrigerator, washer, dryer, or
other circuit can open the Alert Evidence view while still showing a graph that
was manually written for HVAC.

## Recommended V1 Design

Use per-circuit Alert Evidence dashboard views.

Notification links should prefer a circuit-specific path:

- `/circuitsetup-energy-analyzer/alert-evidence-hvac`
- `/circuitsetup-energy-analyzer/alert-evidence-water-heater`
- `/circuitsetup-energy-analyzer/alert-evidence-refrigerator`
- `/circuitsetup-energy-analyzer/alert-evidence-washer`
- `/circuitsetup-energy-analyzer/alert-evidence-dryer`

Each path still includes the existing query parameters:

- `alert_id`
- `circuit_id`
- `feature`

The general `/circuitsetup-energy-analyzer/alert-evidence` view remains a
fallback and index for users who have not added per-circuit sections.

## Data Flow

1. Analyzer creates or refreshes an `AlertEvidence` object.
2. Alert evidence details continue to populate `sensor.<circuit>_alert_evidence`
   attributes, including `alert_id`, `feature`, `graph_entities`,
   `source_entities`, `graph_window_start`, and `graph_window_end`.
3. The evidence path helper slugifies the circuit ID and builds a route like
   `/circuitsetup-energy-analyzer/alert-evidence-<circuit-slug>?alert_id=...`.
4. Persistent notifications and the alert blueprint use that path.
5. The dashboard sample contains matching per-circuit views with the relevant
   Alert Evidence entity and graph cards.

## Dashboard Behavior

The dashboard sample should include:

- A general `Alert Evidence` view at `path: alert-evidence`.
- One appliance-focused view per demo circuit.
- A small index/list on the general view that explains the per-circuit evidence
  views and links to them.
- Per-circuit graph cards for the entities that are most useful for that
  appliance type.

Because standard dashboard YAML cannot read URL query parameters, the graph card
entities are static within each per-circuit view. The query parameters remain
valuable for evidence attributes, blueprint actions, browser context, and future
custom frontend work.

## Link Rules

- Slug circuit IDs with lowercase letters, digits, and hyphens.
- Convert underscores, spaces, and punctuation to hyphens so route segments
  contain only lowercase letters, digits, and hyphens.
- Keep the existing query parameters intact.
- Fall back to `/circuitsetup-energy-analyzer/alert-evidence` if a caller
  explicitly disables per-circuit routing or a blank circuit ID is encountered.

## Testing

Tests should cover:

- Alert evidence paths route to `alert-evidence-<circuit-slug>`.
- Query parameters still include alert ID, circuit ID, and feature.
- Circuit IDs with spaces, underscores, and punctuation create safe paths.
- The dashboard example contains a general Alert Evidence view and matching
  per-circuit views for the demo circuits.
- The dashboard example no longer hard-codes only HVAC as the evidence graph
  destination.
- Existing alert evidence attributes and notification message tests continue to
  pass.

## Rollout

This is a backwards-compatible dashboard and notification-link improvement.
Existing notifications that point at `/alert-evidence` still open the general
view. New notifications should route to per-circuit views. Users with customized
dashboards can either import the updated sample or create matching view paths for
their configured circuits.
