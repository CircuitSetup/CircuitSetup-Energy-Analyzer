# Appliance Usability Test Matrix

Generated for the appliance-centered usability PR 1 audit.

Baseline commit: `f25ea915d275f4673667b9a7ec01b0b046980cc7`
Integration version: `0.10.5`

This matrix tracks the appliance-centered workflow covered by the appliance
story branch. The branch implements the read models, panel payloads, dashboard
story sections, NILM review lanes, setup checklist, advanced setting
explanations, targeted frontend modularization, and the first coordinator
manager extractions.

| Area | Scenario | Current coverage | Implemented coverage | Remaining risk |
| --- | --- | --- | --- | --- |
| Direct appliance detail | Direct circuit exposes one detail payload | Summary entities exist separately | API returns one payload by `circuit_id`; tests cover source, missing data, actions, and evidence path | Visual browser QA still needed in a live HA panel |
| NILM appliance detail | Estimated appliance exposes one detail payload | NILM virtual attrs expose source/confidence | API returns one payload by `assignment_id`; payload is estimated, includes confidence and workspace path | Visual browser QA still needed in a live HA panel |
| Source clarity | User can tell direct vs estimated | Clear for NILM, implicit for direct | `source_type` and source labels are present in appliance detail, NILM workspace, dashboard data, and notifications | Badge styling can be refined after browser screenshots |
| Confidence | Confidence only appears when meaningful | Mostly NILM/settings | Direct payload omits confidence; NILM payload includes it; low-confidence expectations ask for validation | UI confidence badges need live screenshot review |
| Now | Current activity and power are visible | Activity Summary plus numeric sensors | Detail payload includes activity state and current power | None known |
| Today | Daily energy/runtime/run count/cost are visible | Energy and activity summaries separately | Detail payload includes available daily energy, runtime, run count, and cost | Solar-covered share is shown only where existing state provides it |
| Today vs Normal | User sees normal band | Alert evidence only | Comparison model classifies normal/higher/lower/learning/missing data | Visual bar marker is data-ready but still simple in generated dashboard |
| Behavior expectations | User sees expected vs possible issue | Summary and evidence wording | Initial recipes cover fridge/freezer, HVAC, pumps, NILM validation, maintenance, data quality, and electrical issues | Recipe depth can expand without changing payload shape |
| What changed | User sees observed vs baseline | Alert evidence only | Active alert summaries and comparison statuses explain changes | Watchlist copy can be tuned after live usage |
| What to check first | User gets first action | Electrical Health and setup health | Detail payload and expectations include bounded first-check lists | None known |
| Actions | User acts without typing IDs | Evidence actions use service payloads | Detail/NILM/recommendation actions carry internal IDs in payloads | Live panel smoke still required |
| Dashboard | Generated dashboard uses registry IDs | Existing tests cover registry-first behavior | Overview, Today, Behavior Watchlist, run timeline, NILM review, and preflight data are generated | Visual dashboard screenshots still pending |
| NILM workspace | User reviews signatures/sessions | Existing workspace payload/actions | Workspace payload includes lanes, card explanations, selection guidance, estimated source language, and assignment detail links | Graph interaction needs live browser QA |
| Setup checklist | Guided onboarding | Setup Health summary/repairs | Setup Health attributes include a bounded checklist with compact storm-mode serialization | Checklist is not yet a dedicated panel route |
| Advanced settings | Current/default/suggested explanations | Recommendations and options flow | Recommendation payloads include current/default/suggested values, what controls, why, expected effect, reset action | Full options-flow visual QA still pending |
| Coordinator split | Smaller coordinator | Audit only | Dashboard, evidence actions, settings, entity profile, and state reducer are manager-backed with focused tests | Source updates, processing pipeline, persistence, NILM, notification, and setup health managers remain staged |
| HA lifecycle | Install/reload/unload do not traceback | Unit and HA tests exist | `tests_homeassistant` is the current disposable-HA gate for this branch | Full browser-driven install/configure workflow remains a known limitation |

## Focused Test Targets

- Direct appliance detail exists for a configured circuit.
- NILM virtual appliance detail exists for an assignment.
- Source type is explicit.
- Confidence is present for NILM and omitted for direct appliances.
- Missing data returns friendly `null` fields and a next step.
- Direct appliance evidence path uses `circuit_id`.
- NILM appliance evidence/workspace path uses `assignment_id` and mains context.
- Actions are service/navigation payloads, not typed internal-ID instructions.

## Deferred Test Targets

- Browser screenshots for dashboard and panel routes.
- Full Home Assistant install/configure dashboard workflow.
- Deeper coordinator source/pipeline/persistence extractions.
