"""Build two-meter browser case data with the integration's panel handlers."""

import json
import sys
from dataclasses import replace

from custom_components.circuitsetup_energy_analyzer.notifications import (
    notification_id_for_alert,
)
from custom_components.circuitsetup_energy_analyzer.panel import (
    alert_evidence_payload,
    appliance_insights_payload,
)
from tests.test_appliance_detail import _direct_coordinator


def main() -> None:
    meters = []
    for location in ("Kitchen", "Garage"):
        meter = _direct_coordinator()
        meter.entry_id = f"{location.lower()}-meter"
        name = f"{location} fridge"
        meter.circuit_configs = (replace(meter.circuit_configs[0], name=name),)
        alert = replace(
            meter.state.active_alerts_by_circuit["fridge"][0],
            message=f"{name} used more energy than usual.",
        )
        meter.state.active_alerts_by_circuit["fridge"] = [alert]
        meter.store_data.alerts.append(alert)
        meters.append(meter)

    cases = {}
    for meter in meters:
        alert = meter.state.active_alerts_by_circuit["fridge"][0]
        cases[meter.entry_id] = {
            "issues": appliance_insights_payload(
                meters, view="attention", entry_id=meter.entry_id
            ),
            "evidence": alert_evidence_payload(
                meters,
                alert_id=notification_id_for_alert(alert),
                entry_id=meter.entry_id,
            ),
        }
    json.dump(cases, sys.stdout)


if __name__ == "__main__":
    main()
