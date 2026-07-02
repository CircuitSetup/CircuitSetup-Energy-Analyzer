# Coordinator Split Plan

Branch: `feature/appliance-story-usability`
Baseline commit: `f25ea915d275f4673667b9a7ec01b0b046980cc7`

## Goal

Keep `EnergyAnalyzerCoordinator` as the Home Assistant lifecycle facade while
moving user-facing workflows and strict state mutation into smaller managers.
Public coordinator methods remain stable for services, entities, and the panel.

## Extracted In This Branch

| Manager | File | Coordinator methods / behavior |
| --- | --- | --- |
| `DashboardController` | `managers/dashboard_controller.py` | `async_create_dashboard`, `async_remove_dashboard`, `async_set_dashboard_layout` |
| `EvidenceActionController` | `managers/evidence_actions.py` | `async_pause_alerts`, `async_acknowledge_alert`, maintenance start/end, alert feedback, NILM alert feedback |
| `SettingsController` | `managers/settings_controller.py` | Recalculate/apply/undo/reset/deny/dismiss advanced setting recommendations |
| `EntityProfileController` | `managers/entity_profile_controller.py` | `async_set_entity_detail_level` |
| `StateReducer` | `managers/state_reducer.py` | Strict dynamic `AnalyzerState` path updates, feature-result observation recording, recent observation pruning, grouped cleanup for processor/context state, and runtime state refresh for metadata, latest power, alert evidence, and recent activity |
| `SourceSampleBuilder` | `managers/source_samples.py` | Source-state lookup, demo source registry fallback, and normalized circuit sample assembly |
| `SourceUpdateManager` | `managers/source_updates.py` | Source subscriptions, pending updates, listener cleanup, and compatibility accessors |
| `ProcessingContextBuilder` | `managers/context.py` | Runtime processor context assembly and Home Assistant timezone lookup |
| `ProcessingPipeline` | `managers/processing_pipeline.py` | Established per-circuit and cross-circuit processor ordering |
| `StorePersistenceManager` | `managers/store_persistence.py` | Dirty tracking, retention pruning, and gated store saves |
| `SetupHealthAggregator` | `managers/setup_health.py` | Setup-health repair/data-quality issue aggregation |
| `NilmController` | `managers/nilm_controller.py` | Signature/session/assignment actions, virtual appliance state, and publication |
| `NotificationController` | `managers/notification_controller.py` | Persistent notification dedupe/copy and settings-recommendation notification episodes |

Each extracted manager has focused unit tests plus existing coordinator/service
tests to verify the facade remains compatible.

## Staged Extraction

The following targets remain staged because they touch lifecycle ownership,
feature semantics, or Home Assistant reload behavior:

- Broaden `ProcessingContextBuilder` only after characterizing weather, rain,
  water-flow, and source-map inputs.
- Keep Home Assistant lifecycle entrypoints (`async_start`, `async_stop`,
  unload/reload-facing ownership) on the coordinator.
- Continue thinning coordinator-private feature helpers behind existing managers
  in grouped slices with focused tests.

## Compatibility Rules

- Keep public coordinator method names and argument shapes.
- Keep Home Assistant lifecycle methods on the coordinator.
- Managers should use public coordinator facades or injected dependencies, not
  coordinator private helpers.
- Move high-risk internals only with characterization tests first.
- Keep state path validation strict; unknown roots and intermediate key creation
  must continue to raise.

## Current Verification

Focused manager tests:

- `tests/test_dashboard_controller.py`
- `tests/test_evidence_actions_controller.py`
- `tests/test_settings_controller.py`
- `tests/test_entity_profile_controller.py`
- `tests/test_state_reducer.py`
- `tests/test_source_sample_builder.py`
- `tests/test_setup_health_manager.py`
- `tests/test_notification_controller.py`

Existing coordinator, services, dashboard, and control-entity tests still cover
the public facade.
