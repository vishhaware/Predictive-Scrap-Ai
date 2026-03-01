import logging
import os
import re
import json
import warnings
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import joblib
except Exception:
    joblib = None

try:
    import shap
except Exception:
    shap = None

try:
    from dynamic_limits import calculate_dynamic_limits
except ImportError:
    from .dynamic_limits import calculate_dynamic_limits
try:
    from model_registry import get_model_bundle, load_registry, resolve_active_model_id
except ImportError:
    from .model_registry import get_model_bundle, load_registry, resolve_active_model_id

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
HORIZON_MODELS_DIR = os.path.join(MODELS_DIR, "horizon")
FORECASTER_PATH = os.path.join(MODELS_DIR, "sensor_forecaster_lagged.pkl")
SCRAP_RISK_PATH = os.path.join(MODELS_DIR, "lightgbm_scrap_risk_wide.pkl")
FUTURE_RISK_THRESHOLD = 0.60
DEFAULT_HORIZON_STEPS = 1920 # 32 hours (4 shifts of 8 hours)
MAX_HISTORY_ROWS = 240
DEFAULT_HORIZON_MINUTES = (30, 240, 1440)
EPS = 1e-9

# === CSV Audit: all 25 variables found in M231-11.csv ===
# New high-correlation variables added: Shot_size (0.9999), Ejector_fix_deviation_torque (0.990)
# Flatline/dead sensors (std==0): Cyl_tmp_z2, Cyl_tmp_z6, Cyl_tmp_z7, Extruder_torque (still mapped for telemetry)
# Standard thresholds from AI_cup_parameter_info
STANDARD_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "cushion": {"min": -0.5, "max": 0.5},           # +/- 0.5 mm (applied as delta or absolute depending on setpoint)
    "injection_time": {"min": -0.03, "max": 0.03},  # +/- 0.03 s
    "dosage_time": {"min": -1.0, "max": 1.0},      # +/- 1 s
    "injection_pressure": {"min": -100.0, "max": 100.0}, # +/- 100 bar
    "switch_pressure": {"min": -100.0, "max": 100.0},    # +/- 100 bar
    "temp_z1": {"min": -5.0, "max": 5.0},          # +/- 5 °C
    "temp_z2": {"min": -5.0, "max": 5.0},
    "temp_z3": {"min": -5.0, "max": 5.0},
    "temp_z4": {"min": -5.0, "max": 5.0},
    "temp_z5": {"min": -5.0, "max": 5.0},
    "temp_z8": {"min": -5.0, "max": 5.0},
    "switch_position": {"min": -0.05, "max": 0.05}, # +/- 0.05 mm
}

RAW_TO_FRONTEND_SENSOR_MAP: Dict[str, str] = {
    "Cushion": "cushion",
    "Injection_time": "injection_time",
    "Dosage_time": "dosage_time",
    "Injection_pressure": "injection_pressure",
    "Switch_pressure": "switch_pressure",
    "Cycle_time": "cycle_time",
    "Cyl_tmp_z1": "temp_z1",
    "Cyl_tmp_z2": "temp_z2",
    "Cyl_tmp_z3": "temp_z3",
    "Cyl_tmp_z4": "temp_z4",
    "Cyl_tmp_z5": "temp_z5",
    # NEW: CSV Audit high-correlation variables
    "Shot_size": "shot_size",                           # corr=0.9999 with Scrap_counter!
    "Ejector_fix_deviation_torque": "ejector_torque",  # corr=0.990  with Scrap_counter
    "Cyl_tmp_z8": "temp_z8",                           # active zone 50-60C, corr=0.9999
    "Cyl_tmp_z6": "temp_z6",                           # flatline (0) - pass-through
    "Cyl_tmp_z7": "temp_z7",                           # flatline (0) - pass-through
    # Existing pass-through mappings
    "Extruder_start_position": "extruder_start_position",
    "Extruder_torque": "extruder_torque",
    "Peak_pressure_time": "peak_pressure_time",
    "Peak_pressure_position": "peak_pressure_position",
    "Switch_position": "switch_position",
    "Machine_status": "machine_status",
    "Scrap_counter": "scrap_counter",
    "Shot_counter": "shot_counter",
}
FRONTEND_TO_RAW_SENSOR_MAP: Dict[str, str] = {
    frontend_key: raw_name for raw_name, frontend_key in RAW_TO_FRONTEND_SENSOR_MAP.items()
}

_FORECASTER_ARTIFACT: Optional[Dict[str, Any]] = None
_SCRAP_RISK_MODEL: Any = None
_SCRAP_RISK_FEATURES: Optional[List[str]] = None
_MODELS_LOADED = False
_HORIZON_CACHE: Dict[int, Dict[str, Any]] = {}
_HORIZON_EXPLAINERS: Dict[int, Any] = {}


def _get_registry() -> Dict[str, Any]:
    try:
        return load_registry()
    except Exception:
        return {}


