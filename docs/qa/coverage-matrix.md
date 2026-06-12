# QA Coverage Matrix

Date: 2026-06-12
Status key: Pass, Fail, Partial, Blocked, Not run

## Matrix

| Area | Code Location | Existing Automated Tests | Missing Tests / Gaps | Manual HA Steps | Expected Result | Actual Result | Logs Checked | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Manifest and platform declaration | `custom_components/circuitsetup_energy_analyzer/manifest.json`, `const.py` | `tests/test_entities.py`, `tests/test_services.py`, `tests/test_user_facing_text.py` | Runtime platform forwarding in supported HA server | Start HA with copied custom component | Domain loads and forwards `sensor`, `binary_sensor`, `button`, `select`, `number` | HA setup blocked by native Windows dependency/toolchain issue before platform completion | Yes | Blocked |
| Initial setup config flow | `config_flow.py` | `tests/test_config_flow.py` | Browser/API config-flow execution in real HA | Add integration from UI and select fake sources | Config entry created without typed YAML | UI/API not completed in native Windows server | Partial | Blocked |
| Source devices/entities | `config_flow.py`, `discovery.py` | `tests/test_config_flow.py`, `tests/test_discovery.py` | End-to-end HA entity selector coverage | Select fake source devices/entities | Source selection validates and persists | Seeded storage only; UI not completed | Partial | Blocked |
| Mains source entities | `config_flow.py`, `coordinator.py` | `tests/test_config_flow.py`, `tests/test_coordinator.py` | Runtime split-phase mains config in HA | Select L1/L2 mains sensors | Mains circuit and NILM/mains summaries load | Seeded but setup blocked before verification | Yes | Blocked |
| Outdoor temperature | `config_flow.py`, `weather_context.py`, `processors/water_context.py` | `tests/test_weather_context.py`, `tests/test_coordinator.py` | Real HA state-change workflow | Configure temperature entity and simulate state | HVAC context updates without errors | Not reached | Yes | Blocked |
| Rain context | `config_flow.py`, `water_correlations.py`, `processors/water_context.py` | `tests/test_water_correlations.py`, `tests/test_coordinator.py` | UI selector and runtime rain state in HA | Configure rain binary/intensity sensors | Rain/pump context influences summaries safely | Not reached | Yes | Blocked |
| Water-flow context | `config_flow.py`, `water_correlations.py`, `processors/water_context.py` | `tests/test_water_correlations.py`, `tests/test_entities.py` | Real HA binary/numeric flow mismatch path | Configure flow sensors and simulate mismatch | Flow mismatch warning appears without traceback | Not reached | Yes | Blocked |
| Review Circuit Assignments | `config_flow.py`, `mapping.py`, `appliance_metadata.py` | `tests/test_config_flow.py`, `tests/test_mapping.py` | Real multi-step form through HA frontend | Review, edit, include/exclude circuits | Stable circuit IDs and generated assignments | Not reached | Partial | Blocked |
| Options flow init/menu | `config_flow.py` | `tests/test_config_flow.py` | Current HA result-shape compatibility tests should use HA helpers | Open Configure on existing entry | Menu offers sources, mains, NILM, utility, advanced, recommendations, entity detail, dashboard | Earlier HA-backed tests showed brittle direct result comparisons | N/A | Partial |
| Advanced Circuit Settings | `config_flow.py`, `services.py`, processors | `tests/test_config_flow.py`, `tests/test_services.py`, processor tests | Real invalid/valid form save in HA | Open every advanced section and save | Defaults valid, invalid values user-friendly, settings persist | Not reached | Partial | Blocked |
| Entity Detail Level | `config_flow.py`, `profiles.py`, `entity.py` | `tests/test_config_flow.py`, `tests/test_profiles.py`, `tests/test_entities.py` | Real entity registry application | Set Simple/Standard/Expert and apply | Expected entities enabled/disabled, manual choices preserved | Not reached | Partial | Blocked |
| Suggested Settings | `settings_advisor.py`, `config_flow.py`, `button.py` | `tests/test_settings_advisor.py`, `tests/test_config_flow.py`, `tests/test_control_entities.py` | Real options UI apply/deny/dismiss | Recalculate and batch apply suggestions | Recommendations apply without typed IDs | Not reached | Partial | Blocked |
| Sensor entities | `sensor.py`, `entity.py` | `tests/test_entities.py`, `tests/test_user_facing_text.py` | Real entity registry defaults in HA | Load configured entry | Summary entities enabled; diagnostics disabled by detail level | Not reached | Yes | Blocked |
| Binary sensor entities | `binary_sensor.py`, `entity.py` | `tests/test_entities.py` | Real running/mismatch states in HA | Simulate source state changes | Running and mismatch states update | Not reached | Yes | Blocked |
| Button entities | `button.py` | `tests/test_control_entities.py` | Real HA service/entity button press | Press relearn, maintenance, mapping, suggestions buttons | Actions complete and update state | Not reached | Yes | Blocked |
| Select entities | `select.py` | `tests/test_control_entities.py` | Real HA select changes | Change alert sensitivity | Option persists and coordinator updates | Not reached | Yes | Blocked |
| Number entities | `number.py` | `tests/test_control_entities.py` | Real HA number set | Set daily energy goal | Number persists and updates goal settings | Not reached | Yes | Blocked |
| Services/actions | `services.py`, `services.yaml` | `tests/test_services.py`, `tests/test_user_facing_text.py` | Real HA service calls with loaded entry | Call all services with valid/invalid data | Valid calls work; invalid IDs raise clear errors | Not reached in HA server | Partial | Blocked |
| Evidence panel registration | `panel.py`, `frontend/energy-analyzer-panel.js` | `tests/test_panel.py` | Browser/API auth and panel click paths | Open panel and invoke actions | Auth required; valid data works; invalid IDs safe | Not reached in HA server | Partial | Blocked |
| Repairs and notifications | `repairs.py`, `notifications.py`, `coordinator.py` | `tests/test_coordinator.py`, `tests/test_alerting.py` | Real Repairs UI and persistent notification UX | Trigger bad data and alerts | Repairs are actionable, notifications link to panel | Not reached | Partial | Blocked |
| Storage load/save/migration | `storage.py`, `coordinator.py` | `tests/test_storage.py`, `tests/test_coordinator.py` | Runtime storage writes in HA | Generate state, reload, restart | Store loads/saves without duplication | HA native Windows storage required shims; integration store not reached | Yes | Blocked |
| Coordinator lifecycle | `__init__.py`, `coordinator.py` | `tests/test_coordinator.py`, `tests/test_services.py` | Full real HA reload/unload | Setup, reload, unload entry | Listeners/services/panel cleanup correctly | Not reached | Yes | Blocked |
| Processor architecture | `processors/*.py`, feature modules | `tests/test_processors.py`, feature tests | Runtime cross-feature sample in HA | Simulate diverse source states | Processors produce stable summaries | Unit fallback passed; HA runtime blocked | N/A | Partial |
| Async correctness | `coordinator.py`, `services.py`, `panel.py` | Many async tests | Real event-loop/blocking warnings | Run update-heavy scenario | No blocking warnings | Native Windows event-loop limitations blocked this | Yes | Blocked |
| Translations | `strings.json`, `translations/en.json`, `services.yaml` | `tests/test_user_facing_text.py` | Real frontend rendering smoke | Open forms/entities/panel | No missing translation keys | Unit fallback passed; UI not reached | N/A | Partial |
| No-typing UX | `config_flow.py`, `button.py`, `select.py`, `number.py`, `panel.py`, `services.yaml` | `tests/test_user_facing_text.py`, control/entity tests | Real UI review of all normal workflows | Complete setup and actions without IDs/YAML | Normal users avoid typed IDs/YAML | Not reached in HA server | Partial | Blocked |
| Performance smoke | `coordinator.py`, `sensor.py`, `binary_sensor.py` | No dedicated large runtime smoke identified | 6/12/24 circuit HA runtime performance test | Simulate frequent updates | No excessive churn or blocking | Not run | N/A | Not run |

## Automated Coverage Snapshot

The global no-HA fallback run produced 598 passing tests and 90 percent line coverage. This is useful for pure logic and fallback behavior, but it is not a substitute for a supported HA runtime because many tests intentionally avoid importing real Home Assistant internals.

## Priority Gaps

1. Run the full suite in a supported Linux/macOS/WSL/container HA test environment.
2. Exercise a real config entry through HA UI/API instead of direct storage seeding.
3. Verify entity registry defaults and entity detail level against real HA registry state.
4. Verify panel auth, actions, and bad-ID handling against real HTTP endpoints.
5. Add a performance smoke for larger circuit counts.

