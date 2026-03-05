import logging
import os
import re
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned.csv")
CSV_V2_PATH = os.path.join(os.path.dirname(__file__), "AI_cup_parameter_info_cleaned_v2.csv")
PHYSICS_RULES_GLOBAL: Dict[str, Dict[str, float]] = {}
PHYSICS_RULES_BY_PART: Dict[str, Dict[str, Dict[str, float]]] = {}
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


def load_physics_rules(force_reload: bool = False) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load official per-sensor tolerances from the official CSV repository."""
    global _PHYSICS_RULES_LOADED
    if _PHYSICS_RULES_LOADED and not force_reload:
        return {"global": PHYSICS_RULES_GLOBAL, "by_part": PHYSICS_RULES_BY_PART}

    PHYSICS_RULES_GLOBAL.clear()
    PHYSICS_RULES_BY_PART.clear()
    source_path = CSV_V2_PATH if os.path.exists(CSV_V2_PATH) else CSV_PATH
    if not os.path.exists(source_path):
        logger.warning("Physics tolerance CSV not found: %s", source_path)
        _PHYSICS_RULES_LOADED = True
        return {"global": PHYSICS_RULES_GLOBAL, "by_part": PHYSICS_RULES_BY_PART}

    try:
        df = pd.read_csv(source_path)
        # Rename columns to standard internal names if they vary
        col_map = {str(c).strip().lower(): c for c in df.columns}
        var_col = col_map.get("variable_name", "variable_name")
        plus_col = col_map.get("tolerance_plus", "tolerance_plus")
        minus_col = col_map.get("tolerance_minus", "tolerance_minus")
        set_col = col_map.get("default_set_value", "default_set_value")
        part_col = col_map.get("part_number", "part_number")

        for _, row in df.iterrows():
            name = str(row.get(var_col, "")).strip()
            if not name:
                continue
            rule = {
                "plus": _to_float(row.get(plus_col)),
                "minus": _to_float(row.get(minus_col)),
                "setpoint": _to_float(row.get(set_col)),
            }
            part_value = _normalize_part_number(row.get(part_col))
            if part_value:
                PHYSICS_RULES_BY_PART.setdefault(part_value, {})[name] = rule
            else:
                PHYSICS_RULES_GLOBAL[name] = rule
    except Exception as exc:
        logger.error("Failed to read tolerance CSV %s: %s", source_path, exc)

    _PHYSICS_RULES_LOADED = True
    return {"global": PHYSICS_RULES_GLOBAL, "by_part": PHYSICS_RULES_BY_PART}


def _requires_non_negative_min(sensor_name: str) -> bool:
    sensor_lower = sensor_name.lower()
    return not any(token in sensor_lower for token in ("deviation", "offset", "tmp"))


def _resolve_sensor_rule(sensor_name: str, part_number: Optional[str]) -> tuple[Dict[str, Any], str]:
    normalized_part = _normalize_part_number(part_number)
    if normalized_part:
        part_rules = PHYSICS_RULES_BY_PART.get(normalized_part) or {}
        rule = part_rules.get(sensor_name)
        if isinstance(rule, dict):
            return rule, "part_csv"

    rule = PHYSICS_RULES_GLOBAL.get(sensor_name)
    if isinstance(rule, dict):
        return rule, "global_csv"

    return {}, "dynamic"


def _load_user_parameter_overrides(
    session: Any,  # SQLAlchemy Session
    sensor_name: str,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Load user-configured parameter overrides from the database.

    Checks parameter_configs table first for:
    1. Machine-specific + part-specific override
    2. Machine-specific + global override
    3. Global override

    Returns None if no override found (falls back to CSV).
    """
    if not session:
        return None

    try:
        from . import models
    except ImportError:
        import models

    normalized_part = _normalize_part_number(part_number)
    sensor_key = str(sensor_name).strip()
    if not sensor_key:
        return None

    def _to_payload(override: Any, scope: str) -> Dict[str, Any]:
        plus = _to_float(getattr(override, "tolerance_plus", None))
        minus = _to_float(getattr(override, "tolerance_minus", None))
        setpoint = _to_float(getattr(override, "default_set_value", None))
        return {
            "plus": plus,
            "minus": minus,
            "setpoint": setpoint,
            "tolerance_plus": plus,
            "tolerance_minus": minus,
            "default_set_value": setpoint,
            "source": "user_override",
            "status_source": "db_override",
            "scope": scope,
        }

    # 1) Machine + part override (most specific)
    if machine_id and normalized_part:
        override = (
            session.query(models.ParameterConfig)
            .filter(
                models.ParameterConfig.parameter_name.ilike(sensor_key),
                models.ParameterConfig.is_active == 1,
                models.ParameterConfig.machine_id == machine_id,
                models.ParameterConfig.part_number.isnot(None),
                models.ParameterConfig.part_number.ilike(normalized_part),
            )
            .order_by(models.ParameterConfig.updated_at.desc(), models.ParameterConfig.id.desc())
            .first()
        )
        if override:
            return _to_payload(override, "machine+part")

    # 2) Machine-level override (all parts)
    if machine_id:
        override = (
            session.query(models.ParameterConfig)
            .filter(
                models.ParameterConfig.parameter_name.ilike(sensor_key),
                models.ParameterConfig.is_active == 1,
                models.ParameterConfig.machine_id == machine_id,
                models.ParameterConfig.part_number.is_(None),
            )
            .order_by(models.ParameterConfig.updated_at.desc(), models.ParameterConfig.id.desc())
            .first()
        )
        if override:
            return _to_payload(override, "machine")

    # 3) Global override
    override = (
        session.query(models.ParameterConfig)
        .filter(
            models.ParameterConfig.parameter_name.ilike(sensor_key),
            models.ParameterConfig.is_active == 1,
            models.ParameterConfig.machine_id.is_(None),
            models.ParameterConfig.part_number.is_(None),
        )
        .order_by(models.ParameterConfig.updated_at.desc(), models.ParameterConfig.id.desc())
        .first()
    )
    if override:
        return _to_payload(override, "global")

    return None


