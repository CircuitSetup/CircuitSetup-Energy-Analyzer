from custom_components.circuitsetup_energy_analyzer.solar_flow import (
    SolarFlowInput,
    calculate_solar_flow,
)


def test_calculate_solar_flow_tracks_export_and_self_consumption() -> None:
    result = calculate_solar_flow(
        mains=SolarFlowInput(circuit_id="mains", real_power_w=-500.0),
        generation=[
            SolarFlowInput(circuit_id="solar", real_power_w=2000.0),
        ],
    )

    assert result.status == "exporting"
    assert result.solar_generation_w == 2000.0
    assert result.grid_import_w == 0.0
    assert result.grid_export_w == 500.0
    assert result.site_consumption_w == 1500.0
    assert result.solar_used_on_site_w == 1500.0
    assert result.self_consumption_percent == 75.0
    assert result.solar_powered_percent == 100.0
    assert result.features == {
        "mains_net_power_w": -500.0,
        "solar_generation_w": 2000.0,
        "grid_import_w": 0.0,
        "grid_export_w": 500.0,
        "site_consumption_w": 1500.0,
        "solar_used_on_site_w": 1500.0,
        "self_consumption_percent": 75.0,
        "solar_powered_percent": 100.0,
        "generation_circuit_count": 1.0,
    }


def test_calculate_solar_flow_tracks_import_while_solar_offsets_load() -> None:
    result = calculate_solar_flow(
        mains=SolarFlowInput(circuit_id="mains", real_power_w=1200.0),
        generation=[
            SolarFlowInput(circuit_id="solar", real_power_w=800.0),
        ],
    )

    assert result.status == "importing"
    assert result.solar_generation_w == 800.0
    assert result.grid_import_w == 1200.0
    assert result.grid_export_w == 0.0
    assert result.site_consumption_w == 2000.0
    assert result.solar_used_on_site_w == 800.0
    assert result.self_consumption_percent == 100.0
    assert result.solar_powered_percent == 40.0


def test_calculate_solar_flow_reports_export_without_generation_as_inconsistent() -> (
    None
):
    result = calculate_solar_flow(
        mains=SolarFlowInput(circuit_id="mains", real_power_w=-1800.0),
        generation=[
            SolarFlowInput(circuit_id="solar", real_power_w=500.0),
        ],
    )

    assert result.status == "inconsistent_export"
    assert result.grid_export_w == 1800.0
    assert result.site_consumption_w == 0.0
    assert result.solar_used_on_site_w == 0.0
    assert result.self_consumption_percent == 0.0
    assert result.solar_powered_percent == 0.0


def test_calculate_solar_flow_reports_missing_inputs() -> None:
    assert calculate_solar_flow(mains=None, generation=[]).status == "missing_mains"
    assert calculate_solar_flow(
        mains=SolarFlowInput(circuit_id="mains", real_power_w=2000.0),
        generation=[],
    ).status == "missing_generation"
