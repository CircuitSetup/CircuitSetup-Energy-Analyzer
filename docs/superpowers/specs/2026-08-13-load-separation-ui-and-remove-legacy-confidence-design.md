# Load Separation UI Cleanup and Typed NILM Confidence Removal

**Status:** Approved for implementation

## Goal

Make the Load Separation/NILM workspace consistent and readable across session, edge, validation, publication, helper-circuit, and technical-detail sections, while removing the obsolete `legacy_mixed` confidence semantic from runtime data, user-facing text, and tests.

## Scope and decisions

The change is limited to the NILM workspace presentation and the confidence-semantic paths that feed it or other user-facing NILM surfaces. Existing typed semantics remain authoritative:

- sessions use `pairing_confidence`;
- signatures use `evidence_strength`;
- assignments use `feedback_evidence_score` when auditable feedback exists;
- assignment/model quality can use `model_fit` where that typed value is available.

The generic legacy assignment confidence is not a fallback for publication readiness, notifications, appliance detail, or workspace labels. Records without a typed confidence source do not receive a replacement generic label. The unrelated `legacy_mixed` circuit/profile fixture identifiers are test data names, not the confidence semantic, and are out of scope.

Historical stored records are normalized on load into the typed fields that can be inferred safely: signature `confidence` becomes `evidence_strength`, session `confidence` becomes `pairing_confidence`, and assignment feedback events retain typed `score_after` values while dropping `legacy_confidence_after`. An assignment with no auditable feedback score loses the obsolete generic confidence instead of being relabeled.

## UI behavior

### NILM Sessions

- Render the session title, formatted local start/end times, estimated-by-NILM line, and pairing-confidence line using the same semantic structure and formatting as Session Validation.
- Start and end timestamps render as separate lines when both exist. Open sessions show the formatted start and the existing open indicator.
- Do not put pairing confidence into the bold power header.

### NILM Edges

- Render the formatted local timestamp below the direction/power header.
- Display delta watts with at most two fractional digits.
- Remove the raw split-phase/voltage field that currently displays `unknown` for most edges.
- Render dominant-leg information only when the workspace source is Mains NILM. Preserve a meaningful “No dominant leg” state for Mains edges with no value; single-phase/non-Mains workspaces omit the field entirely.

### Session Validation

- Keep the existing typed pairing-confidence presentation.
- For an open session, render only the power portion of the summary; never render an estimated kWh value for an open session.
- Completed sessions retain the power and estimated-energy summary.

### Published interval inspector

- Render “Median power error” and “Energy error” as separate lines.
- Render “Publication readiness” with its status and no “Reason” line.
- Keep the publication-gates disclosure expanded by default.
- Remove the separate unavailable-publication reason paragraph.
- Add a short Helper circuit evidence description explaining that a helper is a separately monitored circuit used to corroborate timing/attribution and is not added to the NILM source estimate.
- Change the unassigned helper selector label to “Choose a helper circuit”.

### Technical-detail grouping and controls

- Keep “Sessions, validation, and technical details” as the containing section.
- Move both “Uncertain events” and “Evidence quality and attribution” into that section.
- Style “Review uncertain events” with the same disclosure-summary treatment used by “Evidence quality and attribution”, while preserving its existing lazy loading, focus restoration, and accessibility behavior.

## Implementation boundaries

- `frontend/energy-analyzer-nilm-workspace.js` owns the session, edge, validation, publication, helper, ambiguity, and section-composition changes.
- `frontend/energy-analyzer-appliance-views.js` and `frontend/energy-analyzer-evidence-views.js` stop using legacy confidence labels/fallbacks and select typed labels only.
- `panel_nilm.py`, `nilm.py`, `nilm_virtual.py`, `appliance_detail.py`, `managers/nilm_controller.py`, and `nilm_confidence.py` remove legacy semantic defaults, compatibility mirrors, and user-facing fallback text while preserving typed confidence calculations.
- `translations/en.json` removes legacy strings and adds the separate error/helper-description/session-rendering copy.
- `panel_contracts.py::PANEL_MODULE_VERSION` is bumped for shipped frontend changes.
- No new dependency or persistence schema is introduced; the existing load-time migration is tightened to remove obsolete fields and preserve safely inferable typed data.

## Testing strategy

- Add/update Node-render tests for formatted session rows, separate timestamps, open-session energy omission, edge formatting/topology gating, separate assignment error lines, expanded publication gates, helper copy, disclosure styling, technical-detail placement, and absence of legacy confidence text.
- Update Playwright tests for Mains versus single-phase edge metadata, published-inspector copy/expansion, technical-detail placement, and no `legacy_mixed` UI output.
- Update Python tests for migration behavior, readiness not falling back to generic confidence, notification/appliance-detail copy, panel labels, entity attributes, and removal of legacy event fields.
- Run targeted tests first, then the repository verification commands: `rtk git diff --check`, `rtk ruff check .`, `rtk pytest -q`, and the frontend Playwright suite relevant to the changed workspace.

## Acceptance criteria

1. Every requested Load Separation presentation change is visible in the rendered workspace and covered by a regression assertion.
2. No runtime or user-facing confidence path emits `legacy_mixed`, “Legacy confidence (mixed semantics)”, or `legacy_confidence_after` outside unrelated fixture identifiers.
3. Typed confidence fields continue to drive their existing displays and gates.
4. Open sessions never show kWh in Session Validation.
5. Publication gates are expanded by default and no publication “Reason” line is rendered.
6. The changed frontend asset is cache-busted by a bumped panel module version.