def _load_bundle_artifact(bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(bundle, dict):
        return None
    artifact_path = bundle.get("artifact_path")
    if not artifact_path:
        return None
    if joblib is None:
        return None
    if not os.path.exists(str(artifact_path)):
        return None
    try:
        loaded = joblib.load(str(artifact_path))
        if isinstance(loaded, dict):
            return loaded
    except Exception as exc:
        logger.warning("Failed to load registry bundle artifact %s: %s", artifact_path, exc)
    return None


def _resolve_task_bundle(
    task: str,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    registry = _get_registry()
    model_id, scope = resolve_active_model_id(registry, task, machine_id, part_number)
    bundle = get_model_bundle(registry, model_id)
    artifact = _load_bundle_artifact(bundle)
    meta = {
        "task": task,
        "model_id": model_id,
        "scope": scope,
        "family": (bundle or {}).get("family"),
        "feature_spec_hash": (bundle or {}).get("feature_spec_hash"),
        "artifact_path": (bundle or {}).get("artifact_path"),
    }
    if isinstance(artifact, dict):
        meta["family"] = artifact.get("family") or meta.get("family")
        meta["feature_spec_hash"] = artifact.get("feature_spec_hash") or meta.get("feature_spec_hash")
    return artifact, meta


def get_active_model_metadata(
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> Dict[str, Any]:
    _, clf_meta = _resolve_task_bundle("scrap_classifier", machine_id, part_number)
    _, frc_meta = _resolve_task_bundle("sensor_forecaster", machine_id, part_number)
    return {"scrap_classifier": clf_meta, "sensor_forecaster": frc_meta}


def _to_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(parsed):
        return None
    return parsed


def _risk_bucket(probability: float) -> str:
    p = float(np.clip(probability, 0.0, 1.0))
    if p < 0.3:
        return "LOW"
    if p <= 0.7:
        return "MEDIUM"
    return "HIGH"


def _with_feature_names(model: Any, x: Any, feature_cols: Optional[List[str]] = None) -> Any:
    if isinstance(x, pd.DataFrame):
        return x
    if not isinstance(x, np.ndarray):
        return x

    arr = np.asarray(x)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        return x

    columns: Optional[List[str]] = None
    if isinstance(feature_cols, list) and len(feature_cols) == arr.shape[1]:
        columns = [str(col) for col in feature_cols]
    elif hasattr(model, "feature_name_"):
        names = getattr(model, "feature_name_")
        if isinstance(names, (list, tuple)) and len(names) == arr.shape[1]:
            columns = [str(col) for col in names]
    elif hasattr(model, "feature_names_in_"):
        names = list(getattr(model, "feature_names_in_", []))
        if len(names) == arr.shape[1]:
            columns = [str(col) for col in names]

    if columns is None:
        return x
    return pd.DataFrame(arr, columns=columns)


def _predict_positive_probability(model: Any, x: Any, feature_cols: Optional[List[str]] = None) -> float:
    model_input = _with_feature_names(model, x, feature_cols=feature_cols)
    if hasattr(model, "predict_proba"):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            proba = np.asarray(model.predict_proba(model_input))
        if proba.ndim == 1:
            return float(np.clip(proba.reshape(-1)[0], 0.0, 1.0))
        if proba.shape[1] == 1:
            cls = list(getattr(model, "classes_", [0]))
            return 1.0 if int(cls[0]) == 1 else 0.0
        classes = list(getattr(model, "classes_", [0, 1]))
        idx = classes.index(1) if 1 in classes else (proba.shape[1] - 1)
        return float(np.clip(proba[:, idx][0], 0.0, 1.0))
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"X does not have valid feature names, but LGBMClassifier was fitted with feature names",
            category=UserWarning,
        )
        pred = np.asarray(model.predict(model_input)).reshape(-1)
    return float(np.clip(pred[0], 0.0, 1.0))


def _load_parameter_metadata() -> pd.DataFrame:
    candidates = [
        os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned_v2.csv"),
        os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned.csv"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            return pd.read_csv(path)
        except Exception:
            continue
    return pd.DataFrame(columns=["variable_name", "tolerance_plus", "tolerance_minus", "default_set_value"])


def _trend_from_tail(series: pd.Series, window: int) -> float:
    tail = pd.to_numeric(series, errors="coerce").tail(max(2, int(window)))
    vals = tail.to_numpy(dtype=float)
    mask = np.isfinite(vals)
    if mask.sum() < 2:
        return 0.0
    x = np.arange(vals.size, dtype=float)[mask]
    y = vals[mask]
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _extract_model_features(model_obj: Any) -> Optional[List[str]]:
    if isinstance(model_obj, dict):
        for key in ("model_features", "feature_names", "input_features", "features"):
            candidate = model_obj.get(key)
            if isinstance(candidate, (list, tuple)) and len(candidate) > 0:
                return [str(item) for item in candidate]
        return None

    if hasattr(model_obj, "feature_name_"):
        feature_name = getattr(model_obj, "feature_name_")
        if isinstance(feature_name, (list, tuple)) and len(feature_name) > 0:
            return [str(item) for item in feature_name]

    if hasattr(model_obj, "feature_names_in_"):
        feature_name = getattr(model_obj, "feature_names_in_")
        if isinstance(feature_name, (list, tuple, np.ndarray)) and len(feature_name) > 0:
            return [str(item) for item in list(feature_name)]

    return None


def _load_models() -> None:
    global _MODELS_LOADED, _FORECASTER_ARTIFACT, _SCRAP_RISK_MODEL, _SCRAP_RISK_FEATURES
    if _MODELS_LOADED:
        return
    _MODELS_LOADED = True

    if joblib is None:
        logger.warning("joblib is unavailable; forecasting models will not be loaded.")
        return

    if os.path.exists(FORECASTER_PATH):
        try:
            artifact = joblib.load(FORECASTER_PATH)
            if isinstance(artifact, dict) and "model" in artifact:
                _FORECASTER_ARTIFACT = artifact
            else:
                logger.error("Invalid forecaster artifact format in %s", FORECASTER_PATH)
        except Exception as exc:
            logger.error("Failed to load forecaster model: %s", exc)

    if os.path.exists(SCRAP_RISK_PATH):
        try:
            artifact = joblib.load(SCRAP_RISK_PATH)
            if isinstance(artifact, dict) and "model" in artifact:
                _SCRAP_RISK_MODEL = artifact.get("model")
                _SCRAP_RISK_FEATURES = _extract_model_features(artifact)
            else:
                _SCRAP_RISK_MODEL = artifact
                _SCRAP_RISK_FEATURES = _extract_model_features(artifact)
        except Exception as exc:
            logger.error("Failed to load scrap-risk model: %s", exc)


def telemetry_to_sensor_row(telemetry: Dict[str, Any]) -> Dict[str, float]:
    row: Dict[str, float] = {}
    if not isinstance(telemetry, dict):
        return row

    for key, payload in telemetry.items():
        raw_name = FRONTEND_TO_RAW_SENSOR_MAP.get(str(key), str(key))

        if isinstance(payload, dict):
            raw_value = payload.get("value")
        else:
            raw_value = payload

        numeric_value = _to_float(raw_value)
        if numeric_value is None:
            continue
        row[raw_name] = float(numeric_value)

    return row


def _last_timestamp_from_history(history: pd.DataFrame) -> pd.Timestamp:
    if isinstance(history.index, pd.DatetimeIndex) and len(history.index) > 0:
        try:
            return pd.Timestamp(history.index[-1]).tz_localize(None)
        except TypeError:
            return pd.Timestamp(history.index[-1])
    return pd.Timestamp.utcnow().tz_localize(None)


def _prepare_history_window(
    recent_history: pd.DataFrame, sensor_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    if recent_history is None or recent_history.empty:
        return pd.DataFrame()

    history = recent_history.copy().tail(MAX_HISTORY_ROWS)
    numeric = history.select_dtypes(include=[np.number]).copy()
    if numeric.empty:
        return pd.DataFrame()

    if sensor_columns:
        for sensor in sensor_columns:
            if sensor not in numeric.columns:
                numeric[sensor] = 0.0
        numeric = numeric[sensor_columns]

    return numeric.ffill().fillna(0.0)


def _ema_fallback_forecast(
    history_window: pd.DataFrame,
    safe_limits: Dict[str, Dict[str, float]],
    num_steps: int,
    start_ts: pd.Timestamp,
) -> pd.DataFrame:
    if history_window.empty:
        return pd.DataFrame()

    ema_alpha = 0.05
    column_means = history_window.mean(numeric_only=True).to_dict()
    current_state = history_window.iloc[-1].to_dict()
    records: List[Dict[str, Any]] = []

    for step in range(num_steps):
        for column in list(current_state.keys()):
            current_val = _to_float(current_state.get(column))
            mean_val = _to_float(column_means.get(column))
            if current_val is None or mean_val is None:
                continue
            next_val = (ema_alpha * mean_val) + ((1.0 - ema_alpha) * current_val)

            limits = safe_limits.get(column)
            if isinstance(limits, dict):
                min_val = _to_float(limits.get("min"))
                max_val = _to_float(limits.get("max"))
                if min_val is not None and max_val is not None:
                    next_val = max(min_val, min(max_val, next_val))
            current_state[column] = next_val

        record = {k: float(v) for k, v in current_state.items() if _to_float(v) is not None}
        record["timestamp"] = start_ts + timedelta(minutes=step + 1)
        records.append(record)

    return pd.DataFrame(records)


def _resolve_forecaster_components() -> Optional[Tuple[Any, List[str], List[str], int]]:
    if not isinstance(_FORECASTER_ARTIFACT, dict):
        return None

    model = _FORECASTER_ARTIFACT.get("model")
    sensor_columns = _FORECASTER_ARTIFACT.get("sensor_columns")
    input_features = _FORECASTER_ARTIFACT.get("input_features")
    num_lags = _FORECASTER_ARTIFACT.get("num_lags")

    if model is None:
        return None
    if not isinstance(sensor_columns, (list, tuple)) or not sensor_columns:
        return None
    if not isinstance(input_features, (list, tuple)) or not input_features:
        return None
    if not isinstance(num_lags, int) or num_lags < 1:
        return None

    return model, [str(c) for c in sensor_columns], [str(f) for f in input_features], num_lags


def _resolve_column_index_aliases(model_features: List[str]) -> Optional[List[str]]:
    """Map generic Column_N model features back to forecaster input feature names when possible."""
    if not model_features:
        return None

    if not all(re.fullmatch(r"column_\d+", str(name).strip().lower()) for name in model_features):
        return None

    components = _resolve_forecaster_components()
    if components is None:
        return None

    _, _, input_features, _ = components
    index_to_feature = {idx: feature for idx, feature in enumerate(input_features)}

    resolved: List[str] = []
    for feature_name in model_features:
        try:
            idx = int(str(feature_name).split("_")[-1])
        except (TypeError, ValueError):
            return None
        resolved_name = index_to_feature.get(idx)
        if resolved_name is None:
            return None
        resolved.append(resolved_name)
    return resolved


def _build_model_feature_frame(
    forecast_df: pd.DataFrame,
    model_features: List[str],
    recent_history: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """
    Build model-ready features, including lag features derived from recent history + forecast horizon.
    """
    if forecast_df is None or forecast_df.empty:
        return pd.DataFrame(columns=model_features)

    # Resolve generic model names (Column_0..N) to actual sensor/lag feature names if available.
    resolved_features = _resolve_column_index_aliases(model_features) or list(model_features)

    history_numeric = (
        recent_history.select_dtypes(include=[np.number]).copy()
        if recent_history is not None and not recent_history.empty
        else pd.DataFrame()
    )
    if history_numeric.empty:
        history_numeric = pd.DataFrame(index=[0])

    # Collect base sensors required by model features.
    required_sensors: List[str] = []
    for feature in resolved_features:
        if "_lag_" in feature:
            sensor_name, lag_suffix = feature.rsplit("_lag_", 1)
            if lag_suffix.isdigit() and sensor_name not in required_sensors:
                required_sensors.append(sensor_name)
        elif feature not in required_sensors:
            required_sensors.append(feature)

    # Ensure both history and forecast expose all required sensors.
    future_numeric = forecast_df.copy()
    last_known: Dict[str, Any] = {}
    if recent_history is not None and not recent_history.empty:
        last_known = recent_history.ffill().fillna(0.0).iloc[-1].to_dict()

    for sensor in required_sensors:
        if sensor not in history_numeric.columns:
            history_numeric[sensor] = _to_float(last_known.get(sensor)) or 0.0
        if sensor not in future_numeric.columns:
            future_numeric[sensor] = _to_float(last_known.get(sensor)) or 0.0

    history_numeric = history_numeric[required_sensors].ffill().fillna(0.0)
    future_numeric = (
        future_numeric[required_sensors]
        .apply(pd.to_numeric, errors="coerce")
        .ffill()
        .fillna(0.0)
    )

    combined = pd.concat([history_numeric, future_numeric], ignore_index=True)
    history_len = len(history_numeric)

    model_frame = pd.DataFrame(index=future_numeric.index, columns=model_features, dtype=float)
    feature_positions = {name: idx for idx, name in enumerate(model_features)}

    for row_idx in range(len(future_numeric)):
        combined_idx = history_len + row_idx
        for model_feature, resolved_feature in zip(model_features, resolved_features):
            if "_lag_" in resolved_feature:
                sensor_name, lag_suffix = resolved_feature.rsplit("_lag_", 1)
                if lag_suffix.isdigit():
                    lag = int(lag_suffix)
                    source_idx = combined_idx - lag
                    value = 0.0
                    if source_idx >= 0 and sensor_name in combined.columns:
                        value = _to_float(combined.iat[source_idx, combined.columns.get_loc(sensor_name)]) or 0.0
                else:
                    value = _to_float(future_numeric.iat[row_idx, future_numeric.columns.get_loc(resolved_feature)]) or 0.0 if resolved_feature in future_numeric.columns else 0.0
            else:
                value = (
                    _to_float(future_numeric.iat[row_idx, future_numeric.columns.get_loc(resolved_feature)])
                    if resolved_feature in future_numeric.columns
                    else None
                )
                value = 0.0 if value is None else float(value)

            model_frame.iat[row_idx, feature_positions[model_feature]] = float(value)

    return model_frame.fillna(0.0)


def _generate_future_horizon(
    recent_history: pd.DataFrame,
    num_steps: int = DEFAULT_HORIZON_STEPS,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> pd.DataFrame:
    """
    Recursive autoregressive sensor forecasting for future horizon generation.
    """
    _load_models()

    requested_steps = max(1, int(num_steps))
    start_ts = _last_timestamp_from_history(recent_history)

    components = _resolve_forecaster_components()
    base_history = _prepare_history_window(recent_history)
    if base_history.empty:
        return pd.DataFrame()

    if components is None:
        safe_limits = calculate_dynamic_limits(base_history)
        return _ema_fallback_forecast(base_history, safe_limits, requested_steps, start_ts)

    model, sensor_columns, input_features, num_lags = components
    history_window = _prepare_history_window(recent_history, sensor_columns=sensor_columns)
    safe_limits = calculate_dynamic_limits(history_window if not history_window.empty else base_history)

    if history_window.empty or len(history_window) < (num_lags + 1):
        logger.warning(
            "Forecaster fallback to EMA: insufficient history for lags (need %s, got %s)",
            num_lags + 1,
            len(history_window),
        )
        fallback_history = history_window if not history_window.empty else base_history
        return _ema_fallback_forecast(fallback_history, safe_limits, requested_steps, start_ts)

    state_buffer = history_window.iloc[-(num_lags + 1) :].to_numpy(dtype=float).tolist()
    sensor_index = {sensor: idx for idx, sensor in enumerate(sensor_columns)}
    input_row = np.zeros((1, len(input_features)), dtype=float)
    input_frame: Optional[pd.DataFrame] = None
    if hasattr(model, "feature_names_in_") or (
        hasattr(model, "estimators_")
        and isinstance(getattr(model, "estimators_"), list)
        and len(getattr(model, "estimators_", [])) > 0
        and hasattr(getattr(model, "estimators_")[0], "feature_names_in_")
    ):
        input_frame = pd.DataFrame(np.zeros((1, len(input_features)), dtype=float), columns=input_features)

    latest_state = history_window.iloc[-1].to_dict()
    future_records: List[Dict[str, Any]] = []

    try:
        for step in range(requested_steps):
            for col_idx, feature in enumerate(input_features):
                if feature in sensor_index:
                    input_row[0, col_idx] = state_buffer[-1][sensor_index[feature]]
                    continue

                if "_lag_" in feature:
                    sensor_name, lag_text = feature.rsplit("_lag_", 1)
                    lag_value = int(lag_text) if lag_text.isdigit() else None
                    if (
                        lag_value is not None
                        and sensor_name in sensor_index
                        and len(state_buffer) >= (lag_value + 1)
                    ):
                        input_row[0, col_idx] = state_buffer[-(lag_value + 1)][sensor_index[sensor_name]]
                    else:
                        input_row[0, col_idx] = 0.0
                else:
                    input_row[0, col_idx] = 0.0

            model_input: Any = input_row
            if input_frame is not None:
                input_frame.iloc[0, :] = input_row[0, :]
                model_input = input_frame

            raw_pred = model.predict(model_input)
            pred_vector = np.asarray(raw_pred).reshape(-1)
            if pred_vector.size < len(sensor_columns):
                raise ValueError(
                    f"Forecaster returned {pred_vector.size} outputs for {len(sensor_columns)} sensors."
                )

            next_buffer_row: List[float] = []
            next_state = dict(latest_state)
            for idx, sensor in enumerate(sensor_columns):
                value = float(pred_vector[idx])
                limits = safe_limits.get(sensor)
                if isinstance(limits, dict):
                    min_val = _to_float(limits.get("min"))
                    max_val = _to_float(limits.get("max"))
                    if min_val is not None and max_val is not None:
                        value = max(min_val, min(max_val, value))
                next_buffer_row.append(value)
                next_state[sensor] = value

            state_buffer.append(next_buffer_row)
            if len(state_buffer) > (num_lags + 1):
                state_buffer.pop(0)

            next_state["timestamp"] = start_ts + timedelta(minutes=step + 1)
            future_records.append(next_state.copy())
            latest_state = next_state
    except Exception as exc:
        logger.error("Forecaster failed during recursive rollout; switching to EMA fallback: %s", exc)
        completed = pd.DataFrame(future_records)
        if completed.empty:
            return _ema_fallback_forecast(history_window, safe_limits, requested_steps, start_ts)

        remaining_steps = max(0, requested_steps - len(completed))
        if remaining_steps == 0:
            return completed

        partial_history = pd.concat(
            [history_window, completed.drop(columns=["timestamp"], errors="ignore")],
            ignore_index=True,
        )
        ema_tail = _ema_fallback_forecast(
            partial_history,
            safe_limits,
            remaining_steps,
            pd.Timestamp(completed.iloc[-1]["timestamp"]),
        )
        return pd.concat([completed, ema_tail], ignore_index=True)

    return pd.DataFrame(future_records)


def predict_future_scrap_risk(
    future_df: pd.DataFrame,
    safe_limits: Dict[str, Dict[str, float]],
    recent_history: Optional[pd.DataFrame] = None,
    future_risk_threshold: float = FUTURE_RISK_THRESHOLD,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> pd.DataFrame:
    """
    Predict future scrap probability from forecasted sensor values.
    """
    _load_models()

    if future_df is None or future_df.empty:
        return pd.DataFrame() if future_df is None else future_df

    df = future_df.copy()
    last_known_state: Dict[str, Any] = {}
    if recent_history is not None and not recent_history.empty:
        last_known_state = recent_history.ffill().fillna(0.0).iloc[-1].to_dict()

    for sensor in safe_limits.keys():
        if sensor not in df.columns:
            df[sensor] = _to_float(last_known_state.get(sensor)) or 0.0

    model = _SCRAP_RISK_MODEL
    model_features = list(_SCRAP_RISK_FEATURES) if isinstance(_SCRAP_RISK_FEATURES, list) else None
    scaler = None

    reg_artifact, _ = _resolve_task_bundle("scrap_classifier", machine_id, part_number)
    if isinstance(reg_artifact, dict) and reg_artifact.get("model") is not None:
        model = reg_artifact.get("model")
        model_features = reg_artifact.get("feature_cols") or reg_artifact.get("model_features")
        scaler = reg_artifact.get("scaler")
    elif isinstance(reg_artifact, dict) and str(reg_artifact.get("family")) == "lstm_attention_dual":
        try:
            try:
                from sequence_model import get_sequence_model_service
            except ImportError:
                from .sequence_model import get_sequence_model_service

            service = get_sequence_model_service(MODELS_DIR)
            sensor_cols = list(reg_artifact.get("sensor_cols") or list(safe_limits.keys()))
            sequence_length = int(reg_artifact.get("sequence_length", 30))
            horizon_cycles = int(reg_artifact.get("horizon_cycles", 30))

            base_history = (
                recent_history.select_dtypes(include=[np.number]).copy()
                if recent_history is not None and not recent_history.empty
                else pd.DataFrame()
            )
            for sensor in sensor_cols:
                if sensor not in base_history.columns:
                    base_history[sensor] = _to_float(last_known_state.get(sensor)) or 0.0
                if sensor not in df.columns:
                    df[sensor] = _to_float(last_known_state.get(sensor)) or 0.0

            base_history = base_history[sensor_cols].ffill().fillna(0.0)
            future_numeric = (
                df[sensor_cols]
                .apply(pd.to_numeric, errors="coerce")
                .ffill()
                .fillna(0.0)
            )
            combined = pd.concat([base_history, future_numeric], ignore_index=True)
            history_len = len(base_history)

            risk_values: List[float] = []
            for row_idx in range(len(future_numeric)):
                combined_idx = history_len + row_idx
                start_idx = max(0, combined_idx - sequence_length + 1)
                seq_df = combined.iloc[start_idx : combined_idx + 1][sensor_cols]
                seq_records = seq_df.to_dict(orient="records")
                if len(seq_records) < 10:
                    risk_values.append(0.0)
                    continue
                pred = service.predict_batch(
                    machine_id=machine_id or "unknown",
                    sequence=seq_records,
                    horizon_cycles=horizon_cycles,
                    part_number=part_number,
                    top_k=8,
                )
                risk_values.append(_to_float(pred.get("scrap_probability")) or 0.0)

            df["scrap_probability"] = np.clip(np.asarray(risk_values, dtype=float), 0.0, 1.0)
            df["predicted_scrap"] = (df["scrap_probability"] >= float(future_risk_threshold)).astype(int)
            return df
        except Exception as exc:
            logger.warning("LSTM future-risk scoring failed, fallback to legacy classifier: %s", exc)
    if model_features is None and model is not None:
        model_features = _extract_model_features(model)

    if model is not None and model_features:
        x_future = _build_model_feature_frame(df, model_features, recent_history)
        if x_future.empty:
            for feature in model_features:
                if feature not in df.columns:
                    df[feature] = _to_float(last_known_state.get(feature)) or 0.0
            x_future = df[model_features].ffill().fillna(0.0)
        if scaler is not None:
            try:
                x_future = pd.DataFrame(
                    scaler.transform(x_future),
                    columns=list(x_future.columns),
                    index=x_future.index,
                )
            except Exception as exc:
                logger.warning("Failed to apply classifier scaler from registry artifact: %s", exc)

        try:
            if hasattr(model, "predict_proba"):
                proba = np.asarray(model.predict_proba(x_future))
                if proba.ndim == 1:
                    risk_values = np.clip(proba.astype(float), 0.0, 1.0)
                elif proba.shape[1] == 1:
                    cls = list(getattr(model, "classes_", [0]))
                    fill_val = 1.0 if int(cls[0]) == 1 else 0.0
                    risk_values = np.full(len(x_future), fill_val, dtype=float)
                else:
                    classes = list(getattr(model, "classes_", [0, 1]))
                    idx = classes.index(1) if 1 in classes else (proba.shape[1] - 1)
                    risk_values = np.asarray(proba[:, idx], dtype=float)
            else:
                risk_values = np.asarray(model.predict(x_future)).reshape(-1)
        except Exception as exc:
            logger.error("Scrap-risk inference failed, falling back to zeros: %s", exc)
            risk_values = np.zeros(len(df), dtype=float)
    else:
        risk_values = np.zeros(len(df), dtype=float)

    df["scrap_probability"] = np.clip(risk_values.astype(float), 0.0, 1.0)
    df["predicted_scrap"] = (df["scrap_probability"] >= float(future_risk_threshold)).astype(int)
    return df


def _load_horizon_artifact(horizon_minutes: int) -> Dict[str, Any]:
    horizon = int(horizon_minutes)
    cached = _HORIZON_CACHE.get(horizon)
    if isinstance(cached, dict):
        return cached

    model_path = os.path.join(HORIZON_MODELS_DIR, f"scrap_{horizon}m_model.joblib")
    scaler_path = os.path.join(HORIZON_MODELS_DIR, f"scrap_{horizon}m_scaler.joblib")
    features_path = os.path.join(HORIZON_MODELS_DIR, f"scrap_{horizon}m_feature_list.joblib")
    metadata_path = os.path.join(HORIZON_MODELS_DIR, f"scrap_{horizon}m_metadata.json")

    if not (os.path.exists(model_path) and os.path.exists(scaler_path) and os.path.exists(features_path)):
        payload = {"available": False, "reason": "artifact_missing", "horizon_minutes": horizon}
        _HORIZON_CACHE[horizon] = payload
        return payload

    if joblib is None:
        payload = {"available": False, "reason": "joblib_missing", "horizon_minutes": horizon}
        _HORIZON_CACHE[horizon] = payload
        return payload

    try:
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        features = list(joblib.load(features_path))
        metadata: Dict[str, Any] = {}
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        payload = {
            "available": True,
            "horizon_minutes": horizon,
            "model": model,
            "scaler": scaler,
            "features": features,
            "metadata": metadata,
        }
        _HORIZON_CACHE[horizon] = payload
        return payload
    except Exception as exc:
        payload = {"available": False, "reason": f"load_error:{exc}", "horizon_minutes": horizon}
        _HORIZON_CACHE[horizon] = payload
        return payload


def _build_latest_horizon_feature_row(recent_history: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    history = recent_history.copy() if recent_history is not None else pd.DataFrame()
    if history.empty:
        return pd.DataFrame([{col: 0.0 for col in feature_cols}], columns=feature_cols)

    numeric = history.select_dtypes(include=[np.number]).copy()
    if numeric.empty:
        return pd.DataFrame([{col: 0.0 for col in feature_cols}], columns=feature_cols)

    numeric = numeric.sort_index()
    param_df = _load_parameter_metadata()
    setpoints: Dict[str, float] = {}
    tolerances: Dict[str, float] = {}
    for _, row in param_df.iterrows():
        name = str(row.get("variable_name", "")).strip()
        if not name:
            continue
        default_set = _to_float(row.get("default_set_value"))
        if default_set is not None:
            setpoints[name] = default_set
        tol_plus = abs(_to_float(row.get("tolerance_plus")) or 0.0)
        tol_minus = abs(_to_float(row.get("tolerance_minus")) or 0.0)
        tol = max(tol_plus, tol_minus)
        if tol > 0:
            tolerances[name] = tol

    row: Dict[str, float] = {}
    for feature in feature_cols:
        value: float = 0.0
        if feature in numeric.columns:
            value = float(pd.to_numeric(numeric[feature], errors="coerce").ffill().iloc[-1])
            row[feature] = value
            continue

        base = feature
        if feature.endswith("__pct_change"):
            base = feature[: -len("__pct_change")]
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            if len(s.dropna()) >= 2:
                prev = float(s.dropna().iloc[-2])
                curr = float(s.dropna().iloc[-1])
                value = (curr - prev) / (abs(prev) + EPS)
        elif "__mean_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__mean_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = float(s.tail(w).mean()) if base in numeric.columns else 0.0
        elif "__std_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__std_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = float(s.tail(w).std() or 0.0) if base in numeric.columns else 0.0
        elif "__min_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__min_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = float(s.tail(w).min()) if base in numeric.columns else 0.0
        elif "__max_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__max_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = float(s.tail(w).max()) if base in numeric.columns else 0.0
        elif "__last_" in feature and feature.endswith("m"):
            base, _ = feature.split("__last_", 1)
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = float(s.ffill().iloc[-1]) if base in numeric.columns else 0.0
        elif "__trend_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__trend_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            value = _trend_from_tail(s, w) if base in numeric.columns else 0.0
        elif "__spike_count_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__spike_count_", 1)
            w = int(suffix[:-1])
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            if base in numeric.columns:
                tail = s.tail(w)
                th = float(tail.mean() + 2.0 * (tail.std() or 0.0))
                value = float((tail > th).sum())
        elif "__missing_ratio_" in feature and feature.endswith("m"):
            base, suffix = feature.split("__missing_ratio_", 1)
            w = int(suffix[:-1])
            if base in history.columns:
                raw = pd.to_numeric(history[base], errors="coerce")
                value = float(raw.tail(w).isna().mean())
        elif feature.endswith("__deviation_from_setpoint"):
            base = feature[: -len("__deviation_from_setpoint")]
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            if base in numeric.columns:
                current = float(s.ffill().iloc[-1])
                setpoint = setpoints.get(base, float(pd.to_numeric(numeric[base], errors="coerce").head(1000).mean()))
                value = float(current - setpoint)
        elif feature.endswith("__deviation_pct"):
            base = feature[: -len("__deviation_pct")]
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            if base in numeric.columns:
                current = float(s.ffill().iloc[-1])
                setpoint = setpoints.get(base, float(pd.to_numeric(numeric[base], errors="coerce").head(1000).mean()))
                dev = current - setpoint
                value = float(dev / (abs(setpoint) + EPS))
        elif feature.endswith("__exceed_threshold"):
            base = feature[: -len("__exceed_threshold")]
            s = pd.to_numeric(numeric[base], errors="coerce") if base in numeric.columns else pd.Series(dtype=float)
            if base in numeric.columns:
                current = float(s.ffill().iloc[-1])
                setpoint = setpoints.get(base, float(pd.to_numeric(numeric[base], errors="coerce").head(1000).mean()))
                tol = tolerances.get(base, 0.0)
                value = float(1.0 if tol > 0 and abs(current - setpoint) > tol else 0.0)
        elif feature.endswith("__normalized_temp"):
            base = feature[: -len("__normalized_temp")]
            if base in numeric.columns:
                s = pd.to_numeric(numeric[base], errors="coerce")
                head = s.head(1000).dropna()
                mean = float(head.mean()) if not head.empty else float(s.mean() or 0.0)
                std = float(head.std()) if (not head.empty and (head.std() or 0.0) > 0) else 1.0
                value = float((float(s.ffill().iloc[-1]) - mean) / (std + EPS))
        elif feature in history.columns:
            value = float(_to_float(history[feature].iloc[-1]) or 0.0)

        row[feature] = float(0.0 if not np.isfinite(value) else value)

    return pd.DataFrame([row], columns=feature_cols).replace([np.inf, -np.inf], 0.0).fillna(0.0)


def _top_features_for_prediction(horizon: int, model: Any, x_row: np.ndarray, feature_cols: List[str], top_k: int) -> List[Dict[str, Any]]:
    if shap is None:
        return []
    try:
        if horizon not in _HORIZON_EXPLAINERS:
            _HORIZON_EXPLAINERS[horizon] = shap.TreeExplainer(model)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"X does not have valid feature names, but LGBMClassifier was fitted with feature names",
                category=UserWarning,
            )
            warnings.filterwarnings(
                "ignore",
                message=r"LightGBM binary classifier with TreeExplainer shap values output has changed to a list of ndarray",
                category=UserWarning,
            )
            shap_values = _HORIZON_EXPLAINERS[horizon].shap_values(x_row)
        values = np.asarray(shap_values[-1])[0] if isinstance(shap_values, list) else np.asarray(shap_values)[0]
        ranked = sorted(zip(feature_cols, values), key=lambda pair: abs(pair[1]), reverse=True)[: max(1, int(top_k))]
        return [{"feature": name, "contribution": float(val)} for name, val in ranked]
    except Exception:
        return []


def predict_multi_horizon_scrap_risk(
    recent_history: pd.DataFrame,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
    horizons: Tuple[int, ...] = DEFAULT_HORIZON_MINUTES,
    top_k: int = 3,
) -> Dict[str, Any]:
    _load_models()
    predictions: Dict[str, Any] = {}
    model_meta: Dict[str, Any] = {}
    feature_top3: Dict[str, Any] = {}

    for horizon in horizons:
        key = f"{int(horizon)}m"
        artifact = _load_horizon_artifact(int(horizon))
        if not artifact.get("available"):
            predictions[key] = {
                "horizon_minutes": int(horizon),
                "available": False,
                "probability": None,
                "risk_bucket": "UNAVAILABLE",
            }
            model_meta[key] = {"available": False, "reason": artifact.get("reason")}
            feature_top3[key] = []
            continue

        model = artifact["model"]
        scaler = artifact["scaler"]
        feature_cols = list(artifact["features"])
        metadata = artifact.get("metadata", {})

        x_df = _build_latest_horizon_feature_row(recent_history, feature_cols)
        try:
            x_scaled = scaler.transform(x_df) if scaler is not None else x_df.to_numpy(dtype=float)
        except Exception:
            x_scaled = x_df.to_numpy(dtype=float)

        x_model = _with_feature_names(model, x_scaled, feature_cols=feature_cols)
        try:
            probability = _predict_positive_probability(model, x_model, feature_cols=feature_cols)
        except Exception:
            probability = 0.0

        probability = float(np.clip(probability, 0.0, 1.0))
        top_features = _top_features_for_prediction(int(horizon), model, x_model, feature_cols, top_k=top_k)

        predictions[key] = {
            "horizon_minutes": int(horizon),
            "available": True,
            "probability": round(probability, 6),
            "risk_bucket": _risk_bucket(probability),
        }
        model_meta[key] = {
            "available": True,
            "horizon_minutes": int(horizon),
            "feature_spec_hash": metadata.get("feature_spec_hash"),
            "trained_at": metadata.get("trained_at"),
            "rows_train": metadata.get("rows_train"),
            "rows_val": metadata.get("rows_val"),
            "rows_test": metadata.get("rows_test"),
        }
        feature_top3[key] = top_features

    return {
        "machine_id": machine_id,
        "part_number": part_number,
        "predictions": predictions,
        "model_meta": model_meta,
        "feature_top3": feature_top3,
    }


def analyze_root_causes(
    current_state: Dict[str, float],
    safe_limits: Dict[str, Dict[str, float]],
    base_risk: float = 0.0,
) -> Dict[str, Any]:
    """
    Rank exceeded and near-limit sensors; apply risk penalty from breach count.
    """
    exceeded: List[Dict[str, Any]] = []
    nearby: List[Dict[str, Any]] = []

    for sensor, limits in safe_limits.items():
        value = _to_float(current_state.get(sensor))
        min_val = _to_float((limits or {}).get("min"))
        max_val = _to_float((limits or {}).get("max"))
        if value is None or min_val is None or max_val is None:
            continue

        raw_span = max_val - min_val
        # Degenerate envelopes (min == max) are common for flatlined sensors.
        # Do not classify those as "near_limit" unless they are truly breached.
        if raw_span <= 0:
            scale = max(abs(max_val), abs(min_val), 1.0)
            if value > max_val:
                exceeded.append(
                    {
                        "sensor": sensor,
                        "status": "above_max",
                        "severity": float((value - max_val) / scale),
                        "value": float(value),
                        "min": float(min_val),
                        "max": float(max_val),
                    }
                )
            elif value < min_val:
                exceeded.append(
                    {
                        "sensor": sensor,
                        "status": "below_min",
                        "severity": float((min_val - value) / scale),
                        "value": float(value),
                        "min": float(min_val),
                        "max": float(max_val),
                    }
                )
            continue

        span = raw_span
        if value > max_val:
            severity = (value - max_val) / span
            exceeded.append(
                {
                    "sensor": sensor,
                    "status": "above_max",
                    "severity": float(severity),
                    "value": float(value),
                    "min": float(min_val),
                    "max": float(max_val),
                }
            )
        elif value < min_val:
            severity = (min_val - value) / span
            exceeded.append(
                {
                    "sensor": sensor,
                    "status": "below_min",
                    "severity": float(severity),
                    "value": float(value),
                    "min": float(min_val),
                    "max": float(max_val),
                }
            )
        else:
            edge_distance = min((max_val - value), (value - min_val))
            proximity = edge_distance / span
            if proximity <= 0.10:
                nearby.append(
                    {
                        "sensor": sensor,
                        "status": "near_limit",
                        "proximity": float(proximity),
                        "value": float(value),
                        "min": float(min_val),
                        "max": float(max_val),
                    }
                )

    exceeded.sort(key=lambda item: item["severity"], reverse=True)
    nearby.sort(key=lambda item: item["proximity"])

    top_root_causes = (exceeded + nearby)[:3]
    breach_count = len(exceeded)
    risk_penalty = min(0.35, 0.12 * breach_count)
    adjusted_risk = min(1.0, max(0.0, float(base_risk)) + risk_penalty)

    # Calculate SHAP-like attributions for the current state analysis
    attributions = []
    for sensor, limits in safe_limits.items():
        value = _to_float(current_state.get(sensor))
        min_val = _to_float((limits or {}).get("min"))
        max_val = _to_float((limits or {}).get("max"))
        if value is None or min_val is None or max_val is None:
            continue

        span = max_val - min_val
        if span <= 0: span = 1.0
        setpoint = (min_val + max_val) / 2.0
        
        # We use a 2.0 multiplier to align with the frontend's visual scale (deviation / half-span)
        contribution = (value - setpoint) / (span if span > 0 else 1.0) * 2.5
        
        attributions.append({
            "feature": RAW_TO_FRONTEND_SENSOR_MAP.get(sensor, str(sensor).lower()),
            "contribution": float(round(contribution, 3)),
            "direction": "positive" if value > setpoint else "negative"
        })
    
    attributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)

    return {
        "root_causes": top_root_causes,
        "breach_count": breach_count,
        "risk_penalty": float(round(risk_penalty, 4)),
        "adjusted_risk": float(round(adjusted_risk, 4)),
        "attributions": attributions[:8]
    }


def convert_safe_limits_to_frontend(safe_limits: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    converted: Dict[str, Dict[str, float]] = {}
    for raw_sensor, limits in safe_limits.items():
        frontend_sensor = RAW_TO_FRONTEND_SENSOR_MAP.get(raw_sensor, str(raw_sensor).lower())
        converted[frontend_sensor] = {
            "min": float(limits.get("min", 0.0)),
            "max": float(limits.get("max", 0.0)),
        }
    return converted


def build_future_timeline(
    forecast_df: pd.DataFrame,
    safe_limits: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    timeline: List[Dict[str, Any]] = []
    if forecast_df is None or forecast_df.empty:
        return timeline

    for row_index, row in forecast_df.iterrows():
        timestamp = row.get("timestamp")
        if timestamp is None and isinstance(row_index, pd.Timestamp):
            timestamp = row_index
        if isinstance(timestamp, pd.Timestamp):
            timestamp_str = timestamp.isoformat()
        else:
            timestamp_str = str(timestamp) if timestamp is not None else ""

        telemetry: Dict[str, Dict[str, Optional[float]]] = {}
        for column, value in row.items():
            if column in {"timestamp", "scrap_probability", "predicted_scrap"}:
                continue
            numeric_value = _to_float(value)
            if numeric_value is None:
                continue

            frontend_sensor = RAW_TO_FRONTEND_SENSOR_MAP.get(column, str(column).lower())
            limits = safe_limits.get(column)
            safe_min = _to_float((limits or {}).get("min"))
            safe_max = _to_float((limits or {}).get("max"))
            setpoint = None
            if safe_min is not None and safe_max is not None:
                setpoint = (safe_min + safe_max) / 2.0

            telemetry[frontend_sensor] = {
                "value": float(round(numeric_value, 4)),
                "safe_min": float(round(safe_min, 4)) if safe_min is not None else None,
                "safe_max": float(round(safe_max, 4)) if safe_max is not None else None,
                "setpoint": float(round(setpoint, 4)) if setpoint is not None else None,
            }

        scrap_probability = _to_float(row.get("scrap_probability")) or 0.0
        predicted_scrap = int(row.get("predicted_scrap", 0))
        timeline.append(
            {
                "timestamp": timestamp_str,
                "telemetry": telemetry,
                "scrap_probability": float(np.clip(scrap_probability, 0.0, 1.0)),
                "predicted_scrap": predicted_scrap,
            }
        )

    return timeline
