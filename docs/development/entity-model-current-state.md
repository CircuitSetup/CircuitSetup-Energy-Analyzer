# Entity Model Current State

This document records the pre-compact entity model for PR 1 of the compact entity migration.

## Baseline

- Current implementation version: 0.9.1.
- Review baseline in the plan: `f0dee7a`.
- Worktree HEAD for this report: `d407f8af4e3be796822b8a1fce2996b0d24d8e13`.
- Current entity detail levels change registry enabled/hidden state; they do not change which per-circuit entities are constructed.

## Current Architecture

- Per-circuit entities use unique IDs shaped as `{entry_id}_{circuit_id}_{key}`.
- `sensor.py` is the largest surface, with summary, feature, and diagnostic tiers plus applicability gates by source role, circuit mode, profile, and stored/configured settings.
- `binary_sensor.py` has diagnostics for learning/data quality/maintenance, the summary `running` entity, and the feature `water_flow_mismatch` entity.
- `button.py`, `select.py`, and `number.py` expose controls but do not currently participate in tier-based creation. Buttons use daily-control applicability; `alert_sensitivity` is currently kept for every circuit, including mains.
- `SetupHealthSensor`, demo source sensors, and integration-wide global buttons/selects are outside per-appliance count targets.

## Replacement Coverage Notes

- Health Summary already carries bounded readiness, learning progress, data-quality problem, maintenance state, active alert count, and next step fields.
- Activity Summary already carries run-cycle status, count, runtime, duty cycle, standby status, and operating state fields.
- Electrical Health already carries metric consistency, leg imbalance, power-quality score/evidence, explanations, and first-check guidance.
- Energy Summary already carries energy, billing, and cost rollups, but later phases must add or preserve coverage for billing budget usage and current cost rate before removing those standalone entities.
- Sensitivity, last event, recent activity count, outdoor temperature, standby threshold, always-on values, and drift metrics should not be removed in later phases until the replacement surface is complete.

## Dashboard Dependency Notes

- The generated dashboard resolves entities by `(domain, entity_key)` and uses registry entity IDs when available, preserving user-renamed IDs.
- Current dashboard references include `activity_summary`, `electrical_health`, `energy_summary`, `daily_energy_usage`, mains balance keys, NILM keys, `outdoor_temperature`, `weather_context`, `run_cycle_runtime`, `run_cycle_duty_cycle`, `water_flow_correlation`, solar-flow keys, and utility comparison keys.
- Later compact phases must update the generated dashboard before removed keys disappear from the entity registry.

## Entity Description Inventory

