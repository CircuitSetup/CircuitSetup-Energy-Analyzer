# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, mixed circuits, and opt-in experimental mains NILM discovery. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Installation

This repository is structured for HACS as a custom integration. The integration files live under `custom_components/circuitsetup_energy_analyzer`.

To install with HACS:

1. Open HACS.
2. Add this repository as a custom repository with category `Integration`.
3. Install CircuitSetup Energy Analyzer.
4. Restart Home Assistant.
5. Add the integration from Settings > Devices & services.

## Circuit Modes

CircuitSetup Energy Analyzer supports four analysis modes:

- Single-phase circuits monitor one CT/channel mapped to one primary appliance, such as a refrigerator, freezer, pump, or other 120 V load.
- Dual-phase circuits combine two CT/channels into one appliance model for 240 V loads. The analyzer keeps leg-level context so it can surface suspicious imbalance or phase-pairing problems without treating each leg as an unrelated appliance.
- Mixed circuits are useful when one branch circuit feeds multiple small loads. The integration reports data quality, large changes, and recurring evidence conservatively instead of pretending the circuit is a clean appliance signature.
- Mains NILM circuits are whole-home aggregate inputs. Experimental NILM can look for recurring aggregate signatures after known directly monitored circuits are masked out.

## Power Flow

CircuitSetup real-power sensors may report negative watts when a CT is reversed
or when a source, such as a solar inverter, is exporting power. The analyzer
tracks the raw watts separately from the analysis watts so those cases can be
handled differently:

- Load circuits treat sustained negative real power as a data-quality problem and raise a Repair suggesting CT orientation review or a different power-flow setting.
- Solar inverter circuits treat negative real power as exported generation and analyze the export magnitude.
- Mains NILM circuits keep signed net power so import and export behavior can be disaggregated without losing direction.

## Experimental NILM

Experimental NILM is opt-in. It can be enabled for mains aggregate channels or mixed circuits to discover recurring load signatures, but it should be treated as a hinting system rather than a diagnostic authority. Unknown signatures stay unknown until a user confirms and labels them.

## Alert Philosophy

The analyzer is evidence-first. It learns for at least 7 days or enough profile-specific cycles before sending appliance-behavior alerts. Alerts require repeated evidence and are phrased as a possible issue or behavior change, not a diagnosis.

This means a refrigerator alert might say that cycle duration appears unusual compared with its learned baseline. It should not claim that a compressor, fan, seal, or refrigerant problem has been diagnosed.

## Notifications And Repairs

Persistent notifications are reserved for important evidence about appliance behavior, such as repeated anomaly evidence after the learning period.

Home Assistant Repairs are used for setup, configuration, and data-quality problems: missing required sensors, stale source sensors, phase mismatch, missing mains NILM sensors, or low NILM confidence. Repairs should help fix the integration inputs before appliance analysis continues.

## Standard Entities

The integration exposes standard Home Assistant diagnostic entities per configured circuit:

- `sensor.<circuit>_anomaly_score`
- `sensor.<circuit>_last_event`
- `binary_sensor.<circuit>_learning`
- `binary_sensor.<circuit>_data_quality_problem`
- `sensor.<circuit>_nilm_discovered_signatures`
- `sensor.<circuit>_nilm_unmatched_load_percentage`

See `docs/dashboard-example.yaml` for a starting dashboard with Refrigerator, HVAC, and Mains NILM cards.
