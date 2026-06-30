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
| `StateReducer` | `managers/state_reducer.py` | Strict dynamic `AnalyzerState` path updates used by processor results |

Each extracted manager has focused unit tests plus existing coordinator/service
tests to verify the facade remains compatible.

## Staged Managers

The following targets remain staged because they touch lifecycle, storage, or
NILM state with higher regression risk:

- `SourceUpdateManager`: source subscriptions, pending updates, listener cleanup.
- `ProcessingContextBuilder`: local time, weather/rain/water context, source maps.
- `ProcessingPipeline`: processor ordering and per/cross-circuit dispatch.
- `StorePersistenceManager`: dirty tracking, retention, prune, migration saves.
- `SetupHealthAggregator`: setup checklist and repair payload aggregation.
- `NilmController`: signature/session/assignment actions and publication.
- `NotificationController`: persistent notification copy, dedupe, and links.

## Compatibility Rules

- Keep public coordinator method names and argument shapes.
- Keep Home Assistant lifecycle methods on the coordinator.
- Managers may call existing coordinator private helpers during this split.
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

Existing coordinator, services, dashboard, and control-entity tests still cover
the public facade.
