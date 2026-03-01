from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from train_models_from_csv import (
    add_regression_targets,
    create_horizon_labels,
    engineer_features_for_machine,
    pivot_to_minute_wide,
    train_multi_horizon_models,
)


def _build_synthetic_long_df(n_rows: int = 1800) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01 00:00:00+00:00", periods=n_rows, freq="1min")
    scrap_delta = np.zeros(n_rows)
    scrap_delta[np.arange(100, n_rows, 120)] = 1.0
    scrap_counter = np.cumsum(scrap_delta)
    shot_counter = np.arange(n_rows, dtype=float)

    wide = pd.DataFrame(
        {
            "timestamp": ts,
            "Cushion": 10 + 0.1 * np.sin(np.arange(n_rows) / 15.0),
            "Cycle_time": 20 + 0.2 * np.cos(np.arange(n_rows) / 25.0),
            "Injection_pressure": 700 + 5 * np.sin(np.arange(n_rows) / 35.0),
            "Scrap_counter": scrap_counter,
            "Shot_counter": shot_counter,
        }
    )
    long = wide.melt(id_vars=["timestamp"], var_name="variable_name", value_name="value")
    long["machine_id"] = "M231"
    return long


def test_horizon_pipeline() -> None:
    long_df = _build_synthetic_long_df()
    wide = pivot_to_minute_wide(long_df)
    assert not wide.empty
    assert wide.index.is_monotonic_increasing
    assert "Scrap_counter" in wide.columns

    machine_df = wide.reset_index()
    machine_df["machine_id"] = "M231"
    machine_df["part_number"] = "PN-1"
    machine_df["tool_id"] = "TOOL-1"
    machine_df["yield_quantity"] = 100.0
    machine_df["scrap_quantity"] = machine_df["Scrap_counter"].diff().fillna(0.0).clip(lower=0.0)
    machine_df["strokes_yield_quantity"] = 100.0
    machine_df["strokes_total_quantity"] = 105.0
    machine_df["scrap_ratio"] = machine_df["scrap_quantity"] / (machine_df["yield_quantity"] + machine_df["scrap_quantity"] + 1e-9)
    machine_df["strokes_efficiency"] = machine_df["strokes_yield_quantity"] / (machine_df["strokes_total_quantity"] + 1e-9)
    machine_df["hydra_scrap_counter"] = machine_df["scrap_quantity"].cumsum()
    machine_df["scrap_counter_source"] = machine_df["Scrap_counter"]

    param_df = pd.DataFrame(
        [
            {"variable_name": "Cushion", "tolerance_plus": 0.5, "tolerance_minus": -0.5, "default_set_value": 10.0},
            {"variable_name": "Cycle_time", "tolerance_plus": 1.0, "tolerance_minus": -1.0, "default_set_value": 20.0},
            {"variable_name": "Injection_pressure", "tolerance_plus": 100.0, "tolerance_minus": -100.0, "default_set_value": 700.0},
        ]
    )

    features, feature_cols, _ = engineer_features_for_machine(machine_df, param_df)
    assert any("__mean_5m" in col for col in feature_cols)
    assert any("__trend_10m" in col for col in feature_cols)
    assert any("__spike_count_30m" in col for col in feature_cols)

    features["scrap_counter_source"] = machine_df["scrap_counter_source"].values
    features = create_horizon_labels(features, scrap_counter_col="scrap_counter_source", horizons=(30, 240, 1440))
    features = add_regression_targets(features, horizons=(30, 240, 1440))
    assert {"scrap_event_30m", "scrap_event_240m", "scrap_event_1440m"}.issubset(features.columns)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "horizon"
        result = train_multi_horizon_models(
            frame=features,
            feature_cols=feature_cols,
            out_dir=out_dir,
            data_sources={"source": "synthetic"},
            horizons=(30, 240, 1440),
        )

        for h in (30, 240, 1440):
            assert (out_dir / f"scrap_{h}m_model.joblib").exists()
            assert (out_dir / f"scrap_{h}m_scaler.joblib").exists()
            assert (out_dir / f"scrap_{h}m_feature_list.joblib").exists()
            assert (out_dir / f"scrap_{h}m_metadata.json").exists()

            metrics = result["horizons"][f"{h}m"]
            assert np.isfinite(metrics["roc_auc"]) or np.isnan(metrics["roc_auc"])
            assert np.isfinite(metrics["pr_auc"]) or np.isnan(metrics["pr_auc"])


if __name__ == "__main__":
    test_horizon_pipeline()
    print("test_horizon_pipeline passed")