| Domain | Key | Tier | Category | Applies | Enabled default | Visible default | Update frequency | Graphable | Tests | Replacement |
|---|---|---|---|---|---|---|---|---|---|---|
| sensor | `anomaly_score` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `last_event` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | Evidence panel or sensor.<circuit>_activity_summary |
| sensor | `health_summary` | summary |  | core/diagnostic baseline | yes | yes | coordinator update | no | tests/test_entities.py summary helper and attribute tests |  |
| sensor | `activity_summary` | summary |  | core/diagnostic baseline | yes | yes | coordinator update | no | tests/test_entities.py summary helper and attribute tests |  |
| sensor | `electrical_health` | summary |  | core/diagnostic baseline | yes | yes | coordinator update | no | tests/test_entities.py summary helper and attribute tests |  |
| sensor | `energy_summary` | summary |  | core/diagnostic baseline | yes | yes | coordinator update | no | tests/test_entities.py summary helper and attribute tests |  |
| sensor | `readiness` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_health_summary |
| sensor | `learning_progress` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_health_summary |
| sensor | `data_quality_checklist` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_health_summary |
| sensor | `energy_dashboard_status` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `alert_evidence` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | Evidence panel and sensor.<circuit>_health_summary |
| sensor | `recent_activity` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `recent_activity_count` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests | Evidence panel or optional recent activity timeline |
| sensor | `sensitivity` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | select.<circuit>_alert_sensitivity |
| sensor | `settings_suggestions` | feature |  | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `circuit_mode` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `power_flow` | diagnostic | diagnostic | core/diagnostic baseline | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `power_quality_score` | diagnostic | diagnostic | electrical metric roles | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `power_quality_evidence` | diagnostic | diagnostic | electrical metric roles | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_electrical_health |
| sensor | `reactive_power_drift` | diagnostic | diagnostic | matching drift metric role | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `apparent_power_drift` | diagnostic | diagnostic | matching drift metric role | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `power_factor_drift` | diagnostic | diagnostic | matching drift metric role | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `nilm_signature_count` | summary |  | mains NILM circuit | yes | yes | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `nilm_unknown_loads` | summary |  | mains NILM circuit | yes | yes | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `nilm_unmatched_load_percentage` | diagnostic | diagnostic | mains NILM circuit | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `nilm_topology_status` | diagnostic | diagnostic | mains NILM circuit | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `weather_context` | feature |  | HVAC profile with temperature source | no | yes | coordinator update | no | tests/test_entities.py weather context applicability tests |  |
| sensor | `outdoor_temperature` | feature |  | HVAC profile with temperature source | no | yes | coordinator update | yes | tests/test_entities.py weather context applicability tests | Configured outdoor temperature source entity |
| sensor | `rain_pump_correlation` | feature |  | pump profile with rain source | no | yes | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `water_flow_correlation` | feature |  | water profile with flow source | no | yes | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `water_flow_mismatch_minutes` | feature |  | water profile with flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `daily_energy_usage` | summary |  | energy source | yes | yes | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `energy_usage_share` | feature |  | energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `energy_usage_status` | feature |  | energy source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `energy_goal_usage` | feature |  | configured energy goal | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `energy_goal_status` | feature |  | configured energy goal | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `run_cycle_count` | feature |  | cyclic appliance with power/current | no | no | coordinator update | yes | tests/test_entities.py helper tests; tests/test_processors.py cycle tests |  |
| sensor | `run_cycle_runtime` | feature |  | cyclic appliance with power/current | no | no | coordinator update | yes | tests/test_entities.py helper tests; tests/test_processors.py cycle tests |  |
| sensor | `run_cycle_duty_cycle` | feature |  | cyclic appliance with power/current | no | no | coordinator update | yes | tests/test_entities.py helper tests; tests/test_processors.py cycle tests |  |
| sensor | `run_cycle_status` | diagnostic | diagnostic | cyclic appliance with power/current | no | no | coordinator update | no | tests/test_entities.py helper tests; tests/test_processors.py cycle tests | sensor.<circuit>_activity_summary |
| sensor | `current_demand` | feature |  | mains/high-power demand context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `peak_demand` | feature |  | mains/high-power demand context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `demand_limit_usage` | feature |  | mains/high-power demand context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `demand_peak_rank` | diagnostic | diagnostic | mains/high-power demand context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `demand_peak_status` | diagnostic | diagnostic | mains/high-power demand context | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `demand_status` | diagnostic | diagnostic | mains/high-power demand context | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `capacity_usage` | feature |  | configured capacity settings | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `capacity_status` | diagnostic | diagnostic | configured capacity settings | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `leg_imbalance` | diagnostic | diagnostic | dual-phase circuit | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `leg_imbalance_status` | diagnostic | diagnostic | dual-phase circuit | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_electrical_health |
| sensor | `metric_consistency_score` | diagnostic | diagnostic | metric consistency context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `metric_consistency_status` | diagnostic | diagnostic | metric consistency context | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests | sensor.<circuit>_electrical_health |
| sensor | `balance_power` | feature |  | mains balance context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `monitored_power` | feature |  | mains balance context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `monitored_coverage` | feature |  | mains balance context | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `balance_status` | diagnostic | diagnostic | mains balance context | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_generation_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_site_consumption_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_grid_import_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_grid_export_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_self_consumption` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_powered` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_flow_status` | feature |  | mains with solar-flow source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_surplus_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_load_shift_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_flexible_load_power` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_flexible_load_coverage` | feature |  | mains with solar-flow source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_load_shift_status` | feature |  | mains with solar-flow source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `solar_surplus_status` | feature |  | mains with solar-flow source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `utility_comparison_difference` | feature |  | utility comparison settings | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `utility_comparison_status` | feature |  | utility comparison settings | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `billing_cycle_usage` | feature |  | billing settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `billing_cycle_forecast` | feature |  | billing settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `billing_cycle_budget_usage` | feature |  | billing settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `billing_cycle_status` | feature |  | billing settings and energy source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `cost_current_rate` | feature |  | cost settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `cost_cycle` | feature |  | cost settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `cost_cycle_forecast` | feature |  | cost settings and energy source | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `cost_status` | feature |  | cost settings and energy source | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `always_on_power` | feature |  | standby-capable load | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `standby_threshold` | feature |  | standby-capable load | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests | Advanced Circuit Settings |
| sensor | `standby_status` | feature |  | standby-capable load | no | no | coordinator update | no | tests/test_entities.py description, helper, and applicability tests |  |
| sensor | `always_on_limit_usage` | feature |  | standby-capable load | no | no | coordinator update | yes | tests/test_entities.py description, helper, and applicability tests |  |
| binary_sensor | `learning` | diagnostic | diagnostic | all configured circuits | no | no | coordinator update | no | tests/test_entities.py binary defaults/applicability tests |  |
| binary_sensor | `data_quality_problem` | diagnostic | diagnostic | all configured circuits | no | no | coordinator update | no | tests/test_entities.py binary defaults/applicability tests |  |
| binary_sensor | `maintenance` | diagnostic | diagnostic | all configured circuits | no | no | coordinator update | no | tests/test_entities.py binary defaults/applicability tests | switch.<circuit>_maintenance |
| binary_sensor | `running` | summary |  | supported appliance profile with real power | yes | yes | coordinator update | no | tests/test_entities.py binary defaults/applicability tests |  |
| binary_sensor | `water_flow_mismatch` | feature |  | water profile with global or linked flow source | no | yes | coordinator update | no | tests/test_entities.py binary defaults/applicability tests |  |
| button | `relearn_baseline` | control |  | daily control circuits | yes | yes | user action | no | tests/test_control_entities.py control setup tests |  |
| button | `start_maintenance` | control |  | daily control circuits | yes | yes | user action | no | tests/test_control_entities.py control setup tests | switch.<circuit>_maintenance |
| button | `end_maintenance` | control |  | daily control circuits | yes | yes | user action | no | tests/test_control_entities.py control setup tests | switch.<circuit>_maintenance |
| button | `pause_alerts` | control |  | daily control circuits | yes | yes | user action | no | tests/test_control_entities.py control setup tests |  |
| select | `alert_sensitivity` | control |  | all configured circuits | yes | yes | user action | no | tests/test_control_entities.py control setup tests |  |
| number | `daily_energy_goal` | control |  | circuits with usable cumulative energy evidence | yes | yes | user action | no | tests/test_control_entities.py control setup tests |  |

