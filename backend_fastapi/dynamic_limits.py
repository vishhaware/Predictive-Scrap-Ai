import logging
import os
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned.csv")
CSV_V2_PATH = os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned_v2.csv")
PHYSICS_RULES: Dict[str, Dict[str, float]] = {}
_PHYSICS_RULES_LOADED = False


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "na", "n/a", "nan", "none"}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(parsed):
        return None
    return parsed


def load_physics_rules(force_reload: bool = False) -> Dict[str, Dict[str, float]]:
    """Load official per-sensor tolerances from the official CSV repository."""
    global _PHYSICS_RULES_LOADED
    if _PHYSICS_RULES_LOADED and not force_reload:
        return PHYSICS_RULES

    PHYSICS_RULES.clear()
    source_path = CSV_V2_PATH if os.path.exists(CSV_V2_PATH) else CSV_PATH
    if not os.path.exists(source_path):
        logger.warning("Physics tolerance CSV not found: %s", source_path)
        _PHYSICS_RULES_LOADED = True
        return PHYSICS_RULES

    try:
        df = pd.read_csv(source_path)
        # Rename columns to standard internal names if they vary
        col_map = {str(c).strip().lower(): c for c in df.columns}
        var_col = col_map.get("variable_name", "variable_name")
        plus_col = col_map.get("tolerance_plus", "tolerance_plus")
        minus_col = col_map.get("tolerance_minus", "tolerance_minus")
        set_col = col_map.get("default_set_value", "default_set_value")

        for _, row in df.iterrows():
            name = str(row.get(var_col, "")).strip()
            if not name:
                continue
            PHYSICS_RULES[name] = {
                "plus": _to_float(row.get(plus_col)),
                "minus": _to_float(row.get(minus_col)),
                "setpoint": _to_float(row.get(set_col)),
            }
    except Exception as exc:
        logger.error("Failed to read tolerance CSV %s: %s", source_path, exc)

    _PHYSICS_RULES_LOADED = True
    return PHYSICS_RULES


def _requires_non_negative_min(sensor_name: str) -> bool:
    sensor_lower = sensor_name.lower()
    return not any(token in sensor_lower for token in ("deviation", "offset", "tmp"))


def calculate_dynamic_limits(recent_history: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Acts as a universal, 2-bucket engine based strictly on CSV tolerances (Part 3 Calibration).
    Recursive sensor forecasting and scrap risk rely on these newly calibrated bounds.
    """
    load_physics_rules()

    if recent_history is None or recent_history.empty:
        return {}

    # Step 1: Local Context calculation from recent past window
    numeric_history = recent_history.select_dtypes(include=[np.number]).copy()
    if numeric_history.empty:
        return {}

    local_median = numeric_history.median(numeric_only=True)
    local_std = numeric_history.std(numeric_only=True)

    limits: Dict[str, Dict[str, Any]] = {}

    # Step 2: Loop through every sensor and apply Bucket logic
    for sensor, median_val in local_median.items():
        median_val = float(median_val) if not pd.isna(median_val) else 0.0
        rule = PHYSICS_RULES.get(str(sensor), {})

        tol_plus = rule.get("plus")
        tol_minus = rule.get("minus")

        # Bucket A (Hard CSV Tolerances)
        if tol_plus is not None and tol_minus is not None:
            min_limit = median_val - abs(tol_minus)
            max_limit = median_val + abs(tol_plus)
            source = "bucket_a_csv"
        else:
            # Bucket C (Statistical / 'N/A' Fallback)
            std_val = float(local_std.get(sensor, 0.0)) if not pd.isna(local_std.get(sensor)) else 0.0
            # Ensure a minimum 2% physical buffer if std is 0
            safe_margin = max(std_val * 3.0, abs(median_val) * 0.02)
            min_limit = median_val - safe_margin
            max_limit = median_val + safe_margin
            source = "bucket_c_statistical"

        # Step 3: Sanity Clamps
        if _requires_non_negative_min(str(sensor)):
            min_limit = max(0.0, min_limit)

        limits[str(sensor)] = {
            "min": float(min_limit),
            "max": float(max_limit),
            "median": float(median_val),
            "official_setpoint": rule.get("setpoint"),
            "source": source
        }

    return limits


load_physics_rules()
