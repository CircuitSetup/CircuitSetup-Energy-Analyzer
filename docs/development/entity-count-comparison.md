# Entity Count Comparison

This report compares the pre-compact entity inventory with compact creation rules for the `all_applicable_optional_settings` scenario variant.

| Scenario | Before created | Simple | Standard | Expert, no groups | Expert, all groups |
|---|---:|---:|---:|---:|---:|
| refrigerator | 55 | 10 | 14 | 14 | 39 |
| washer | 58 | 10 | 16 | 16 | 42 |
| dryer_dual_phase | 63 | 10 | 15 | 15 | 46 |
| hvac | 67 | 10 | 17 | 17 | 49 |
| water_heater | 66 | 10 | 17 | 17 | 50 |
| ev_charger | 61 | 10 | 16 | 16 | 45 |
| sump_pump_with_rain | 62 | 10 | 15 | 15 | 46 |
| water_pump_with_flow | 65 | 10 | 17 | 17 | 49 |
| solar_inverter | 47 | 7 | 11 | 11 | 34 |
| mains_nilm | 73 | 7 | 10 | 10 | 50 |
| mixed_circuit | 44 | 7 | 11 | 11 | 31 |

## Acceptance Summary

- Simple maximum: 10 per-circuit entities.
- Standard maximum: 17 per-circuit entities.
- Expert without selected groups stays at 17 per-circuit entities and does not recreate the full historical diagnostic surface.
- Expert with every group selected stays at 50 per-circuit entities.
- The compact model keeps `select.<circuit>_alert_sensitivity` as the canonical sensitivity control and replaces legacy maintenance buttons with `switch.<circuit>_maintenance`.