## Global Entities Outside Per-Circuit Counts

| Domain | Key | Unique ID pattern | Notes |
|---|---|---|---|
| sensor | `setup_health` | `{entry_id}_setup_health` | integration-wide setup health sensor |
| button | `run_mapping_checks` | `{entry_id}_run_mapping_checks` | integration-wide action button |
| button | `recalculate_suggestions` | `{entry_id}_recalculate_suggestions` | integration-wide action button |
| select | `entity_detail_level` | `{entry_id}_entity_detail_level` | integration-wide detail profile control |
| select | `dashboard_layout` | `{entry_id}_dashboard_layout` | integration-wide recommended-dashboard layout control |

## Representative Count Baseline

| Scenario | Simple created | Standard created | Expert created | Simple enabled | Standard enabled | Expert enabled |
|---|---:|---:|---:|---:|---:|---:|
| refrigerator | 55 | 55 | 55 | 12 | 32 | 55 |
| washer | 58 | 58 | 58 | 12 | 35 | 58 |
| dryer_dual_phase | 63 | 63 | 63 | 12 | 35 | 63 |
| hvac | 67 | 67 | 67 | 12 | 38 | 67 |
| water_heater | 66 | 66 | 66 | 12 | 39 | 66 |
| ev_charger | 61 | 61 | 61 | 12 | 33 | 61 |
| sump_pump_with_rain | 62 | 62 | 62 | 12 | 36 | 62 |
| water_pump_with_flow | 65 | 65 | 65 | 12 | 39 | 65 |
| solar_inverter | 47 | 47 | 47 | 7 | 27 | 47 |
| mains_nilm | 73 | 73 | 73 | 9 | 44 | 73 |
| mixed_circuit | 44 | 44 | 44 | 7 | 24 | 44 |
