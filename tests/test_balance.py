from custom_components.circuitsetup_energy_analyzer.balance import (
    BalanceInput,
    calculate_balance,
)


def test_calculate_balance_tracks_unmonitored_load_and_coverage() -> None:
    result = calculate_balance(
        mains=BalanceInput(circuit_id="mains", real_power_w=5000.0),
        monitored=[
            BalanceInput(circuit_id="hvac", real_power_w=2400.0),
            BalanceInput(circuit_id="fridge", real_power_w=300.0),
        ],
    )

    assert result.mains_power_w == 5000.0
    assert result.monitored_power_w == 2700.0
    assert result.balance_power_w == 2300.0
    assert result.monitored_coverage_percent == 54.0
    assert result.status == "tracking"
    assert result.features == {
        "mains_power_w": 5000.0,
        "monitored_power_w": 2700.0,
        "balance_power_w": 2300.0,
        "monitored_coverage_percent": 54.0,
        "monitored_circuit_count": 2.0,
    }


def test_calculate_balance_marks_negative_balance_with_tolerance() -> None:
    result = calculate_balance(
        mains=BalanceInput(circuit_id="mains", real_power_w=1000.0),
        monitored=[
            BalanceInput(circuit_id="hvac", real_power_w=900.0),
            BalanceInput(circuit_id="fridge", real_power_w=350.0),
        ],
        negative_tolerance_w=100.0,
    )

    assert result.balance_power_w == -250.0
    assert result.monitored_coverage_percent == 125.0
    assert result.status == "negative_balance"


def test_calculate_balance_ignores_generation_and_mains_net_export() -> None:
    result = calculate_balance(
        mains=BalanceInput(circuit_id="mains", real_power_w=-400.0),
        monitored=[
            BalanceInput(circuit_id="solar", real_power_w=1200.0, generation=True),
            BalanceInput(circuit_id="fridge", real_power_w=300.0),
        ],
    )

    assert result.mains_power_w == 0.0
    assert result.monitored_power_w == 300.0
    assert result.balance_power_w == -300.0
    assert result.status == "negative_balance"


def test_calculate_balance_reports_missing_inputs() -> None:
    assert calculate_balance(mains=None, monitored=[]).status == "missing_mains"
    assert calculate_balance(
        mains=BalanceInput(circuit_id="mains", real_power_w=5000.0),
        monitored=[],
    ).status == "no_monitored_circuits"
