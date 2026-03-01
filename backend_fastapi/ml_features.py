import hashlib
import json
import math
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


DEFAULT_ROLL_WINDOWS = [3, 5, 10, 20]


def build_feature_spec(
    sensors: List[str],
    num_lags: int = 3,
    rolling_windows: List[int] = None,
) -> Dict[str, Any]:
    windows = rolling_windows or list(DEFAULT_ROLL_WINDOWS)
    return {
        "sensors": list(sensors),
        "num_lags": int(num_lags),
        "rolling_windows": [int(w) for w in windows],
        "datetime_features": ["hour", "dayofweek", "month", "hour_sin", "hour_cos", "dow_sin", "dow_cos"],
    }


def feature_spec_hash(spec: Dict[str, Any]) -> str:
    payload = json.dumps(spec, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def add_datetime_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out["timestamp"], errors="coerce")
    out["hour"] = ts.dt.hour.fillna(0).astype(int)
    out["dayofweek"] = ts.dt.dayofweek.fillna(0).astype(int)
    out["month"] = ts.dt.month.fillna(1).astype(int)
    out["hour_sin"] = out["hour"].map(lambda h: math.sin(2 * math.pi * (h / 24.0)))
    out["hour_cos"] = out["hour"].map(lambda h: math.cos(2 * math.pi * (h / 24.0)))
    out["dow_sin"] = out["dayofweek"].map(lambda d: math.sin(2 * math.pi * (d / 7.0)))
    out["dow_cos"] = out["dayofweek"].map(lambda d: math.cos(2 * math.pi * (d / 7.0)))
    return out


def add_lag_features(df: pd.DataFrame, sensors: List[str], num_lags: int) -> Tuple[pd.DataFrame, List[str]]:
    out = df.copy()
    feature_cols = list(sensors)
    for lag in range(1, int(num_lags) + 1):
        for sensor in sensors:
            col = f"{sensor}_lag_{lag}"
            out[col] = out.groupby("segment_id")[sensor].shift(lag)
            feature_cols.append(col)
    return out, feature_cols


def add_rolling_features(df: pd.DataFrame, sensors: List[str], windows: List[int]) -> Tuple[pd.DataFrame, List[str]]:
    out = df.copy()
    added: List[str] = []
    for w in windows:
        window = max(2, int(w))
        grouped = out.groupby("segment_id")
        for sensor in sensors:
            m_col = f"{sensor}_roll_mean_{window}"
            s_col = f"{sensor}_roll_std_{window}"
            out[m_col] = grouped[sensor].transform(lambda x: x.rolling(window=window, min_periods=1).mean())
            out[s_col] = grouped[sensor].transform(lambda x: x.rolling(window=window, min_periods=2).std())
            added.extend([m_col, s_col])
    return out, added


def add_drift_features(df: pd.DataFrame, sensors: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    out = df.copy()
    added: List[str] = []
    for sensor in sensors:
        v_col = f"{sensor}_vel"
        a_col = f"{sensor}_acc"
        out[v_col] = out.groupby("segment_id")[sensor].diff().fillna(0.0)
        out[a_col] = out.groupby("segment_id")[v_col].diff().fillna(0.0)
        added.extend([v_col, a_col])
    return out, added


def build_features(
    df: pd.DataFrame,
    sensors: List[str],
    num_lags: int = 3,
    rolling_windows: List[int] = None,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any], str]:
    spec = build_feature_spec(sensors=sensors, num_lags=num_lags, rolling_windows=rolling_windows or list(DEFAULT_ROLL_WINDOWS))
    out = add_datetime_features(df)
    out, lag_cols = add_lag_features(out, sensors=sensors, num_lags=num_lags)
    out, roll_cols = add_rolling_features(out, sensors=sensors, windows=spec["rolling_windows"])
    out, drift_cols = add_drift_features(out, sensors=sensors)

    dt_cols = spec["datetime_features"]
    feature_cols = list(dict.fromkeys(sensors + lag_cols[len(sensors):] + roll_cols + drift_cols + dt_cols))
    out[feature_cols] = out[feature_cols].replace([np.inf, -np.inf], np.nan)
    out[feature_cols] = out.groupby("segment_id")[feature_cols].ffill().fillna(0.0)
    spec_hash = feature_spec_hash(spec)
    return out, feature_cols, spec, spec_hash

