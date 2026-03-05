#!/usr/bin/env python3
"""
Complete data transformation pipeline:
long-format machine CSV -> cleaned wide-format cycles -> LSTM-ready sequences.

Outputs:
- cleaned_data_output/{machine_id}_cleaned.csv
- cleaned_data_output/lstm_sequences.json
- cleaned_data_output/data_metadata.json
- cleaned_data_output/safe_limits_by_machine.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


LOGGER = logging.getLogger("transform_data_pipeline")

MACHINES = ["M231-11", "M356-57", "M471-23", "M607-30", "M612-33"]
SENSOR_COLUMNS = [
    "Cushion",
    "Injection_time",
    "Dosage_time",
    "Injection_pressure",
    "Switch_pressure",
    "Switch_position",
    "Cycle_time",
    "Cyl_tmp_z1",
    "Cyl_tmp_z2",
    "Cyl_tmp_z3",
    "Cyl_tmp_z4",
    "Cyl_tmp_z5",
    "Cyl_tmp_z8",
    "Shot_size",
    "Ejector_fix_deviation_torque",
]


def _normalize_machine_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    text = text.replace("_", "-")
    m = re.search(r"(\d{3})", text)
    if not m:
        return None
    prefix = m.group(1)
    for machine_id in MACHINES:
        if machine_id.startswith(f"M{prefix}"):
            return machine_id
    return None


def _normalize_part_number(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip().upper()
    if not text or text in {"NA", "N/A", "NONE", "NULL", "NAN", "-"}:
        return None
    if not re.search(r"\d", text):
        return None
    return text


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    if np.isnan(out):
        return None
    return out


def _parse_mes_time_seconds(raw_value: Any) -> Optional[int]:
    if raw_value is None:
        return None
    try:
        if pd.isna(raw_value):
            return None
    except Exception:
        pass
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if ":" in text:
            parts = text.split(":")
            if len(parts) == 3:
                try:
                    h, m, s = [int(x) for x in parts]
                    return h * 3600 + m * 60 + s
                except ValueError:
                    pass
    try:
        numeric = int(float(raw_value))
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return None
    if numeric <= 172800:
        return numeric
    text = str(numeric).zfill(6)[-6:]
    try:
        hh, mm, ss = int(text[0:2]), int(text[2:4]), int(text[4:6])
    except ValueError:
        return None
    if 0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60:
        return hh * 3600 + mm * 60 + ss
    return None


def _parse_mes_datetime(date_value: Any, time_value: Any) -> Optional[pd.Timestamp]:
    if date_value is None:
        return None
    try:
        date_ts = pd.Timestamp(date_value)
    except Exception:
        return None
    if pd.isna(date_ts):
        return None
    raw_dt = date_ts.to_pydatetime().replace(microsecond=0, tzinfo=None)
    base = raw_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds = _parse_mes_time_seconds(time_value)
    if seconds is None:
        if raw_dt.hour or raw_dt.minute or raw_dt.second:
            return pd.Timestamp(raw_dt)
        return pd.Timestamp(base)
    return pd.Timestamp(base + pd.Timedelta(seconds=int(seconds)))


def _classify_shift(ts: pd.Timestamp) -> str:
    hour = int(ts.hour)
    if 6 <= hour < 14:
        return "MORNING"
    if 14 <= hour < 22:
        return "AFTERNOON"
    return "NIGHT"


@dataclass
class MachineProcessResult:
    machine_id: str
    raw_rows: int
    wide_rows: int
    cleaned_rows: int
    part_mapping_coverage_pct: float
    cleaned_df: pd.DataFrame


class DataTransformationPipeline:
    def __init__(
        self,
        data_dir: Path,
        mes_file: Path,
        output_dir: Path,
        sequence_length: int = 30,
        horizon_cycles: int = 30,
        resample_minutes: Optional[int] = None,
        max_sequences: Optional[int] = None,
    ) -> None:
        self.data_dir = data_dir
        self.mes_file = mes_file
        self.output_dir = output_dir
        self.sequence_length = max(10, int(sequence_length))
        self.horizon_cycles = max(5, int(horizon_cycles))
        self.resample_minutes = int(resample_minutes) if resample_minutes else None
        self.max_sequences = int(max_sequences) if max_sequences else None

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_machine_long(self, machine_id: str) -> pd.DataFrame:
        path_csv = self.data_dir / f"{machine_id}.csv"
        path_xlsx = self.data_dir / f"{machine_id}.xlsx"
        if path_csv.exists():
            path = path_csv
            df = pd.read_csv(path, low_memory=False)
        elif path_xlsx.exists():
            path = path_xlsx
            df = pd.read_excel(path)
        else:
            raise FileNotFoundError(f"Missing machine source for {machine_id}: {path_csv.name} or {path_xlsx.name}")

        required = {"timestamp", "variable_name", "value"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(f"{machine_id} missing required columns: {missing}")

        LOGGER.info("Loaded %s rows=%s source=%s", machine_id, f"{len(df):,}", path.name)
        return df

    def pivot_long_to_wide(self, df_long: pd.DataFrame, machine_id: str) -> pd.DataFrame:
        df = df_long.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp", "variable_name"])
        if df.empty:
            raise ValueError(f"{machine_id}: no valid timestamp/variable rows after parsing.")

        df["variable_name"] = df["variable_name"].astype(str).str.strip()
        df = df.sort_values("timestamp")
        df = df.drop_duplicates(subset=["timestamp", "variable_name"], keep="last")

        wide = (
            df.pivot_table(
                index="timestamp",
                columns="variable_name",
                values="value",
                aggfunc="last",
            )
            .sort_index()
            .reset_index()
        )

        for col in wide.columns:
            if col == "timestamp":
                continue
            wide[col] = pd.to_numeric(wide[col], errors="coerce")

        wide = wide.sort_values("timestamp").reset_index(drop=True)
        wide["machine_id"] = machine_id
        return wide

    def _resample_cycles(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.resample_minutes:
            return df
        rule = f"{int(self.resample_minutes)}min"
        frame = df.copy()
        frame = frame.set_index("timestamp").sort_index()
        numeric_cols = frame.select_dtypes(include=[np.number]).columns.tolist()
        resampled = frame.resample(rule).first()
        if numeric_cols:
            resampled[numeric_cols] = resampled[numeric_cols].ffill()
        resampled["machine_id"] = frame["machine_id"].iloc[0]
        out = resampled.reset_index()
        return out

    def fix_scrap_counters(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy().sort_values("timestamp").reset_index(drop=True)
        if "Scrap_counter" not in frame.columns:
            frame["Scrap_counter"] = np.nan
        if "Shot_counter" not in frame.columns:
            frame["Shot_counter"] = np.nan

        frame["Scrap_counter"] = pd.to_numeric(frame["Scrap_counter"], errors="coerce").ffill().bfill().fillna(0.0)
        frame["Shot_counter"] = pd.to_numeric(frame["Shot_counter"], errors="coerce").ffill().bfill().fillna(0.0)

        scrap_diff = frame["Scrap_counter"].diff()
        shot_diff = frame["Shot_counter"].diff()

        scrap_diff = np.where(scrap_diff < 0, frame["Scrap_counter"], scrap_diff)
        shot_diff = np.where(shot_diff < 0, frame["Shot_counter"], shot_diff)

        frame["scrap_inc"] = pd.Series(scrap_diff).fillna(frame["Scrap_counter"]).clip(lower=0.0)
        frame["shot_inc"] = pd.Series(shot_diff).fillna(frame["Shot_counter"]).clip(lower=0.0)
        frame["scrap_rate"] = np.where(
            frame["shot_inc"] > 0,
            (frame["scrap_inc"] / frame["shot_inc"]) * 100.0,
            0.0,
        )
        frame["scrap_rate"] = frame["scrap_rate"].replace([np.inf, -np.inf], 0.0).fillna(0.0).round(4)
        frame["has_scrap"] = (frame["scrap_inc"] > 0).astype(int)
        return frame

    def add_shift_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        frame["shift"] = frame["timestamp"].apply(_classify_shift)
        frame["date"] = frame["timestamp"].dt.date.astype(str)
        frame["time_gap_minutes"] = frame["timestamp"].diff().dt.total_seconds().div(60.0).fillna(0.0)
        return frame

    def load_mes_timeline(self) -> Dict[str, pd.DataFrame]:
        if not self.mes_file.exists():
            raise FileNotFoundError(f"MES workbook missing: {self.mes_file}")

        df_raw = pd.read_excel(self.mes_file, sheet_name="Data")
        if df_raw.empty:
            raise ValueError("MES workbook Data sheet is empty.")

        col_map = {str(col).strip().lower(): col for col in df_raw.columns}
        machine_col = col_map.get("machine_id")
        part_col = col_map.get("part_number")
        if machine_col is None or part_col is None:
            raise ValueError("MES Data sheet missing machine_id/part_number columns.")

        end_date_col = col_map.get("machine_event_end_date")
        end_time_col = col_map.get("machine_event_end_time")
        create_date_col = col_map.get("machine_event_create_date")
        create_time_col = col_map.get("machine_event_create_time")
        shift_ts_col = col_map.get("plant_shift_timestamp")
        shift_date_col = col_map.get("plant_shift_date")

        df = df_raw.copy()
        df["machine_id_norm"] = df[machine_col].map(_normalize_machine_id)
        df["part_number_norm"] = df[part_col].map(_normalize_part_number)
        df = df.dropna(subset=["machine_id_norm", "part_number_norm"])
        if df.empty:
            raise ValueError("MES mapping produced no valid machine_id+part_number rows.")

        event_timestamps: List[Optional[pd.Timestamp]] = []
        for _, row in df.iterrows():
            event_ts = None
            if end_date_col:
                event_ts = _parse_mes_datetime(row.get(end_date_col), row.get(end_time_col) if end_time_col else None)
            if event_ts is None and create_date_col:
                event_ts = _parse_mes_datetime(row.get(create_date_col), row.get(create_time_col) if create_time_col else None)
            if event_ts is None and shift_ts_col:
                try:
                    shift_ts = pd.Timestamp(row.get(shift_ts_col))
                    if not pd.isna(shift_ts):
                        event_ts = pd.Timestamp(shift_ts).tz_localize(None)
                except Exception:
                    event_ts = None
            if event_ts is None and shift_date_col:
                try:
                    shift_date = pd.Timestamp(row.get(shift_date_col))
                    if not pd.isna(shift_date):
                        event_ts = pd.Timestamp(shift_date).tz_localize(None)
                except Exception:
                    event_ts = None
            event_timestamps.append(event_ts)

        df["event_ts"] = pd.to_datetime(event_timestamps, utc=True, errors="coerce")
        df = df.dropna(subset=["event_ts"])
        if df.empty:
            raise ValueError("MES mapping produced no valid timestamps.")

        out: Dict[str, pd.DataFrame] = {}
        for machine_id, machine_df in df.groupby("machine_id_norm"):
            timeline = (
                machine_df[["event_ts", "part_number_norm"]]
                .rename(columns={"part_number_norm": "part_number"})
                .sort_values("event_ts")
                .drop_duplicates(subset=["event_ts"], keep="last")
                .reset_index(drop=True)
            )
            out[str(machine_id)] = timeline
        return out

    def map_part_numbers(self, df_machine: pd.DataFrame, timeline_by_machine: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, float]:
        frame = df_machine.copy()
        machine_id = str(frame["machine_id"].iloc[0])
        timeline = timeline_by_machine.get(machine_id)
        if timeline is None or timeline.empty:
            frame["part_number"] = "UNKNOWN"
            return frame, 0.0

        left = frame[["timestamp"]].copy().sort_values("timestamp")
        left["orig_idx"] = left.index
        right = timeline[["event_ts", "part_number"]].copy().sort_values("event_ts")

        merged = pd.merge_asof(
            left,
            right,
            left_on="timestamp",
            right_on="event_ts",
            direction="backward",
        )

        part_col = merged["part_number"].fillna("UNKNOWN").astype(str)
        out = frame.copy()
        out["part_number"] = "UNKNOWN"
        out.loc[merged["orig_idx"].values, "part_number"] = part_col.values
        coverage = float((out["part_number"] != "UNKNOWN").mean() * 100.0) if len(out) else 0.0
        return out, coverage

    def calculate_safe_limits(self, df_all: pd.DataFrame) -> Dict[str, Dict[str, Dict[str, float]]]:
        result: Dict[str, Dict[str, Dict[str, float]]] = {}
        for machine_id, machine_df in df_all.groupby("machine_id"):
            machine_limits: Dict[str, Dict[str, float]] = {}
            for sensor in SENSOR_COLUMNS:
                if sensor not in machine_df.columns:
                    continue
                series = pd.to_numeric(machine_df[sensor], errors="coerce").dropna()
                if series.empty:
                    continue
                mean = float(series.mean())
                std = float(series.std(ddof=0))
                if std > 0:
                    series = series[(series >= (mean - 3 * std)) & (series <= (mean + 3 * std))]
                if series.empty:
                    continue
                p5 = float(series.quantile(0.05))
                p95 = float(series.quantile(0.95))
                machine_limits[sensor] = {
                    "count": float(len(series)),
                    "min_observed": float(series.min()),
                    "max_observed": float(series.max()),
                    "mean": float(series.mean()),
                    "std": float(series.std(ddof=0)),
                    "safe_min": p5,
                    "safe_max": p95,
                }
            result[str(machine_id)] = machine_limits
        return result

    def create_lstm_sequences(self, df_all: pd.DataFrame) -> List[Dict[str, Any]]:
        sequences: List[Dict[str, Any]] = []
        grouped = df_all.groupby(["machine_id", "part_number", "shift"], dropna=False, sort=False)
        for (machine_id, part_number, shift), group in grouped:
            frame = group.sort_values("timestamp").reset_index(drop=True)
            if len(frame) < (self.sequence_length + self.horizon_cycles):
                continue

            for sensor in SENSOR_COLUMNS:
                if sensor not in frame.columns:
                    frame[sensor] = 0.0
            frame[SENSOR_COLUMNS] = frame[SENSOR_COLUMNS].apply(pd.to_numeric, errors="coerce").ffill().bfill().fillna(0.0)

            for idx in range(self.sequence_length, len(frame) - self.horizon_cycles + 1):
                past = frame.iloc[idx - self.sequence_length : idx]
                future = frame.iloc[idx : idx + self.horizon_cycles]

                row = {
                    "context": {
                        "machine_id": str(machine_id),
                        "part_number": str(part_number),
                        "shift": str(shift),
                        "date": str(frame.iloc[idx]["timestamp"].date()),
                        "timestamp_start": str(past.iloc[0]["timestamp"]),
                        "timestamp_end": str(future.iloc[-1]["timestamp"]),
                    },
                    "X": past[SENSOR_COLUMNS].to_numpy(dtype=float).tolist(),
                    "Y_scrap_rates": future["scrap_rate"].astype(float).tolist(),
                    "Y_has_scrap": future["has_scrap"].astype(int).tolist(),
                }
                sequences.append(row)
                if self.max_sequences and len(sequences) >= self.max_sequences:
                    LOGGER.warning("Sequence limit reached (%s). Truncating output.", self.max_sequences)
                    return sequences
        return sequences

    def save_outputs(
        self,
        machine_results: List[MachineProcessResult],
        all_df: pd.DataFrame,
        sequences: List[Dict[str, Any]],
        safe_limits: Dict[str, Dict[str, Dict[str, float]]],
    ) -> None:
        for result in machine_results:
            out_csv = self.output_dir / f"{result.machine_id}_cleaned.csv"
            result.cleaned_df.to_csv(out_csv, index=False)
            LOGGER.info("Saved %s (%s rows)", out_csv, f"{len(result.cleaned_df):,}")

        out_sequences = self.output_dir / "lstm_sequences.json"
        with out_sequences.open("w", encoding="utf-8") as f:
            json.dump(sequences, f, indent=2, default=str)
        LOGGER.info("Saved %s (%s sequences)", out_sequences, f"{len(sequences):,}")

        safe_limits_path = self.output_dir / "safe_limits_by_machine.json"
        with safe_limits_path.open("w", encoding="utf-8") as f:
            json.dump(safe_limits, f, indent=2)
        LOGGER.info("Saved %s", safe_limits_path)

        metadata = {
            "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
            "total_cycles": int(len(all_df)),
            "total_sequences": int(len(sequences)),
            "machines": [
                {
                    "machine_id": item.machine_id,
                    "raw_rows": int(item.raw_rows),
                    "wide_rows": int(item.wide_rows),
                    "cleaned_rows": int(item.cleaned_rows),
                    "part_mapping_coverage_pct": round(float(item.part_mapping_coverage_pct), 2),
                }
                for item in machine_results
            ],
            "date_range": {
                "start": str(all_df["timestamp"].min()) if len(all_df) else None,
                "end": str(all_df["timestamp"].max()) if len(all_df) else None,
            },
            "scrap_statistics": {
                machine_id: {
                    "scrap_rate_mean": float(group["scrap_rate"].mean()),
                    "scrap_rate_std": float(group["scrap_rate"].std(ddof=0)),
                    "has_scrap_count": int(group["has_scrap"].sum()),
                    "cycles_count": int(len(group)),
                }
                for machine_id, group in all_df.groupby("machine_id")
            },
        }

        out_metadata = self.output_dir / "data_metadata.json"
        with out_metadata.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        LOGGER.info("Saved %s", out_metadata)

    def run(self) -> None:
        LOGGER.info("=" * 88)
        LOGGER.info("DATA TRANSFORMATION PIPELINE")
        LOGGER.info("data_dir=%s", self.data_dir)
        LOGGER.info("mes_file=%s", self.mes_file)
        LOGGER.info("output_dir=%s", self.output_dir)
        LOGGER.info(
            "sequence_length=%s horizon_cycles=%s resample_minutes=%s max_sequences=%s",
            self.sequence_length,
            self.horizon_cycles,
            self.resample_minutes,
            self.max_sequences,
        )
        LOGGER.info("=" * 88)

        timeline_by_machine = self.load_mes_timeline()
        LOGGER.info("Loaded MES timeline for %s machines.", len(timeline_by_machine))

        machine_results: List[MachineProcessResult] = []
        all_frames: List[pd.DataFrame] = []

        for machine_id in MACHINES:
            LOGGER.info("Processing %s...", machine_id)
            long_df = self.load_machine_long(machine_id)
            wide_df = self.pivot_long_to_wide(long_df, machine_id)
            transformed = self._resample_cycles(wide_df)
            transformed = self.fix_scrap_counters(transformed)
            transformed = self.add_shift_columns(transformed)
            transformed, coverage = self.map_part_numbers(transformed, timeline_by_machine)

            result = MachineProcessResult(
                machine_id=machine_id,
                raw_rows=len(long_df),
                wide_rows=len(wide_df),
                cleaned_rows=len(transformed),
                part_mapping_coverage_pct=coverage,
                cleaned_df=transformed,
            )
            machine_results.append(result)
            all_frames.append(transformed)
            LOGGER.info(
                "%s done: raw=%s wide=%s cleaned=%s part_coverage=%.2f%%",
                machine_id,
                f"{result.raw_rows:,}",
                f"{result.wide_rows:,}",
                f"{result.cleaned_rows:,}",
                result.part_mapping_coverage_pct,
            )

        if not all_frames:
            raise RuntimeError("No machine data processed.")

        all_df = pd.concat(all_frames, ignore_index=True).sort_values(["machine_id", "timestamp"]).reset_index(drop=True)
        safe_limits = self.calculate_safe_limits(all_df)
        sequences = self.create_lstm_sequences(all_df)

        self.save_outputs(machine_results, all_df, sequences, safe_limits)

        LOGGER.info("=" * 88)
        LOGGER.info("PIPELINE COMPLETE")
        LOGGER.info("Total cleaned cycles: %s", f"{len(all_df):,}")
        LOGGER.info("Total sequences: %s", f"{len(sequences):,}")
        LOGGER.info("Output directory: %s", self.output_dir)
        LOGGER.info("=" * 88)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transform raw long-format machine data into LSTM-ready datasets.")
    parser.add_argument(
        "--data-dir",
        default=r"c:\new project\New folder\frontend\Data",
        help="Directory containing machine CSV/XLSX files.",
    )
    parser.add_argument(
        "--mes-file",
        default=r"c:\new project\New folder\frontend\Data\MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx",
        help="MES workbook path.",
    )
    parser.add_argument(
        "--output-dir",
        default=r"c:\new project\New folder\cleaned_data_output",
        help="Output directory for cleaned artifacts.",
    )
    parser.add_argument("--sequence-length", type=int, default=30, help="Past steps for X.")
    parser.add_argument("--horizon-cycles", type=int, default=30, help="Future steps for Y.")
    parser.add_argument(
        "--resample-minutes",
        type=int,
        default=5,
        help="Optional resample bucket in minutes. Use 0 to disable.",
    )
    parser.add_argument(
        "--max-sequences",
        type=int,
        default=0,
        help="Optional sequence cap (0 means no cap).",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARN/ERROR).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    pipeline = DataTransformationPipeline(
        data_dir=Path(args.data_dir),
        mes_file=Path(args.mes_file),
        output_dir=Path(args.output_dir),
        sequence_length=args.sequence_length,
        horizon_cycles=args.horizon_cycles,
        resample_minutes=(args.resample_minutes if int(args.resample_minutes) > 0 else None),
        max_sequences=(args.max_sequences if int(args.max_sequences) > 0 else None),
    )
    pipeline.run()


if __name__ == "__main__":
    main()