def calculate_dynamic_limits(
    recent_history: pd.DataFrame,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
    db: Any = None,
) -> Dict[str, Dict[str, Any]]:
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
        sensor_name = str(sensor)
        override_rule = _load_user_parameter_overrides(
            db,
            sensor_name=sensor_name,
            machine_id=machine_id,
            part_number=part_number,
        )
        if override_rule:
            rule = override_rule
            status_source = str(override_rule.get("status_source") or "db_override")
        else:
            rule, status_source = _resolve_sensor_rule(sensor_name, part_number)

        tol_plus = _to_float(rule.get("plus"))
        tol_minus = _to_float(rule.get("minus"))
        official_setpoint = _to_float(rule.get("setpoint"))

        # Bucket A (Hard CSV Tolerances)
        if tol_plus is not None and tol_minus is not None:
            base_setpoint = official_setpoint if official_setpoint is not None else median_val
            min_limit = base_setpoint - abs(tol_minus)
            max_limit = base_setpoint + abs(tol_plus)
            source = str(rule.get("source") or "csv_tolerance")
        else:
            # Bucket C (Statistical / 'N/A' Fallback)
            std_val = float(local_std.get(sensor, 0.0)) if not pd.isna(local_std.get(sensor)) else 0.0
            # Ensure a minimum 2% physical buffer if std is 0
            safe_margin = max(std_val * 3.0, abs(median_val) * 0.02)
            min_limit = median_val - safe_margin
            max_limit = median_val + safe_margin
            source = "dynamic_history"
            status_source = "dynamic"

        # Step 3: Sanity Clamps
        if _requires_non_negative_min(str(sensor)):
            min_limit = max(0.0, min_limit)

        limits[sensor_name] = {
            "min": float(min_limit),
            "max": float(max_limit),
            "median": float(median_val),
            "official_setpoint": official_setpoint,
            "source": source,
            "status_source": status_source,
        }

    return limits


def calculate_safe_limits(
    machine_id: Optional[str],
    part_number: Optional[str],
    history_df: pd.DataFrame,
    db: Any = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compatibility wrapper:
    calculate machine + part aware safe limits using DB overrides when available.
    """
    return calculate_dynamic_limits(
        recent_history=history_df,
        machine_id=machine_id,
        part_number=part_number,
        db=db,
    )


load_physics_rules()
