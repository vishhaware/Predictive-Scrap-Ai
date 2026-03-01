
import argparse
import hashlib
import json
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, mean_absolute_error, mean_squared_error, roc_auc_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.dummy import DummyClassifier

try:
    import shap
except Exception:  # pragma: no cover
    shap = None

LOGGER = logging.getLogger("csv_horizon_pipeline")
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"X does not have valid feature names, but LGBM.* was fitted with feature names",
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"X does not have valid feature names, but StandardScaler was fitted with feature names",
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"LightGBM binary classifier with TreeExplainer shap values output has changed to a list of ndarray",
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR.parent / "frontend" / "Data"
DEFAULT_MODELS_DIR = BASE_DIR / "models"
DEFAULT_HORIZON_MODELS_DIR = DEFAULT_MODELS_DIR / "horizon"
DEFAULT_MES_WORKBOOK = DEFAULT_DATA_DIR / "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"
DEFAULT_PARAMETER_CSV = BASE_DIR / "AI_cup_parameter_info_cleaned.csv"
DEFAULT_PARAMETER_CSV_V2 = BASE_DIR / "AI_cup_parameter_info_cleaned_v2.csv"

ROLL_WINDOWS = (5, 10, 30)
HORIZONS_MINUTES = (30, 240, 1440)
COUNTER_COLS = ("Scrap_counter", "Shot_counter")
REGRESSION_TARGET_SENSORS = ("Cycle_time", "Injection_pressure")
EPS = 1e-9

CANONICAL_VARIABLES = [
    "Time_on_machine", "Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure",
    "Cycle_time", "Extruder_start_position", "Cyl_tmp_z1", "Cyl_tmp_z2", "Cyl_tmp_z3", "Cyl_tmp_z4",
    "Cyl_tmp_z5", "Cyl_tmp_z6", "Cyl_tmp_z7", "Cyl_tmp_z8", "Switch_position", "Machine_status",
    "Scrap_counter", "Shot_counter", "Shot_size", "Extruder_torque", "Peak_pressure_time",
    "Peak_pressure_position", "Ejector_fix_deviation_torque", "Alrams_array",
]

SET_VALUE_VARIABLES = {"Cyl_tmp_z1", "Cyl_tmp_z2", "Cyl_tmp_z3", "Cyl_tmp_z4", "Cyl_tmp_z5", "Cyl_tmp_z6", "Cyl_tmp_z7", "Cyl_tmp_z8", "Switch_position"}
PRESSURE_VARIABLES = {"Injection_pressure", "Switch_pressure"}
STATUS_VARIABLES = {"Machine_status", "Alrams_array"}
HIGH_IMPORTANCE = {"Cushion", "Injection_time", "Injection_pressure", "Switch_pressure", "Switch_position", "Cycle_time", "Scrap_counter"}
MEDIUM_IMPORTANCE = {"Dosage_time", "Shot_counter", "Shot_size", "Cyl_tmp_z1", "Cyl_tmp_z2", "Cyl_tmp_z3", "Cyl_tmp_z4", "Cyl_tmp_z5", "Cyl_tmp_z6", "Cyl_tmp_z7", "Cyl_tmp_z8", "Ejector_fix_deviation_torque"}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "na", "n/a", "nan", "none", "null"}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(parsed):
        return None
    return parsed


def _machine_short_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "UNKNOWN"
    upper = text.upper()
    if "-" in upper:
        upper = upper.split("-", 1)[0]
    if upper.startswith("M"):
        return upper
    digits = "".join(ch for ch in upper if ch.isdigit())
    return f"M{digits[-3:]}" if digits else upper


def _importance_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 3)


def _risk_bucket(probability: float) -> str:
    p = float(np.clip(probability, 0.0, 1.0))
    if p < 0.3:
        return "LOW"
    if p <= 0.7:
        return "MEDIUM"
    return "HIGH"


