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
    """Load official per-sensor tolerances from AI_cup_parameter_info_cleaned.csv."""
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
    except Exception as exc:
        logger.error("Failed to read tolerance CSV %s: %s", source_path, exc)
        _PHYSICS_RULES_LOADED = True
        return PHYSICS_RULES

    for _, row in df.iterrows():
        variable_name = row.get("variable_name")
        if not isinstance(variable_name, str) or not variable_name.strip():
            continue

        PHYSICS_RULES[variable_name.strip()] = {
            "tolerance_plus": _to_float(row.get("tolerance_plus")),
            "tolerance_minus": _to_float(row.get("tolerance_minus")),
        }

    _PHYSICS_RULES_LOADED = True
    return PHYSICS_RULES


def _requires_non_negative_min(sensor_name: str) -> bool:
    sensor_lower = sensor_name.lower()
    return not any(token in sensor_lower for token in ("deviation", "offset", "tmp"))


def calculate_dynamic_limits(recent_history: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    Compute per-sensor dynamic operating limits using exactly two buckets:
    - Bucket A: official CSV tolerances (tolerance_plus/tolerance_minus)
    - Bucket C: local statistical fallback (3 sigma with a 2% floor)
    """
    load_physics_rules()

    if recent_history is None or recent_history.empty:
        return {}

    numeric_history = recent_history.select_dtypes(include=[np.number]).copy()
    if numeric_history.empty:
        return {}

    local_median = numeric_history.median(numeric_only=True)
    local_std = numeric_history.std(numeric_only=True)

    limits: Dict[str, Dict[str, float]] = {}
    for sensor, median_value in local_median.items():
        if pd.isna(median_value):
            continue

        rule = PHYSICS_RULES.get(sensor, {})
        tol_plus = _to_float(rule.get("tolerance_plus"))
        tol_minus = _to_float(rule.get("tolerance_minus"))

        if tol_plus is not None and tol_minus is not None:
            # Bucket A: hard tolerances from official CSV.
            min_limit = float(median_value - abs(tol_minus))
            max_limit = float(median_value + abs(tol_plus))
            source = "csv_tolerance"
        else:
            # Bucket C: statistical fallback for missing/invalid tolerances.
            sigma = _to_float(local_std.get(sensor)) or 0.0
            safe_margin = max((sigma * 3.0), (abs(float(median_value)) * 0.02))
            min_limit = float(median_value - safe_margin)
            max_limit = float(median_value + safe_margin)
            source = "statistical_fallback"

        if max_limit < min_limit:
            min_limit, max_limit = max_limit, min_limit

        if _requires_non_negative_min(str(sensor)):
            min_limit = max(0.0, min_limit)

        limits[str(sensor)] = {
            "min": float(min_limit),
            "max": float(max_limit),
            "source": source,
        }

    return limits


load_physics_rules()
