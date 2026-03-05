#!/usr/bin/env python3
"""
Data quality checks for cleaned machine CSV artifacts.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


LOGGER = logging.getLogger("data_quality")
MACHINES = ["M231-11", "M356-57", "M471-23", "M607-30", "M612-33"]

SENSOR_BOUNDS = {
    "Cushion": (0.0, 100.0),
    "Injection_time": (0.0, 10.0),
    "Dosage_time": (0.0, 10.0),
    "Injection_pressure": (0.0, 3000.0),
    "Switch_pressure": (0.0, 3000.0),
    "Switch_position": (0.0, 500.0),
    "Cycle_time": (0.0, 300.0),
    "Cyl_tmp_z1": (-50.0, 400.0),
    "Cyl_tmp_z2": (-50.0, 400.0),
    "Cyl_tmp_z3": (-50.0, 400.0),
    "Cyl_tmp_z4": (-50.0, 400.0),
    "Cyl_tmp_z5": (-50.0, 400.0),
    "Cyl_tmp_z8": (-50.0, 400.0),
    "Shot_size": (0.0, 5000.0),
    "Ejector_fix_deviation_torque": (-500.0, 500.0),
}


class DataQualityChecker:
    def check_cycle_row(self, row: Dict[str, Any]) -> Tuple[bool, List[str]]:
        issues: List[str] = []

        ts = row.get("timestamp")
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            issues.append("Missing timestamp")

        scrap_inc = self._to_float(row.get("scrap_inc"))
        shot_inc = self._to_float(row.get("shot_inc"))
        scrap_rate = self._to_float(row.get("scrap_rate"))

        if scrap_inc is not None and scrap_inc < 0:
            issues.append(f"Negative scrap_inc: {scrap_inc}")
        if shot_inc is not None and shot_inc < 0:
            issues.append(f"Negative shot_inc: {shot_inc}")
        if scrap_rate is not None and (scrap_rate < 0 or scrap_rate > 100):
            issues.append(f"Invalid scrap_rate: {scrap_rate}")
        if shot_inc is not None and shot_inc == 0 and scrap_inc is not None and scrap_inc > 0:
            issues.append("scrap_inc > 0 while shot_inc == 0")

        for sensor_name, (min_v, max_v) in SENSOR_BOUNDS.items():
            value = self._to_float(row.get(sensor_name))
            if value is None:
                continue
            if value < min_v or value > max_v:
                issues.append(f"{sensor_name} out of bounds: {value} not in [{min_v}, {max_v}]")

        return len(issues) == 0, issues

    def check_dataframe(self, df: pd.DataFrame, machine_id: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "machine_id": machine_id,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "total_rows": int(len(df)),
            "valid_rows": 0,
            "invalid_rows": 0,
            "data_quality_score": 0.0,
            "warnings": [],
            "errors": [],
            "invalid_row_details": [],
            "metrics": {},
        }

        if df.empty:
            report["warnings"].append("Dataframe is empty.")
            return report

        frame = df.copy()
        frame["timestamp"] = pd.to_datetime(frame.get("timestamp"), errors="coerce", utc=True)
        if frame["timestamp"].isna().any():
            report["warnings"].append(f"{int(frame['timestamp'].isna().sum())} invalid timestamps.")

        sorted_ts = frame["timestamp"].dropna().sort_values()
        if not sorted_ts.empty:
            diffs = sorted_ts.diff().dt.total_seconds().div(60.0)
            large_gaps = int((diffs > 10).sum())
            if large_gaps > 0:
                report["warnings"].append(f"{large_gaps} gaps > 10 minutes detected.")
            report["metrics"]["avg_interval_minutes"] = round(float(diffs.mean(skipna=True) or 0.0), 3)
            report["metrics"]["max_interval_minutes"] = round(float(diffs.max(skipna=True) or 0.0), 3)

        if "cycle_id" in frame.columns:
            dupes = int(frame["cycle_id"].astype(str).duplicated().sum())
            if dupes > 0:
                report["errors"].append(f"{dupes} duplicate cycle_id rows.")

        if "timestamp" in frame.columns:
            dup_ts = int(frame["timestamp"].duplicated().sum())
            if dup_ts > 0:
                report["warnings"].append(f"{dup_ts} duplicate timestamps.")

        for idx, row in frame.iterrows():
            is_valid, issues = self.check_cycle_row(row.to_dict())
            if is_valid:
                report["valid_rows"] += 1
            else:
                report["invalid_rows"] += 1
                if len(report["invalid_row_details"]) < 50:
                    report["invalid_row_details"].append(
                        {
                            "row_index": int(idx),
                            "cycle_id": str(row.get("cycle_id", "")),
                            "issues": issues,
                        }
                    )

        total_rows = max(1, int(report["total_rows"]))
        report["data_quality_score"] = round((float(report["valid_rows"]) / float(total_rows)) * 100.0, 3)

        scrap_rate = None
        if "shot_inc" in frame.columns and "scrap_inc" in frame.columns:
            shot_sum = float(pd.to_numeric(frame["shot_inc"], errors="coerce").fillna(0.0).sum())
            scrap_sum = float(pd.to_numeric(frame["scrap_inc"], errors="coerce").fillna(0.0).sum())
            if shot_sum > 0:
                scrap_rate = (scrap_sum / shot_sum) * 100.0
        if scrap_rate is not None:
            report["metrics"]["overall_scrap_rate_percent"] = round(scrap_rate, 4)

        report["metrics"]["null_cells"] = int(frame.isna().sum().sum())
        report["metrics"]["completeness_percent"] = round(
            ((frame.size - int(frame.isna().sum().sum())) / float(max(1, frame.size))) * 100.0,
            3,
        )
        return report

    @staticmethod
    def _to_float(value: Any) -> float | None:
        try:
            out = float(value)
        except Exception:
            return None
        if pd.isna(out):
            return None
        return out


def run_quality_check_for_all(cleaned_output_dir: Path, machines: List[str] | None = None) -> Dict[str, Any]:
    checker = DataQualityChecker()
    machine_reports: List[Dict[str, Any]] = []
    target_machines = machines or MACHINES

    for machine_id in target_machines:
        csv_path = cleaned_output_dir / f"{machine_id}_cleaned.csv"
        if not csv_path.exists():
            machine_reports.append(
                {
                    "machine_id": machine_id,
                    "missing_file": True,
                    "file": str(csv_path),
                    "data_quality_score": 0.0,
                    "total_rows": 0,
                    "valid_rows": 0,
                    "invalid_rows": 0,
                    "errors": [f"Missing cleaned file: {csv_path.name}"],
                    "warnings": [],
                    "invalid_row_details": [],
                    "metrics": {},
                }
            )
            continue

        df = pd.read_csv(csv_path, low_memory=False)
        report = checker.check_dataframe(df, machine_id)
        report["file"] = str(csv_path)
        machine_reports.append(report)

    overall_rows = sum(int(item.get("total_rows", 0)) for item in machine_reports)
    overall_valid = sum(int(item.get("valid_rows", 0)) for item in machine_reports)
    overall_quality = round((overall_valid / float(max(1, overall_rows))) * 100.0, 3)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(cleaned_output_dir),
        "machines": machine_reports,
        "summary": {
            "machine_count": len(machine_reports),
            "overall_rows": overall_rows,
            "overall_valid_rows": overall_valid,
            "overall_quality_score": overall_quality,
            "machines_below_99_quality": [
                item.get("machine_id")
                for item in machine_reports
                if float(item.get("data_quality_score", 0.0)) < 99.0
            ],
        },
    }
    return payload


def parse_args() -> argparse.Namespace:
    default_output = Path(
        os.getenv(
            "CLEANED_DATA_OUTPUT_DIR",
            str(Path(__file__).resolve().parent.parent / "cleaned_data_output"),
        )
    )
    parser = argparse.ArgumentParser(description="Run quality checks on cleaned machine CSV artifacts.")
    parser.add_argument("--cleaned-output-dir", default=str(default_output))
    parser.add_argument("--machines", default=",".join(MACHINES), help="Comma-separated machine IDs.")
    parser.add_argument(
        "--report-file",
        default=str(default_output / "data_quality_report.json"),
        help="Output JSON report path.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    machine_ids = [m.strip() for m in str(args.machines).split(",") if m.strip()]
    report = run_quality_check_for_all(Path(args.cleaned_output_dir), machines=machine_ids)
    report_path = Path(args.report_file)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LOGGER.info("Data quality report written: %s", report_path)
    LOGGER.info("Overall quality score: %.3f", float(report["summary"]["overall_quality_score"]))


if __name__ == "__main__":
    main()