def _hash_feature_spec(feature_cols: Sequence[str], windows: Sequence[int], horizons: Sequence[int]) -> str:
    payload = json.dumps({"feature_cols": list(feature_cols), "windows": list(windows), "horizons": list(horizons)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    arr = df.to_numpy(dtype=np.float32, copy=True)
    np.nan_to_num(arr, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return pd.DataFrame(arr, index=df.index, columns=df.columns)


def _sanitize_target_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.apply(pd.to_numeric, errors="coerce")
    out = out.where(np.isfinite(out), np.nan)
    return out


def _predict_positive_probability(model: Any, x: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(x))
        if proba.ndim == 1:
            return np.clip(proba.astype(float), 0.0, 1.0)
        if proba.shape[1] == 1:
            cls = list(getattr(model, "classes_", [0]))
            return np.ones(proba.shape[0], dtype=float) if int(cls[0]) == 1 else np.zeros(proba.shape[0], dtype=float)
        classes = list(getattr(model, "classes_", [0, 1]))
        idx = classes.index(1) if 1 in classes else (proba.shape[1] - 1)
        return np.clip(proba[:, idx].astype(float), 0.0, 1.0)
    pred = np.asarray(model.predict(x)).reshape(-1)
    return np.clip(pred.astype(float), 0.0, 1.0)


def enrich_parameter_csv(input_csv: Path, output_csv: Path) -> pd.DataFrame:
    if not input_csv.exists():
        raise FileNotFoundError(f"Missing parameter CSV: {input_csv}")
    df = pd.read_csv(input_csv)
    if "variable_name" not in df.columns:
        raise ValueError("parameter CSV must contain 'variable_name'")

    df = df.copy()
    df["variable_name"] = df["variable_name"].astype(str).str.strip()
    df = df[df["variable_name"].str.len() > 0]

    missing_vars = [name for name in CANONICAL_VARIABLES if name not in set(df["variable_name"])]
    if missing_vars:
        df = pd.concat([df, pd.DataFrame({"variable_name": missing_vars, "tolerance_plus": np.nan, "tolerance_minus": np.nan})], ignore_index=True)

    def _default_plus(name: str, cur: Any) -> Any:
        ex = _to_float(cur)
        if ex is not None:
            return ex
        if name in SET_VALUE_VARIABLES and name.startswith("Cyl_tmp_"):
            return 5.0
        if name in PRESSURE_VARIABLES:
            return 100.0
        if name == "Switch_position":
            return 0.05
        if name == "Injection_time":
            return 0.03
        return np.nan

    def _default_minus(name: str, cur: Any) -> Any:
        ex = _to_float(cur)
        if ex is not None:
            return ex
        if name in SET_VALUE_VARIABLES and name.startswith("Cyl_tmp_"):
            return -5.0
        if name in PRESSURE_VARIABLES:
            return -100.0
        if name == "Switch_position":
            return -0.05
        if name == "Injection_time":
            return -0.03
        return np.nan

    df["tolerance_plus"] = [_default_plus(name, tol) for name, tol in zip(df["variable_name"], df.get("tolerance_plus", np.nan))]
    df["tolerance_minus"] = [_default_minus(name, tol) for name, tol in zip(df["variable_name"], df.get("tolerance_minus", np.nan))]

    def _vtype(name: str) -> str:
        if name in COUNTER_COLS:
            return "counter"
        if name in STATUS_VARIABLES:
            return "status"
        if name in SET_VALUE_VARIABLES:
            return "set_value"
        return "monitored_result"

    def _importance(name: str) -> str:
        if name in HIGH_IMPORTANCE:
            return "high"
        if name in MEDIUM_IMPORTANCE:
            return "medium"
        if name in STATUS_VARIABLES:
            return "low"
        return "medium"

    df["variable_type"] = df["variable_name"].map(_vtype)
    df["importance"] = df["variable_name"].map(_importance)
    df["default_set_value"] = df["variable_name"].map(lambda n: 500.0 if str(n).startswith("Cyl_tmp_") else np.nan)
    df["notes"] = [f"{vt} feature, model importance {imp}." for vt, imp in zip(df["variable_type"], df["importance"])]

    df = df.drop_duplicates(subset=["variable_name"], keep="last")
    df = df.sort_values(by=["importance", "variable_name"], key=lambda c: c.map(_importance_rank) if c.name == "importance" else c).reset_index(drop=True)
    df = df[["variable_name", "tolerance_plus", "tolerance_minus", "variable_type", "importance", "default_set_value", "notes"]]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    LOGGER.info("parameter CSV enriched: %s", df["variable_type"].value_counts().to_dict())
    return df

def _read_machine_long_csv(csv_path: Path, max_rows: int, chunk_size: int) -> pd.DataFrame:
    required_cols = [
        "device_name", "machine_definition", "variable_name", "value", "timestamp",
        "variable_attribute", "device", "machine_def", "year", "month", "date",
    ]
    frames: List[pd.DataFrame] = []
    rows_left = max_rows if max_rows > 0 else None

    for chunk in pd.read_csv(csv_path, chunksize=max(1000, int(chunk_size)), low_memory=False):
        missing = [col for col in required_cols if col not in chunk.columns]
        if missing:
            raise ValueError(f"{csv_path.name} missing required columns: {missing}")

        if rows_left is not None and rows_left <= 0:
            break
        if rows_left is not None and len(chunk) > rows_left:
            chunk = chunk.iloc[:rows_left].copy()

        chunk = chunk[["machine_definition", "variable_name", "value", "timestamp"]].copy()
        chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], errors="coerce", utc=True)
        chunk["value"] = pd.to_numeric(chunk["value"], errors="coerce")
        chunk = chunk.dropna(subset=["timestamp", "variable_name"])
        if chunk.empty:
            continue

        chunk["machine_id"] = chunk["machine_definition"].map(_machine_short_id)
        frames.append(chunk)
        if rows_left is not None:
            rows_left -= len(chunk)

    if not frames:
        return pd.DataFrame(columns=["machine_id", "timestamp", "variable_name", "value"])
    out = pd.concat(frames, ignore_index=True)
    return out[["machine_id", "timestamp", "variable_name", "value"]].sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


def pivot_to_minute_wide(df_long: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame()
    df = df_long.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df.empty:
        return pd.DataFrame()

    wide = df.pivot_table(index="timestamp", columns="variable_name", values="value", aggfunc="last")
    if wide.empty:
        return pd.DataFrame()

    idx = pd.date_range(wide.index.min().floor("min"), wide.index.max().ceil("min"), freq=freq, tz="UTC")
    wide = wide.reindex(idx)

    counter_cols = [col for col in COUNTER_COLS if col in wide.columns]
    non_counter_cols = [col for col in wide.columns if col not in counter_cols]
    if non_counter_cols:
        wide[non_counter_cols] = wide[non_counter_cols].ffill(limit=5).bfill(limit=2)
    if counter_cols:
        wide[counter_cols] = wide[counter_cols].ffill()
    wide.index.name = "timestamp"
    return wide


def _load_hydra_context(workbook_path: Path) -> pd.DataFrame:
    if not workbook_path.exists():
        LOGGER.warning("MES workbook not found: %s", workbook_path)
        return pd.DataFrame()

    df = pd.read_excel(workbook_path, sheet_name="Data")
    if df.empty:
        return pd.DataFrame()

    col_map = {str(col).strip().lower(): col for col in df.columns}
    ts_col = col_map.get("plant_shift_timestamp")
    machine_col = col_map.get("machine_id")
    if not ts_col or not machine_col:
        return pd.DataFrame()

    keep_map = {
        "timestamp": ts_col,
        "machine_id": machine_col,
        "part_number": col_map.get("part_number"),
        "tool_id": col_map.get("resource_id"),
        "yield_quantity": col_map.get("yield_quantity"),
        "scrap_quantity": col_map.get("scrap_quantity"),
        "strokes_yield_quantity": col_map.get("strokes_yield_quantity"),
        "strokes_total_quantity": col_map.get("strokes_total_quantity"),
    }

    out = pd.DataFrame({k: (df[v] if v is not None else np.nan) for k, v in keep_map.items()})
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
    out = out.dropna(subset=["timestamp"])
    out["machine_id"] = out["machine_id"].map(_machine_short_id)

    for col in ["yield_quantity", "scrap_quantity", "strokes_yield_quantity", "strokes_total_quantity"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    return out.sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


def _merge_machine_hydra(machine_df: pd.DataFrame, hydra_df: pd.DataFrame) -> pd.DataFrame:
    df = machine_df.copy().sort_values("timestamp")
    cols = ["part_number", "tool_id", "yield_quantity", "scrap_quantity", "strokes_yield_quantity", "strokes_total_quantity"]

    if hydra_df.empty:
        for col in cols:
            df[col] = np.nan
    else:
        machine_id = str(df["machine_id"].iloc[0])
        right = hydra_df[hydra_df["machine_id"] == machine_id].copy().sort_values("timestamp")
        if right.empty:
            for col in cols:
                df[col] = np.nan
        else:
            df = pd.merge_asof(df, right, on="timestamp", by="machine_id", direction="backward")

    for col in ["yield_quantity", "scrap_quantity", "strokes_yield_quantity", "strokes_total_quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["scrap_ratio"] = df["scrap_quantity"] / (df["yield_quantity"] + df["scrap_quantity"] + EPS)
    df["strokes_efficiency"] = df["strokes_yield_quantity"] / (df["strokes_total_quantity"] + EPS)
    df["hydra_scrap_counter"] = df["scrap_quantity"].fillna(0.0).cumsum()
    return df


def _is_valid_cumulative_counter(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 10:
        return False
    diffs = s.diff().dropna()
    if diffs.empty:
        return False
    return float((diffs < -1e-6).mean()) <= 0.05


def _select_scrap_counter(df: pd.DataFrame) -> Tuple[pd.Series, str]:
    if "Scrap_counter" in df.columns and _is_valid_cumulative_counter(df["Scrap_counter"]):
        return pd.to_numeric(df["Scrap_counter"], errors="coerce").ffill().fillna(0.0), "machine_scrap_counter"
    if "hydra_scrap_counter" in df.columns:
        return pd.to_numeric(df["hydra_scrap_counter"], errors="coerce").ffill().fillna(0.0), "hydra_cumsum_scrap"
    return pd.Series(np.zeros(len(df), dtype=float), index=df.index), "fallback_zeros"


def _rolling_slope(values: np.ndarray) -> float:
    if values is None or len(values) < 2:
        return 0.0
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr)
    if mask.sum() < 2:
        return 0.0
    x = np.arange(arr.size, dtype=float)[mask]
    y = arr[mask]
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _build_parameter_maps(parameter_df: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float]]:
    setpoint_map: Dict[str, float] = {}
    tolerance_map: Dict[str, float] = {}
    for _, row in parameter_df.iterrows():
        name = str(row.get("variable_name", "")).strip()
        if not name:
            continue
        default_set = _to_float(row.get("default_set_value"))
        plus = _to_float(row.get("tolerance_plus"))
        minus = _to_float(row.get("tolerance_minus"))
        if default_set is not None:
            setpoint_map[name] = float(default_set)
        if plus is not None or minus is not None:
            tolerance_map[name] = max(abs(float(plus or 0.0)), abs(float(minus or 0.0)))
    return setpoint_map, tolerance_map

def engineer_features_for_machine(
    machine_df: pd.DataFrame,
    parameter_df: pd.DataFrame,
    windows: Sequence[int] = ROLL_WINDOWS,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    if machine_df.empty:
        return pd.DataFrame(), [], {}

    df = machine_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df = df.set_index("timestamp")

    setpoint_map, tolerance_map = _build_parameter_maps(parameter_df)

    process_cols = [
        col for col in CANONICAL_VARIABLES
        if col in df.columns and col not in {"Time_on_machine", "Machine_status", "Alrams_array", "Scrap_counter", "Shot_counter"}
    ]

    raw_numeric = df[process_cols].apply(pd.to_numeric, errors="coerce") if process_cols else pd.DataFrame(index=df.index)
    baseline = raw_numeric.head(1000)

    feature_df = pd.DataFrame(index=df.index)
    feature_cols: List[str] = []

    for col in process_cols:
        series_raw = raw_numeric[col]
        series = series_raw.ffill().bfill()

        pct_name = f"{col}__pct_change"
        feature_df[pct_name] = series.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        feature_cols.append(pct_name)

        for window in windows:
            roll = series.rolling(window=window, min_periods=1)
            mean_name = f"{col}__mean_{window}m"
            std_name = f"{col}__std_{window}m"
            min_name = f"{col}__min_{window}m"
            max_name = f"{col}__max_{window}m"
            last_name = f"{col}__last_{window}m"
            trend_name = f"{col}__trend_{window}m"
            spike_name = f"{col}__spike_count_{window}m"
            miss_name = f"{col}__missing_ratio_{window}m"

            feature_df[mean_name] = roll.mean()
            feature_df[std_name] = roll.std().fillna(0.0)
            feature_df[min_name] = roll.min()
            feature_df[max_name] = roll.max()
            feature_df[last_name] = series
            trend_period = max(1, int(window) - 1)
            # Fast slope proxy to avoid expensive per-window polyfit on large runs.
            feature_df[trend_name] = series.diff(periods=trend_period).div(float(trend_period)).fillna(0.0)

            spike_mask = (series > (roll.mean() + (2.0 * roll.std().fillna(0.0)))).astype(float)
            feature_df[spike_name] = spike_mask.rolling(window=window, min_periods=1).sum().fillna(0.0)
            feature_df[miss_name] = series_raw.isna().astype(float).rolling(window=window, min_periods=1).mean().fillna(0.0)
            feature_cols.extend([mean_name, std_name, min_name, max_name, last_name, trend_name, spike_name, miss_name])

        baseline_series = baseline[col].dropna()
        baseline_mean = float(baseline_series.mean()) if not baseline_series.empty else float(series.mean())
        baseline_std = float(baseline_series.std()) if (not baseline_series.empty and baseline_series.std() > 0) else 1.0

        if col.startswith("Cyl_tmp_"):
            norm_name = f"{col}__normalized_temp"
            feature_df[norm_name] = ((series - baseline_mean) / (baseline_std + EPS)).fillna(0.0)
            feature_cols.append(norm_name)

        setpoint = setpoint_map.get(col, baseline_mean)
        tolerance = tolerance_map.get(col)
        dev_name = f"{col}__deviation_from_setpoint"
        dev_pct_name = f"{col}__deviation_pct"
        exceed_name = f"{col}__exceed_threshold"

        deviation = series - float(setpoint)
        feature_df[dev_name] = deviation
        feature_df[dev_pct_name] = deviation / (abs(float(setpoint)) + EPS)
        feature_df[exceed_name] = 0.0 if (tolerance is None or tolerance <= 0) else (np.abs(deviation) > float(tolerance)).astype(float)
        feature_cols.extend([dev_name, dev_pct_name, exceed_name])

    for col in ["yield_quantity", "scrap_quantity", "scrap_ratio", "strokes_efficiency", "hydra_scrap_counter"]:
        feature_df[col] = pd.to_numeric(df.get(col), errors="coerce").ffill().fillna(0.0)
        feature_cols.append(col)

    part_number = df.get("part_number")
    tool_id = df.get("tool_id")
    feature_df["part_number"] = (part_number.astype(str).replace("nan", "UNKNOWN") if part_number is not None else "UNKNOWN")
    feature_df["tool_id"] = (tool_id.astype(str).replace("nan", "UNKNOWN") if tool_id is not None else "UNKNOWN")

    feature_df["part_number_code"] = pd.factorize(feature_df["part_number"])[0].astype(float)
    feature_df["tool_id_code"] = pd.factorize(feature_df["tool_id"])[0].astype(float)
    feature_cols.extend(["part_number_code", "tool_id_code"])

    # Keep raw core sensors for downstream regression target construction.
    for sensor in REGRESSION_TARGET_SENSORS:
        feature_df[sensor] = pd.to_numeric(df.get(sensor), errors="coerce").ffill().fillna(0.0)
    feature_df["Scrap_counter"] = pd.to_numeric(df.get("Scrap_counter"), errors="coerce").ffill().fillna(0.0)
    feature_df["Shot_counter"] = pd.to_numeric(df.get("Shot_counter"), errors="coerce").ffill().fillna(0.0)
    feature_df["machine_id"] = str(machine_df["machine_id"].iloc[0])

    # Downcast numeric features early to keep peak memory under control for multi-machine runs.
    numeric_cols = feature_df.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        feature_df[numeric_cols] = feature_df[numeric_cols].astype(np.float32)

    feature_cols = sorted(set(feature_cols))
    metadata = {"machine_id": str(machine_df["machine_id"].iloc[0]), "process_columns": process_cols, "feature_count": len(feature_cols)}
    return feature_df.reset_index(), feature_cols, metadata


def create_horizon_labels(frame: pd.DataFrame, scrap_counter_col: str = "scrap_counter_source", horizons: Sequence[int] = HORIZONS_MINUTES) -> pd.DataFrame:
    out = frame.copy()
    if scrap_counter_col not in out.columns:
        raise ValueError(f"Missing scrap counter column: {scrap_counter_col}")
    counter = pd.to_numeric(out[scrap_counter_col], errors="coerce").ffill().fillna(0.0)
    for horizon in horizons:
        future = counter.shift(-int(horizon))
        out[f"scrap_event_{horizon}m"] = ((future - counter) > 0).astype(int)
    return out


def _future_mean_target(series: pd.Series, horizon: int) -> pd.Series:
    shifted = [series.shift(-step) for step in range(1, int(horizon) + 1)]
    return pd.concat(shifted, axis=1).mean(axis=1)


def add_regression_targets(frame: pd.DataFrame, horizons: Sequence[int] = HORIZONS_MINUTES) -> pd.DataFrame:
    out = frame.copy()
    for horizon in horizons:
        for sensor in REGRESSION_TARGET_SENSORS:
            if sensor in out.columns:
                out[f"target_{sensor}_{horizon}m"] = _future_mean_target(pd.to_numeric(out[sensor], errors="coerce"), int(horizon))
            else:
                out[f"target_{sensor}_{horizon}m"] = np.nan
    return out


def _split_by_machine_time(frame: pd.DataFrame, train_ratio: float = 0.70, val_ratio: float = 0.15) -> pd.Series:
    split = pd.Series(index=frame.index, dtype="object")
    for _, idx in frame.groupby("machine_id").groups.items():
        ordered = frame.loc[idx].sort_values("timestamp")
        n = len(ordered)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))
        split.loc[ordered.index[:train_end]] = "train"
        split.loc[ordered.index[train_end:val_end]] = "val"
        split.loc[ordered.index[val_end:]] = "test"
    return split

def train_multi_horizon_models(
    frame: pd.DataFrame,
    feature_cols: Sequence[str],
    out_dir: Path,
    data_sources: Dict[str, Any],
    horizons: Sequence[int] = HORIZONS_MINUTES,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {"horizons": {}}

    all_feature_cols = [col for col in feature_cols if col in frame.columns]
    if not all_feature_cols:
        raise RuntimeError("No feature columns found in training frame.")

    frame = frame.copy()
    frame["split"] = _split_by_machine_time(frame)
    feature_spec_hash = _hash_feature_spec(all_feature_cols, ROLL_WINDOWS, horizons)

    for horizon in horizons:
        label_col = f"scrap_event_{horizon}m"
        reg_cols = [f"target_{sensor}_{horizon}m" for sensor in REGRESSION_TARGET_SENSORS]
        subset = frame.dropna(subset=[label_col])
        if subset.empty:
            continue

        x = _sanitize_feature_frame(subset[all_feature_cols])
        y_cls = subset[label_col].astype(int)

        train_mask = subset["split"] == "train"
        val_mask = subset["split"] == "val"
        test_mask = subset["split"] == "test"
        if int(train_mask.sum()) == 0 or int(test_mask.sum()) == 0:
            continue

        scaler = StandardScaler()
        x_train = scaler.fit_transform(x.loc[train_mask]).astype(np.float32, copy=False)
        x_test = scaler.transform(x.loc[test_mask]).astype(np.float32, copy=False)
        y_train = y_cls.loc[train_mask]
        y_test = y_cls.loc[test_mask]

        positives = int(y_train.sum())
        negatives = int(len(y_train) - positives)
        class_weight = {0: 1.0, 1: float(max(1.0, negatives / max(1, positives)))}

        if y_train.nunique() < 2:
            cls_model = DummyClassifier(strategy="constant", constant=int(y_train.iloc[0]) if len(y_train) else 0)
            cls_model.fit(x_train, y_train)
        else:
            cls_model = lgb.LGBMClassifier(
                objective="binary",
                n_estimators=320,
                learning_rate=0.05,
                num_leaves=63,
                class_weight=class_weight,
                random_state=42,
                n_jobs=-1,
                verbosity=-1,
            )
            cls_model.fit(x_train, y_train)
        y_prob_test = _predict_positive_probability(cls_model, x_test)

        if y_test.nunique() > 1:
            roc_auc = float(roc_auc_score(y_test, y_prob_test))
            pr_auc = float(average_precision_score(y_test, y_prob_test))
        else:
            # Keep metrics finite in sparse-label slices.
            roc_auc = 0.5
            pr_auc = float(y_test.mean()) if len(y_test) else 0.0

        y_reg = _sanitize_target_frame(subset[reg_cols])
        valid_reg_mask = y_reg.notna().all(axis=1).to_numpy()
        split_np = subset["split"].astype(str).to_numpy()
        train_np = train_mask.to_numpy()
        test_np = test_mask.to_numpy()

        reg_metrics: Dict[str, float] = {"mae": float("nan"), "rmse": float("nan")}
        reg_model: Optional[MultiOutputRegressor] = None

        reg_train_idx = np.flatnonzero(valid_reg_mask & train_np & (split_np == "train"))
        reg_test_idx = np.flatnonzero(valid_reg_mask & test_np & (split_np == "test"))

        if reg_train_idx.size > 0 and reg_test_idx.size > 0:
            # Guardrail for memory pressure on large multi-machine runs.
            max_reg_rows = 90000
            if reg_train_idx.size > max_reg_rows:
                rng = np.random.default_rng(42)
                reg_train_idx = rng.choice(reg_train_idx, size=max_reg_rows, replace=False)

            try:
                x_values = x.to_numpy(dtype=np.float32, copy=False)
                y_values = y_reg.to_numpy(dtype=np.float32, copy=False)
                reg_x_train = scaler.transform(x_values[reg_train_idx]).astype(np.float32, copy=False)
                reg_x_test = scaler.transform(x_values[reg_test_idx]).astype(np.float32, copy=False)
                reg_y_train = y_values[reg_train_idx]
                reg_y_test = y_values[reg_test_idx]

                reg_model = MultiOutputRegressor(
                    lgb.LGBMRegressor(
                        objective="regression",
                        n_estimators=160,
                        learning_rate=0.05,
                        num_leaves=31,
                        max_bin=127,
                        min_child_samples=120,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        random_state=42,
                        n_jobs=1,
                        verbosity=-1,
                    )
                )
                reg_model.fit(reg_x_train, reg_y_train)
                reg_pred = reg_model.predict(reg_x_test)
                reg_metrics = {
                    "mae": float(mean_absolute_error(reg_y_test, reg_pred)),
                    "rmse": float(mean_squared_error(reg_y_test, reg_pred) ** 0.5),
                }
            except Exception as exc:
                LOGGER.warning("Regression model skipped for %sm due to memory/error: %s", horizon, exc)
                reg_model = None

        model_path = out_dir / f"scrap_{horizon}m_model.joblib"
        scaler_path = out_dir / f"scrap_{horizon}m_scaler.joblib"
        features_path = out_dir / f"scrap_{horizon}m_feature_list.joblib"
        metadata_path = out_dir / f"scrap_{horizon}m_metadata.json"
        reg_model_path = out_dir / f"reg_{horizon}m_model.joblib"

        joblib.dump(cls_model, model_path)
        joblib.dump(scaler, scaler_path)
        joblib.dump(all_feature_cols, features_path)
        if reg_model is not None:
            joblib.dump(reg_model, reg_model_path)

        metadata = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "data_sources": data_sources,
            "rows_train": int(train_mask.sum()),
            "rows_val": int(val_mask.sum()),
            "rows_test": int(test_mask.sum()),
            "metrics": {"classifier": {"roc_auc": roc_auc, "pr_auc": pr_auc}, "regression": reg_metrics},
            "feature_spec_hash": feature_spec_hash,
            "horizon_minutes": int(horizon),
            "feature_count": len(all_feature_cols),
        }
        with open(metadata_path, "w", encoding="utf-8") as fp:
            json.dump(metadata, fp, indent=2)

        results["horizons"][f"{horizon}m"] = {
            "model_path": str(model_path),
            "scaler_path": str(scaler_path),
            "feature_list_path": str(features_path),
            "metadata_path": str(metadata_path),
            "reg_model_path": str(reg_model_path) if reg_model is not None else None,
            "roc_auc": roc_auc,
            "pr_auc": pr_auc,
            "regression": reg_metrics,
        }

    return results


def _build_latest_feature_rows_by_machine(frame: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for machine_id, group in frame.groupby("machine_id"):
        out[str(machine_id)] = group.sort_values("timestamp").tail(1).copy()
    return out


def export_horizon_predictions_to_excel(feature_frame: pd.DataFrame, horizon_dir: Path, output_dir: Path, horizons: Sequence[int] = HORIZONS_MINUTES) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_by_machine = _build_latest_feature_rows_by_machine(feature_frame)
    explainer_cache: Dict[int, Any] = {}

    for machine_id, latest in latest_by_machine.items():
        rows: List[Dict[str, Any]] = []
        for horizon in horizons:
            model_path = horizon_dir / f"scrap_{horizon}m_model.joblib"
            scaler_path = horizon_dir / f"scrap_{horizon}m_scaler.joblib"
            features_path = horizon_dir / f"scrap_{horizon}m_feature_list.joblib"
            if not (model_path.exists() and scaler_path.exists() and features_path.exists()):
                continue

            model = joblib.load(model_path)
            scaler = joblib.load(scaler_path)
            feature_cols = joblib.load(features_path)
            x = latest.copy()
            for col in feature_cols:
                if col not in x.columns:
                    x[col] = 0.0
            x = _sanitize_feature_frame(x[feature_cols])
            xs = scaler.transform(x).astype(np.float32, copy=False)

            probability = float(_predict_positive_probability(model, xs)[0])
            risk = _risk_bucket(probability)

            top_features: List[str] = []
            if shap is not None:
                try:
                    if horizon not in explainer_cache:
                        explainer_cache[horizon] = shap.TreeExplainer(model)
                    shap_values = explainer_cache[horizon].shap_values(np.asarray(xs))
                    values = np.asarray(shap_values[-1])[0] if isinstance(shap_values, list) else np.asarray(shap_values)[0]
                    ranked = sorted(zip(feature_cols, values), key=lambda pair: abs(pair[1]), reverse=True)[:3]
                    top_features = [f"{name}:{float(val):.4f}" for name, val in ranked]
                except Exception:
                    top_features = []

            rows.append({
                "timestamp": pd.to_datetime(latest["timestamp"].iloc[0], utc=True).isoformat(),
                "part_number": str(latest.get("part_number", pd.Series(["UNKNOWN"])).iloc[0]),
                "tool_id": str(latest.get("tool_id", pd.Series(["UNKNOWN"])).iloc[0]),
                "horizon_minutes": int(horizon),
                "predicted_scrap_probability": round(probability, 6),
                "predicted_scrap_risk": risk,
                "top3_contributing_features": ", ".join(top_features),
            })

        if rows:
            out_path = output_dir / f"predictions_{machine_id}.xlsx"
            pd.DataFrame(rows).to_excel(out_path, index=False)
            LOGGER.info("excel export created: %s", out_path)

def build_minute_horizon_training_frame(
    data_dir: Path,
    machine_files: Sequence[str],
    mes_workbook: Path,
    parameter_df: pd.DataFrame,
    max_rows_per_machine: int,
    chunk_size: int,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    hydra_df = _load_hydra_context(mes_workbook)
    all_machine_frames: List[pd.DataFrame] = []
    all_feature_cols: set[str] = set()
    data_sources: Dict[str, Any] = {
        "data_dir": str(data_dir.resolve()),
        "mes_workbook": str(mes_workbook.resolve()) if mes_workbook.exists() else str(mes_workbook),
        "machine_files": list(machine_files),
    }

    for file_name in machine_files:
        csv_path = data_dir / file_name
        if not csv_path.exists():
            LOGGER.warning("machine file missing: %s", csv_path)
            continue

        long_df = _read_machine_long_csv(csv_path, max_rows=max_rows_per_machine, chunk_size=chunk_size)
        if long_df.empty:
            LOGGER.warning("machine file empty after parse: %s", csv_path)
            continue

        for machine_id, machine_long in long_df.groupby("machine_id"):
            wide = pivot_to_minute_wide(machine_long)
            if wide.empty:
                continue

            machine_frame = wide.reset_index()
            machine_frame["machine_id"] = machine_id
            machine_frame = _merge_machine_hydra(machine_frame, hydra_df)

            scrap_series, scrap_source = _select_scrap_counter(machine_frame)
            machine_frame["scrap_counter_source"] = scrap_series
            machine_frame["scrap_counter_source_name"] = scrap_source

            features, feature_cols, _ = engineer_features_for_machine(machine_frame, parameter_df=parameter_df)
            if features.empty:
                continue

            features["scrap_counter_source"] = scrap_series.values
            features = create_horizon_labels(features, scrap_counter_col="scrap_counter_source", horizons=HORIZONS_MINUTES)
            features = add_regression_targets(features, horizons=HORIZONS_MINUTES)

            all_machine_frames.append(features)
            all_feature_cols.update(feature_cols)
            LOGGER.info("machine %s rows=%s features=%s", machine_id, len(features), len(feature_cols))

    if not all_machine_frames:
        return pd.DataFrame(), [], data_sources

    # Avoid a full-frame sort copy here; per-machine temporal ordering is handled later in split logic.
    frame = pd.concat(all_machine_frames, ignore_index=True, copy=False)
    feature_cols_sorted = sorted(all_feature_cols)
    for col in feature_cols_sorted:
        if col not in frame.columns:
            frame[col] = np.float32(0.0)

    # Keep memory footprint predictable before training.
    numeric_cols = frame.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) > 0:
        frame[numeric_cols] = frame[numeric_cols].astype(np.float32)
    return frame, feature_cols_sorted, data_sources


def _discover_machine_files(data_dir: Path, provided: Optional[Sequence[str]]) -> List[str]:
    if provided:
        return [str(name) for name in provided]
    return sorted(path.name for path in data_dir.glob("M*.csv"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train minute-horizon scrap prediction models from machine CSV + MES context.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory containing machine CSV files")
    parser.add_argument("--models-dir", default=str(DEFAULT_MODELS_DIR), help="Base models directory")
    parser.add_argument("--horizon-dir", default=str(DEFAULT_HORIZON_MODELS_DIR), help="Output directory for horizon artifacts")
    parser.add_argument("--machine-files", nargs="*", default=None, help="Machine CSV files to use")
    parser.add_argument("--max-rows-per-machine", type=int, default=300000, help="Max rows read per machine CSV")
    parser.add_argument("--chunk-size", type=int, default=50000, help="CSV read chunk size")
    parser.add_argument("--mes-workbook", default=str(DEFAULT_MES_WORKBOOK), help="Path to MES workbook")
    parser.add_argument("--parameter-csv", default=str(DEFAULT_PARAMETER_CSV), help="Path to parameter tolerance CSV v1")
    parser.add_argument("--parameter-csv-v2", default=str(DEFAULT_PARAMETER_CSV_V2), help="Output enriched parameter CSV path")
    parser.add_argument("--only-enrich-csv", action="store_true", help="Only enrich CSV and exit")
    parser.add_argument("--skip-excel-export", action="store_true", help="Skip Excel prediction export")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    data_dir = Path(args.data_dir)
    models_dir = Path(args.models_dir)
    horizon_dir = Path(args.horizon_dir)
    mes_workbook = Path(args.mes_workbook)
    parameter_csv = Path(args.parameter_csv)
    parameter_csv_v2 = Path(args.parameter_csv_v2)

    parameter_df = enrich_parameter_csv(parameter_csv, parameter_csv_v2)
    if args.only_enrich_csv:
        print(json.dumps({"ok": True, "parameter_csv_v2": str(parameter_csv_v2)}, indent=2))
        return

    machine_files = _discover_machine_files(data_dir, args.machine_files)
    if not machine_files:
        raise RuntimeError(f"No machine files found in {data_dir}")

    frame, feature_cols, data_sources = build_minute_horizon_training_frame(
        data_dir=data_dir,
        machine_files=machine_files,
        mes_workbook=mes_workbook,
        parameter_df=parameter_df,
        max_rows_per_machine=int(args.max_rows_per_machine),
        chunk_size=int(args.chunk_size),
    )
    if frame.empty:
        raise RuntimeError("No rows available for horizon model training.")

    horizon_results = train_multi_horizon_models(
        frame=frame,
        feature_cols=feature_cols,
        out_dir=horizon_dir,
        data_sources=data_sources,
        horizons=HORIZONS_MINUTES,
    )

    if not args.skip_excel_export:
        export_horizon_predictions_to_excel(feature_frame=frame, horizon_dir=horizon_dir, output_dir=models_dir, horizons=HORIZONS_MINUTES)

    print(json.dumps({"ok": True, "rows": len(frame), "feature_count": len(feature_cols), "horizons": horizon_results.get("horizons", {})}, indent=2))


if __name__ == "__main__":
    main()
