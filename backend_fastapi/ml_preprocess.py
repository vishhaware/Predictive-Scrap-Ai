from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler


def clean_dataset(df: pd.DataFrame, numeric_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out = out.drop_duplicates(subset=["machine_id", "timestamp"], keep="last")
    for col in numeric_cols:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    # lightweight robust clipping by IQR per machine
    for col in numeric_cols:
        q1 = out[col].quantile(0.25)
        q3 = out[col].quantile(0.75)
        if pd.isna(q1) or pd.isna(q3):
            continue
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lo = q1 - 4.0 * iqr
        hi = q3 + 4.0 * iqr
        out[col] = out[col].clip(lower=lo, upper=hi)
    return out


def fill_missing(df: pd.DataFrame, numeric_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out[numeric_cols] = out.groupby("machine_id")[numeric_cols].ffill()
    out[numeric_cols] = out.groupby("machine_id")[numeric_cols].transform(lambda s: s.fillna(s.median()))
    out[numeric_cols] = out[numeric_cols].fillna(0.0)
    return out


def chronological_split(
    df: pd.DataFrame,
    group_cols: List[str],
    train_ratio: float = 0.8,
) -> Tuple[pd.Series, pd.Series]:
    ratio = min(0.95, max(0.5, float(train_ratio)))
    work = df.copy()
    work["_order"] = work.groupby(group_cols).cumcount()
    work["_max_order"] = work.groupby(group_cols)["_order"].transform("max").clip(lower=1)
    train_mask = work["_order"] <= (work["_max_order"] * ratio)
    valid_mask = ~train_mask
    return train_mask, valid_mask


def fit_scaler(df: pd.DataFrame, feature_cols: List[str], train_mask: pd.Series) -> Optional[StandardScaler]:
    if not feature_cols:
        return None
    scaler = StandardScaler()
    train_x = df.loc[train_mask, feature_cols]
    if train_x.empty:
        return None
    scaler.fit(train_x)
    return scaler


def apply_scaler(df: pd.DataFrame, feature_cols: List[str], scaler: Optional[StandardScaler]) -> pd.DataFrame:
    out = df.copy()
    if scaler is None or not feature_cols:
        return out
    out[feature_cols] = scaler.transform(out[feature_cols])
    return out


def segment_hierarchy(machine_id: Optional[str], part_number: Optional[str]) -> List[str]:
    machine = (machine_id or "").strip()
    part = (part_number or "").strip()
    keys: List[str] = []
    if machine and part:
        keys.append(f"machine_part:{machine}|{part}")
    if machine:
        keys.append(f"machine:{machine}")
    keys.append("global")
    return keys

