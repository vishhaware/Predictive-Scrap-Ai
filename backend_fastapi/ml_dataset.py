import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session, joinedload

try:
    from . import models
    from .data_access import telemetry_to_sensor_row
except ImportError:
    import models
    from data_access import telemetry_to_sensor_row


BASE_DIR = os.path.dirname(__file__)
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "..", "frontend", "Data")
MES_WORKBOOK_PATH = os.getenv(
    "MES_WORKBOOK_PATH",
    os.path.join(DEFAULT_DATA_DIR, "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"),
)


def _machine_numeric_code(machine_id: Any) -> Optional[str]:
    if machine_id is None:
        return None
    text = str(machine_id).strip().upper()
    if not text:
        return None
    m = re.search(r"(\d{3,5})", text)
    return m.group(1) if m else None


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


def _parse_time_seconds(raw_value: Any) -> Optional[int]:
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
            try:
                parts = [int(x) for x in text.split(":")]
            except ValueError:
                parts = []
            if len(parts) == 3:
                h, m, s = parts
                return h * 3600 + m * 60 + s
    try:
        n = int(float(raw_value))
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    if n <= 172800:
        return n
    text = str(n).zfill(6)[-6:]
    try:
        h, m, s = int(text[0:2]), int(text[2:4]), int(text[4:6])
        return h * 3600 + m * 60 + s
    except ValueError:
        return None


def _parse_mes_datetime(date_value: Any, time_value: Any) -> Optional[datetime]:
    if date_value is None:
        return None
    try:
        d = pd.Timestamp(date_value)
    except Exception:
        return None
    if pd.isna(d):
        return None
    base = d.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    sec = _parse_time_seconds(time_value)
    if sec is None:
        return base
    return base + timedelta(seconds=int(sec))


def load_part_timeline() -> Dict[str, pd.DataFrame]:
    if not os.path.exists(MES_WORKBOOK_PATH):
        return {}
    try:
        df_raw = pd.read_excel(MES_WORKBOOK_PATH, sheet_name="Data")
    except Exception:
        return {}
    if df_raw.empty:
        return {}
    col_map = {str(c).strip().lower(): c for c in df_raw.columns}
    machine_col = col_map.get("machine_id")
    part_col = col_map.get("part_number")
    if not machine_col or not part_col:
        return {}

    end_date_col = col_map.get("machine_event_end_date")
    end_time_col = col_map.get("machine_event_end_time")
    create_date_col = col_map.get("machine_event_create_date")
    create_time_col = col_map.get("machine_event_create_time")

    df = df_raw.copy()
    df["part_number"] = df[part_col].map(_normalize_part_number)
    df = df.dropna(subset=["part_number"])
    if df.empty:
        return {}

    machine_codes = df[machine_col].map(_machine_numeric_code)
    event_ts: List[Optional[datetime]] = []
    for _, row in df.iterrows():
        ts = None
        if end_date_col:
            ts = _parse_mes_datetime(row.get(end_date_col), row.get(end_time_col) if end_time_col else None)
        if ts is None and create_date_col:
            ts = _parse_mes_datetime(row.get(create_date_col), row.get(create_time_col) if create_time_col else None)
        event_ts.append(ts)
    df["machine_code"] = machine_codes
    df["event_ts"] = event_ts
    df = df.dropna(subset=["machine_code", "event_ts"])
    if df.empty:
        return {}
    df["event_ts"] = pd.to_datetime(df["event_ts"]).dt.tz_localize(None)
    df = df.sort_values(["machine_code", "event_ts"])

    out: Dict[str, pd.DataFrame] = {}
    for code, g in df.groupby("machine_code"):
        timeline = g[["event_ts", "part_number"]].drop_duplicates("event_ts", keep="last").reset_index(drop=True)
        out[str(code)] = timeline
    return out


def build_training_dataset(
    db: Session,
    machine_ids: Optional[List[str]] = None,
    lookback_cycles: int = 5000,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    query = db.query(models.Cycle).options(joinedload(models.Cycle.prediction)).order_by(models.Cycle.timestamp.asc(), models.Cycle.id.asc())
    if machine_ids:
        query = query.filter(models.Cycle.machine_id.in_(machine_ids))
    cycles = query.limit(max(100, int(lookback_cycles) * max(1, len(machine_ids or [1])))).all()
    rows: List[Dict[str, Any]] = []
    for cycle in cycles:
        telemetry = cycle.data or {}
        sensor_row = telemetry_to_sensor_row(telemetry)
        if not sensor_row:
            continue
        scrap_counter = None
        sc = telemetry.get("scrap_counter")
        if isinstance(sc, dict):
            try:
                scrap_counter = float(sc.get("value"))
            except (TypeError, ValueError):
                scrap_counter = None
        rows.append(
            {
                "machine_id": str(cycle.machine_id),
                "timestamp": pd.Timestamp(cycle.timestamp).to_pydatetime().replace(tzinfo=None),
                "cycle_row_id": int(cycle.id),
                "cycle_id": str(cycle.cycle_id),
                "scrap_counter": scrap_counter,
                "scrap_probability_label": float(cycle.prediction.scrap_probability) if cycle.prediction and cycle.prediction.scrap_probability is not None else None,
                **sensor_row,
            }
        )

    if not rows:
        return pd.DataFrame(), {"rows": 0, "rows_mapped_part": 0, "fingerprint": None}

    df = pd.DataFrame(rows).sort_values(["machine_id", "timestamp", "cycle_row_id"]).reset_index(drop=True)
    df = df.drop_duplicates(subset=["machine_id", "timestamp"], keep="last")

    # derive scrap event from counter delta
    df["scrap_event"] = (
        df.groupby("machine_id")["scrap_counter"].diff().fillna(0.0) > 0.0
    ).astype(int)

    timeline_by_code = load_part_timeline()
    mapped_parts: List[Optional[str]] = [None] * len(df)
    for machine_id, group_idx in df.groupby("machine_id").groups.items():
        code = _machine_numeric_code(machine_id)
        timeline = timeline_by_code.get(str(code)) if code else None
        if timeline is None or timeline.empty:
            continue
        temp = df.loc[list(group_idx), ["timestamp"]].copy()
        temp["orig_idx"] = temp.index
        temp = temp.sort_values("timestamp")
        merged = pd.merge_asof(
            temp,
            timeline.sort_values("event_ts"),
            left_on="timestamp",
            right_on="event_ts",
            direction="backward",
        )
        for _, r in merged.iterrows():
            idx = int(r["orig_idx"])
            mapped_parts[idx] = r.get("part_number")

    df["part_number"] = mapped_parts
    df["part_number"] = df["part_number"].map(_normalize_part_number)
    df["part_number"] = df["part_number"].fillna("UNKNOWN")
    df["segment_id"] = df["machine_id"] + "|" + df["part_number"]

    cols_for_fp = ["machine_id", "part_number", "timestamp", "scrap_event"]
    fp_payload = df[cols_for_fp].head(2000).to_csv(index=False)
    fingerprint = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()
    meta = {
        "rows": int(len(df)),
        "rows_mapped_part": int((df["part_number"] != "UNKNOWN").sum()),
        "machines": int(df["machine_id"].nunique()),
        "parts": int(df["part_number"].nunique()),
        "fingerprint": fingerprint,
    }
    return df, meta
