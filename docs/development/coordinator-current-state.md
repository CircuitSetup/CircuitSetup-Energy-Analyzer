# Coordinator Current State

Generated for the appliance-centered usability PR 1 audit.

Baseline commit: `f25ea915d275f4673667b9a7ec01b0b046980cc7`
Integration version: `0.10.5`

The generated codegraph found 176 files, 154 Python modules, 3623 symbols, 469
internal import edges, and 0 internal import cycles. `coordinator.py` is one of
the most connected modules, with 7 incoming and 47 outgoing internal edges.

The initial audit was completed before extraction. This branch now keeps the
public coordinator facade stable while delegating dashboard creation, evidence
actions, settings recommendations, entity profile changes, strict state update
reduction, recent observation state, grouped processor/context cleanup, runtime
metadata/latest-power/alert-evidence/recent-activity refresh, source
update lifecycle, source sample construction, processor ordering, store
persistence, setup-health aggregation, NILM workflows, and notification dedupe to focused managers. Further
coordinator thinning should keep lifecycle ownership in the coordinator while
moving remaining feature-specific behavior behind those managers.

## Responsibility Clusters

| Cluster | Current ownership | State/store fields | Home Assistant APIs | Tests / risk | Safe extraction target |
| --- | --- | --- | --- | --- | --- |
| Config and options interpretation | Coordinator init and config-entry helpers build circuits, sources, NILM, advanced settings, retention, detail level, weather/rain/water context | config entry data/options, advanced settings, circuit/source configs | config entry update/reload | Broad coverage in coordinator/config-flow tests; high risk because options migrations feed many surfaces | Pure config runtime helper, with HA update/reload left at coordinator boundary |
| Source entity subscription | `async_start`, `async_stop`, source listeners, pending source update cancellation/debounce | source state/freshness and pending update handles | event bus, state machine, async timers/listener cleanup | Reload/unload regressions are likely if duplicated | `SourceUpdateManager` |
| Sample normalization | Source-state lookup, parallel leg aggregation, demo source lookup, circuit sample creation | latest source states, source entity config, circuit configs | HA states | Medium risk; feeds every processor | sample/source builder helper |
| Context construction | Local time, weather, rain, water-flow, source mapping, contextual baseline inputs | context dictionaries and history by circuit | HA states, timezone | Medium risk; context bugs change alert semantics | `ProcessingContextBuilder` |
| Processor dispatch | Processor registry/order, per-circuit and cross-circuit processing, feature result collection | `AnalyzerState`, processor outputs | mostly none after sample/context are built | High risk because ordering is behavior | `ProcessingPipeline` |
| State update application | Dynamic `StateUpdate` path application, feature result updates, recent observation upsert/prune handling, grouped cleanup for processor/context mappings, metadata/latest-power refresh, relearn volatile-state reset, alert evidence payload refresh, and recent-activity timeline refresh | all `AnalyzerState` mapping roots, `recent_observations_by_circuit`, context state/store mappings | none | High risk; covered by strict-path, recent-observation, cleanup, metadata, alert-evidence, and timeline characterization tests | `StateReducer` |
| Alert feedback | Expected/unhelpful feedback, adjusted repeated counts, alert lookup/retirement, NILM appliance feedback | alert store, feedback store, active alerts | persistent notifications via notification helper | High user impact; stale IDs should stay friendly | `EvidenceActionController` |
| Settings recommendations | Recalculate/apply/undo/reset/dismiss recommendations and notification refresh | settings recommendation store and state mappings | config entry updates/reload | Medium/high risk because options and UI meet here | `SettingsController` |
| NILM actions | Label/assign/validate/reject/rename/profile/merge/publish/unpublish/retire/ignore/expected | NILM assignments, signatures, intervals, session history, virtual appliance state | services, entity refresh side effects | High risk; must preserve no automatic appliance creation | `NilmController` |
| Evidence panel actions/payloads | Alert evidence, no-evidence fallback, recommendation actions, NILM preview/workspace payloads | state, store alerts, NILM store, recommendations | HTTP views in `panel.py` | Medium risk; stale internal IDs are a user-facing failure | payload helpers plus `EvidenceActionController` |
| Dashboard creation | Preview/build/save/update, registry resolution, resource handling | circuit configs, entity registry state, dashboard status | entity registry, dashboard storage, resources | High UI risk, already heavily tested | `DashboardController` |
| Setup health aggregation | Setup Health state, checklist-ish issue aggregation, repair payloads | readiness/data-quality/source health state | repairs, persistent notifications | Medium risk; should become guided checklist later | `SetupHealthAggregator` |
| Repairs and notifications | Issue creation/dismissal, notification dedupe/copy | repair issue state, alert notification state | repairs, persistent notifications | Medium risk; wording/source labels matter | `NotificationController` plus existing helpers |
| Storage save/prune/migration | Dirty tracking, retention, prune, save scheduling, migration coordination | `FeatureStoreData` and store manager internals | HA storage helpers/timers | Medium risk; migrations are primary-agent-only | `StorePersistenceManager` |
| Entity profile and registry behavior | Simple/Standard/Expert desired entities, registry cleanup, compatibility behavior | entity metadata and registry entries | entity/device registries | High risk for existing users; fake-HA compatibility recently repaired | `EntityProfileController` |

## Current Public Facade To Preserve

Existing services and panel code call coordinator methods directly for alert
feedback, maintenance, dashboard creation/update, settings recommendations, NILM
workspace actions, and source processing. Later extraction should preserve these
public coordinator methods and delegate behind them instead of changing service
or panel contracts.

## Extraction Order Notes

Recommended later work should continue as grouped slices around related
behavior: context-source construction, UX-state refresh, demo-history seeding,
and Home Assistant lifecycle verification. The highest-risk boundary remains
state mutation, so new reducer moves should keep strict path validation and
focused tests.

## Branch Implementation Boundary

This branch adds appliance-centered read models and API payloads, plus the first
low-risk manager delegates. It does not move coordinator lifecycle methods,
storage migrations, or Home Assistant unload/reload ownership.
