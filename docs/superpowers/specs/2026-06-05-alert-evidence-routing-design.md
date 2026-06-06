# Alert Evidence Dynamic Panel Design

## Goal

Make notification evidence links open a dynamic Home Assistant page that shows
the specific graph and evidence for the alert that the user clicked.

## Problem

The integration can already attach `alert_id`, `circuit_id`, and `feature`
parameters to notification links, and it can expose graph metadata on
`sensor.<circuit>_alert_evidence`. Standard Lovelace dashboard cards do not use
URL query parameters to change the entities shown in a history graph. A static
dashboard therefore cannot reliably show the graph for the notification that was
clicked.

## Recommended Design

Build an integration-owned custom Home Assistant panel as the primary evidence
surface.

The notification link should point to:

`/circuitsetup-energy-analyzer-evidence?alert_id=<id>&circuit_id=<id>&feature=<feature>`

This path intentionally does not reuse `/circuitsetup-energy-analyzer` because
users may already have a Lovelace dashboard at that URL.

The panel should:

- Read the URL query parameters.
- Fetch a JSON evidence payload from the integration backend.
- Show the alert message, severity, circuit, feature, observed value, baseline
  value, percent change, repeated count, first seen, last seen, and source
  entities.
- Render a graph using the returned `graph_entities` and graph window.
- Explain whether the displayed alert is an exact alert ID match, a fallback to
  the latest evidence for the requested circuit, or unavailable.
- Offer alert feedback actions: Acknowledge, Mark Expected, and Mark Unhelpful.

The existing Lovelace dashboard example remains useful as a fallback and as a
general overview, but it is no longer the primary notification destination.

## Backend Design

Add a focused frontend/panel module for the integration.

Responsibilities:

- Register static frontend assets served by the integration.
- Register the custom panel route.
- Register an authenticated HTTP endpoint that returns alert evidence JSON.
- Resolve alert evidence by `alert_id` first, then by `circuit_id`, then return
  an unavailable payload when nothing matches.

The payload should be JSON-safe and should include:

- `status`: `matched_alert`, `latest_for_circuit`, or `not_found`.
- `alert`: the alert evidence detail returned by existing UX helpers, when
  available.
- `circuit`: display metadata for the circuit config, when available.
- `actions`: service names and data needed by the frontend buttons.

## Frontend Design

Create a dependency-free JavaScript module under the integration directory. It
should define a custom panel element that Home Assistant can load as a module.

The panel should use normal browser APIs and the Home Assistant `hass` object
available to custom panels. It should:

- Parse `window.location.search`.
- Call the integration evidence endpoint.
- Render a clear diagnostic page with sections for Summary, Evidence, Graph,
  Source Entities, and Actions.
- Render the graph by embedding the built-in Home Assistant history panel URL or
  by using Home Assistant frontend history components when available. For V1,
  the embedded history URL is acceptable because it is dynamic, authenticated,
  and can be built from the selected entity IDs.
- Use accessible buttons and plain text labels.
- Call integration services through `hass.callService`.

## Link Rules

- Keep existing query parameters: `alert_id`, `circuit_id`, and `feature`.
- Default notification links to `/circuitsetup-energy-analyzer-evidence`.
- Preserve a dashboard fallback path constant for README/dashboard examples.
- Do not generate per-circuit static routes as the primary behavior.

## Error Handling

- If `alert_id` is missing but `circuit_id` is present, show latest evidence for
  that circuit.
- If an old notification references an alert that is no longer retained, show a
  clear "historical alert not found" message and any latest evidence available
  for the circuit.
- If graph entities are missing, show the evidence text and source entities
  instead of an empty graph.
- If the backend endpoint is unavailable, show a retry button and the request
  path that failed.

## Testing

Tests should cover:

- Notification links point to the dynamic evidence panel path.
- Alert evidence paths preserve `alert_id`, `circuit_id`, and `feature`.
- Backend payload resolution returns exact alert ID matches.
- Backend payload resolution falls back to latest circuit evidence.
- Backend payload resolution returns `not_found` for unknown alerts/circuits.
- Panel/static asset registration is idempotent and unload-safe.
- The JavaScript asset contains the custom element, URL parsing, endpoint fetch,
  graph rendering, and alert feedback service calls.
- Existing dashboard tests continue to pass as fallback documentation.

## Rollout

This change is backwards compatible for entity data and services. New
notifications should open the dynamic panel. Existing dashboard links still work,
but README and blueprint examples should guide users toward the dynamic evidence
panel as the better default.
