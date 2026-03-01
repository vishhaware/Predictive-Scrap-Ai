from pathlib import Path
import tempfile

import pandas as pd

from train_models_from_csv import CANONICAL_VARIABLES, enrich_parameter_csv


def test_parameter_csv_enrichment() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "input.csv"
        dst = tmp / "output.csv"

        pd.DataFrame(
            [
                {"variable_name": "Cushion", "tolerance_plus": 0.5, "tolerance_minus": -0.5},
                {"variable_name": "Injection_pressure", "tolerance_plus": None, "tolerance_minus": None},
                {"variable_name": "Cyl_tmp_z1", "tolerance_plus": None, "tolerance_minus": None},
                {"variable_name": "Switch_position", "tolerance_plus": None, "tolerance_minus": None},
            ]
        ).to_csv(src, index=False)

        out = enrich_parameter_csv(src, dst)

        assert set(CANONICAL_VARIABLES).issubset(set(out["variable_name"]))

        row_pressure = out.loc[out["variable_name"] == "Injection_pressure"].iloc[0]
        assert float(row_pressure["tolerance_plus"]) == 100.0
        assert float(row_pressure["tolerance_minus"]) == -100.0

        row_temp = out.loc[out["variable_name"] == "Cyl_tmp_z1"].iloc[0]
        assert float(row_temp["tolerance_plus"]) == 5.0
        assert float(row_temp["tolerance_minus"]) == -5.0

        row_switch = out.loc[out["variable_name"] == "Switch_position"].iloc[0]
        assert float(row_switch["tolerance_plus"]) == 0.05
        assert float(row_switch["tolerance_minus"]) == -0.05

        type_counts = out["variable_type"].value_counts().to_dict()
        assert type_counts.get("set_value", 0) > 0
        assert type_counts.get("monitored_result", 0) > 0
        assert type_counts.get("counter", 0) > 0


if __name__ == "__main__":
    test_parameter_csv_enrichment()
    print("test_parameter_csv_enrichment passed")
