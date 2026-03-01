import numpy as np
import pandas as pd

from dynamic_limits import PHYSICS_RULES, calculate_dynamic_limits, load_physics_rules


def test_dynamic_limits() -> None:
    print("--- Testing Dynamic Limits ---")
    load_physics_rules(force_reload=True)

    # Synthetic recent history with deterministic values.
    history_df = pd.DataFrame(
        {
            "Cushion": np.linspace(5.2, 5.8, 120),
            "Injection_pressure": np.linspace(620.0, 760.0, 120),
            "Switch_pressure": np.linspace(610.0, 750.0, 120),
            "Cycle_time": np.linspace(13.0, 15.5, 120),
            "Extruder_torque": np.linspace(0.2, 0.2, 120),
            "Ejector_fix_deviation_torque": np.linspace(-0.5, 0.5, 120),
            "Cyl_tmp_z1": np.linspace(-7.0, -3.0, 120),
        }
    )

    limits = calculate_dynamic_limits(history_df)
    local_median = history_df.median(numeric_only=True)
    local_std = history_df.std(numeric_only=True)

    # Bucket A: CSV tolerance sensor examples.
    cushion_rule = PHYSICS_RULES["Cushion"]
    expected_cushion_min = local_median["Cushion"] - abs(cushion_rule["tolerance_minus"])
    expected_cushion_max = local_median["Cushion"] + abs(cushion_rule["tolerance_plus"])
    assert np.isclose(limits["Cushion"]["min"], expected_cushion_min)
    assert np.isclose(limits["Cushion"]["max"], expected_cushion_max)
    assert limits["Cushion"]["source"] == "csv_tolerance"

    inj_rule = PHYSICS_RULES["Injection_pressure"]
    expected_inj_span = abs(inj_rule["tolerance_minus"]) + abs(inj_rule["tolerance_plus"])
    actual_inj_span = limits["Injection_pressure"]["max"] - limits["Injection_pressure"]["min"]
    assert np.isclose(actual_inj_span, expected_inj_span)

    # Bucket C: fallback for non-CSV tolerance sensors.
    sigma_cycle = local_std["Cycle_time"]
    expected_cycle_margin = max((sigma_cycle * 3.0), (abs(local_median["Cycle_time"]) * 0.02))
    expected_cycle_min = local_median["Cycle_time"] - expected_cycle_margin
    expected_cycle_max = local_median["Cycle_time"] + expected_cycle_margin
    assert np.isclose(limits["Cycle_time"]["min"], expected_cycle_min)
    assert np.isclose(limits["Cycle_time"]["max"], expected_cycle_max)
    assert limits["Cycle_time"]["source"] == "statistical_fallback"

    # No relational rules: Switch_pressure must use its own CSV tolerance.
    switch_rule = PHYSICS_RULES["Switch_pressure"]
    expected_switch_min = local_median["Switch_pressure"] - abs(switch_rule["tolerance_minus"])
    expected_switch_max = local_median["Switch_pressure"] + abs(switch_rule["tolerance_plus"])
    assert np.isclose(limits["Switch_pressure"]["min"], expected_switch_min)
    assert np.isclose(limits["Switch_pressure"]["max"], expected_switch_max)

    # Sanity clamp: min >= 0 for normal sensors.
    assert limits["Extruder_torque"]["min"] >= 0.0

    # Exceptions for deviation/offset/tmp sensors can remain negative.
    assert limits["Ejector_fix_deviation_torque"]["min"] < 0.0
    assert limits["Cyl_tmp_z1"]["min"] < 0.0

    print("Dynamic limits logic verified correctly. No relational rules found.\n")


def test_no_manual_sensor_overrides() -> None:
    with open("data_access.py", mode="r", encoding="utf-8") as f:
        source = f.read().lower()

    forbidden_tokens = ["locked_sensors", "steady_state override", "steady_state_overrides"]
    for token in forbidden_tokens:
        assert token not in source, f"Forbidden override token found: {token}"

    print("Forecasting pipeline check passed: no locked-sensor/steady-state overrides found.\n")


if __name__ == "__main__":
    test_dynamic_limits()
    test_no_manual_sensor_overrides()
    print("All pipeline verification checks passed.")

