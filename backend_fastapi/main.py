import asyncio
import csv
import json
import logging
import os
import re
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from statistics import median
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

# Keep TensorFlow startup quiet/deterministic before any TF import path is reached.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

# Use selector loop on Windows to avoid noisy Proactor transport shutdown errors
# when clients disconnect/reset sockets (WinError 10054).
if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

try:
    from . import database
    from . import engine as ai_engine
    from . import models
    from .database import get_db, init_db, with_reconnect
except ImportError:
    import database
    import engine as ai_engine
    import models
    from database import get_db, init_db, with_reconnect
try:
    from data_access import (
        _generate_future_horizon,
        RAW_TO_FRONTEND_SENSOR_MAP,
        analyze_root_causes,
        build_future_timeline,
        convert_safe_limits_to_frontend,
        get_active_model_metadata,
        predict_multi_horizon_scrap_risk,
        predict_future_scrap_risk,
        telemetry_to_sensor_row,
    )
except ImportError:
    from .data_access import (
        _generate_future_horizon,
        RAW_TO_FRONTEND_SENSOR_MAP,
        analyze_root_causes,
        build_future_timeline,
        convert_safe_limits_to_frontend,
        get_active_model_metadata,
        predict_multi_horizon_scrap_risk,
        predict_future_scrap_risk,
        telemetry_to_sensor_row,
    )
try:
    from model_registry import (
        load_registry,
        promote_model,
        rollback_model,
        save_registry,
    )
except ImportError:
    from .model_registry import (
        load_registry,
        promote_model,
        rollback_model,
        save_registry,
    )
try:
    from train_pipeline import load_latest_benchmark, run_training_pipeline
except ImportError:
    from .train_pipeline import load_latest_benchmark, run_training_pipeline
try:
    from dynamic_limits import calculate_dynamic_limits
except ImportError:
    from .dynamic_limits import calculate_dynamic_limits

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("factory_brain.api")
_ASYNCIO_PREV_EXCEPTION_HANDLER: Optional[Any] = None


def _is_windows_connection_reset_noise(context: Dict[str, Any]) -> bool:
    if os.name != "nt":
        return False

    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False

    win_error = getattr(exc, "winerror", None)
    if win_error != 10054:
        return False

    message = str(context.get("message") or "").lower()
    handle = str(context.get("handle") or "").lower()
    callback = str(context.get("source_traceback") or "").lower()
    proactor_signature = "_proactorbasepipetransport._call_connection_lost"
    return (
        proactor_signature in message
        or proactor_signature in handle
        or proactor_signature in callback
    )


def _install_asyncio_exception_filter() -> None:
    global _ASYNCIO_PREV_EXCEPTION_HANDLER
    loop = asyncio.get_running_loop()
    _ASYNCIO_PREV_EXCEPTION_HANDLER = loop.get_exception_handler()

    def _handler(active_loop: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
        if _is_windows_connection_reset_noise(context):
            logger.debug("Suppressed known Windows socket reset callback noise (WinError 10054).")
            return
        if _ASYNCIO_PREV_EXCEPTION_HANDLER is not None:
            _ASYNCIO_PREV_EXCEPTION_HANDLER(active_loop, context)
            return
        active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def _restore_asyncio_exception_filter() -> None:
    global _ASYNCIO_PREV_EXCEPTION_HANDLER
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_ASYNCIO_PREV_EXCEPTION_HANDLER)
    _ASYNCIO_PREV_EXCEPTION_HANDLER = None

# --- Pydantic Models for Response Validation ---
class PredictionSchema(BaseModel):
    scrap_probability: float
    expected_scrap_rate: Optional[float] = None
    confidence: float
    risk_level: str
    primary_defect_risk: str
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    model_label: Optional[str] = None
    confidence_raw: Optional[float] = None
    confidence_empirical: Optional[float] = None
    confidence_method: Optional[str] = None
    maintenance_urgency: Optional[str] = "LOW"
    engine_version: Optional[str] = "LSTM-Hyper v6.0.0-PRO"
    synergy_detected: Optional[bool] = False
    anomaly_contribution: Optional[float] = 0.0


class Forecast1h(BaseModel):
    horizon_minutes: int = 60
    predicted_value: float
    predicted_deviation: float
    deviation_change: float
    will_exceed_tolerance: bool
    expected_excess: float
    trend: str
    expected_threshold_cross_minutes: Optional[float] = None
    velocity_used: Optional[float] = None
    velocity_source: Optional[str] = None


# Global AI Model Placeholder for LSTM/TensorFlow (Pre-loaded at startup)
AI_MODEL: Any = None

class ModelInputSequence(BaseModel):
    """Pydantic model for LSTM sequence validation as per Best Practices."""
    machine_id: str
    sequence: List[Dict[str, float]] = Field(..., min_items=10, max_items=240)
    horizon_minutes: int = 1920


class PredictBatchRequest(BaseModel):
    machine_id: str
    sequence: List[Dict[str, float]] = Field(..., min_items=10, max_items=240)
    horizon_cycles: int = Field(default=30, ge=5, le=120)
    part_number: Optional[str] = None


class ExplainPredictionRequest(PredictBatchRequest):
    top_k: int = Field(default=8, ge=3, le=20)

class TelemetryValue(BaseModel):
    value: Any
    safe_min: Optional[float] = None
    safe_max: Optional[float] = None
    setpoint: Optional[float] = None
    velocity: Optional[float] = 0.0
    acceleration: Optional[float] = 0.0
    velocity_effective: Optional[float] = None
    velocity_source: Optional[str] = None
    ttqt: Optional[float] = None
    forecast_1h: Optional[Forecast1h] = None

class CyclePayload(BaseModel):
    cycle_id: str
    timestamp: str
    telemetry: Dict[str, TelemetryValue]
    predictions: Optional[PredictionSchema] = None
    shap_attributions: List[Dict[str, Any]] = []

class MachineSummary(BaseModel):
    id: str
    name: str
    status: str
    oee: int
    scraps: int
    temp: float
    cushion: Optional[float] = None
    cycles: int
    abnormal_params: List[str] = []
    maintenance_urgency: Optional[str] = "LOW"

class IngestionMachineState(BaseModel):
    status: str
    error: Optional[str] = None
    inserted: int
    pruned: int
    source_rows: int

class SystemStatus(BaseModel):
    ok: bool
    backend: str = "fastapi"
    version: str = "5.2.0"
    db_status: str
    data_status: str
    ingestion_status: str
    uptime_seconds: float
    details: Dict[str, Any]


class ModelTrainRequest(BaseModel):
    machine_ids: Optional[List[str]] = None
    segment_id: Optional[str] = None
    auto_promote: bool = False


class ModelPromoteRequest(BaseModel):
    task: str = Field(..., description="scrap_classifier|sensor_forecaster")
    model_id: str
    machine_id: Optional[str] = None
    part_number: Optional[str] = None


class ModelRollbackRequest(BaseModel):
    task: str = Field(..., description="scrap_classifier|sensor_forecaster")
    machine_id: Optional[str] = None
    part_number: Optional[str] = None


class AutoTrainConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_seconds: Optional[int] = Field(default=None, ge=300, le=604800)
    machine_ids: Optional[List[str]] = None
    segment_id: Optional[str] = None
    auto_promote: Optional[bool] = None
    run_immediately: Optional[bool] = False

# Startup time
STARTUP_TIME = time.time()
MODEL_JOBS: Dict[str, Dict[str, Any]] = {}
model_runtime_state: Dict[str, Any] = {
    "last_refresh_at": None,
    "last_refresh_reason": None,
    "last_refresh_ok": None,
    "last_error": None,
    "last_registry_signature": None,
}
auto_train_state: Dict[str, Any] = {
    "enabled": False,
    "interval_seconds": 3600,
    "machine_ids": None,
    "segment_id": None,
    "auto_promote": False,
    "last_run_at": None,
    "last_run_epoch": None,
    "last_job_id": None,
    "last_error": None,
    "last_result": None,
    "next_run_at": None,
    "skipped_overlap_count": 0,
}


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    global AI_MODEL, STARTUP_TIME
    init_db()
    model_path = os.path.join(MODELS_DIR, "lstm_scrap_risk.h5")
    AI_MODEL = ai_engine.LSTMPredictor(model_path=model_path, models_dir=MODELS_DIR)
    ai_engine.AI_MODEL = AI_MODEL
    STARTUP_TIME = time.time()
    _install_asyncio_exception_filter()
    _configure_auto_train_state()
    _refresh_sequence_runtime("startup_init", force=True)

    await _ensure_ingestion_task_running("startup_boot")
    app_instance.state.watchdog_task = asyncio.create_task(_connectivity_watchdog_loop())
    app_instance.state.model_refresh_task = asyncio.create_task(_model_registry_refresh_loop())
    app_instance.state.auto_training_task = asyncio.create_task(_auto_training_loop())
    lstm_ready = False
    lstm_reason = ""
    if AI_MODEL is not None:
        service = getattr(AI_MODEL, "service", None)
        if service is not None and hasattr(service, "is_available"):
            lstm_ready = bool(service.is_available())
            if (not lstm_ready) and hasattr(service, "unavailable_reason"):
                lstm_reason = str(service.unavailable_reason())
        elif hasattr(AI_MODEL, "predict_batch"):
            lstm_ready = True

    if lstm_ready:
        logger.info("FastAPI backend is live. LSTM sequence model pre-loaded. Continuous ingestion enabled.")
    else:
        reason_suffix = f" Reason: {lstm_reason}" if lstm_reason else ""
        logger.warning("FastAPI backend is live. LSTM sequence model is unavailable.%s Continuous ingestion enabled.", reason_suffix)
    try:
        yield
    finally:
        with suppress(Exception):
            _restore_asyncio_exception_filter()
        for task_name in ("watchdog_task", "ingestion_task", "model_refresh_task", "auto_training_task"):
            task = getattr(app_instance.state, task_name, None)
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if AI_MODEL is not None and hasattr(AI_MODEL, "service") and hasattr(AI_MODEL.service, "close"):
            with suppress(Exception):
                AI_MODEL.service.close()


app = FastAPI(title="Smart Factory Brain - FastAPI", lifespan=lifespan)

# Middleware & Gzip
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_process_time_and_request_id(request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Request-ID"] = request_id
    return response
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
ALLOW_CREDENTIALS = ALLOWED_ORIGINS != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Internal Server Error", "detail": str(exc) if os.getenv("DEBUG") else "An unexpected error occurred."}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail}
    )


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv_list(name: str) -> Optional[List[str]]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return None
    items = [item.strip() for item in str(raw_value).split(",") if item.strip()]
    return items or None


def _horizon_minutes_to_cycles(horizon_minutes: int) -> int:
    # Shop-floor cycles are not strictly minute-based; map to bounded cycle horizon.
    if horizon_minutes <= 0:
        return 30
    return max(5, min(120, int(round(horizon_minutes / 2.0))))


# Constants
MACHINE_IDS = ["M231-11", "M356-57", "M471-23", "M607-30", "M612-33"]
MACHINE_NAMES = {
    "M231-11": "Engel ES-200",
    "M356-57": "Arburg 370S",
    "M471-23": "Haitian J300",
    "M607-30": "JSW J85E-II",
    "M612-33": "Fanuc S-2000i",
}
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "..", "frontend", "Data"))
MES_WORKBOOK_PATH = os.getenv(
    "MES_WORKBOOK_PATH",
    os.path.join(DATA_DIR, "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"),
)
MACHINE_FILE_EXTENSIONS = [".csv", ".xlsx", ".xls", ""]
MODELS_DIR = os.path.join(BASE_DIR, "models")
MAX_API_LIMIT = _env_int("MAX_API_LIMIT", 1000)
MAX_CYCLES_PER_MACHINE = _env_int("MAX_CYCLES_PER_MACHINE", 5000)
INITIAL_LOAD_CYCLES = _env_int("INITIAL_LOAD_CYCLES", 500)
WS_STREAM_LIMIT = _env_int("WS_STREAM_LIMIT", 20)
WS_STREAM_INTERVAL_SEC = _env_float("WS_STREAM_INTERVAL_SEC", 3.0)
WATCHDOG_INTERVAL_SEC = max(5.0, _env_float("WATCHDOG_INTERVAL_SEC", 15.0))
MODEL_REFRESH_INTERVAL_SEC = max(10.0, _env_float("MODEL_REFRESH_INTERVAL_SEC", 30.0))
AUTO_TRAIN_INTERVAL_SEC = max(300.0, _env_float("AUTO_TRAIN_INTERVAL_SEC", 3600.0))
AUTO_TRAIN_ENABLED = _env_bool("AUTO_TRAIN_ENABLED", False)
AUTO_TRAIN_AUTO_PROMOTE = _env_bool("AUTO_TRAIN_AUTO_PROMOTE", False)
AUTO_TRAIN_MACHINE_IDS = _env_csv_list("AUTO_TRAIN_MACHINE_IDS")
AUTO_TRAIN_SEGMENT_ID = os.getenv("AUTO_TRAIN_SEGMENT_ID")
MAX_MODEL_JOBS_HISTORY = max(50, _env_int("MAX_MODEL_JOBS_HISTORY", 300))
PRUNE_BATCH_SIZE = max(1, min(_env_int("PRUNE_BATCH_SIZE", 500), 900))
CSV_RESUME_CHUNK_ROWS = max(1000, min(_env_int("CSV_RESUME_CHUNK_ROWS", 20000), 100000))

# Runtime state
machine_contexts: Dict[str, Dict[str, Any]] = {}
ingestion_state: Dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "machines": {},
}
connectivity_state: Dict[str, Any] = {
    "reconnect_attempts": 0,
    "last_reconnect_at": None,
    "last_reconnect_reason": None,
    "last_reconnect_ok": None,
}
MAX_ERROR_MESSAGE_LEN = 600
part_catalog_cache: Dict[str, Any] = {"mtime": None, "data": {}}
part_timeline_cache: Dict[str, Any] = {"mtime": None, "data": {}}


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _get_machine_context(machine_id: str) -> Dict[str, Any]:
    """
    Per-machine runtime context retained across ingestion cycles.
    Keeps drift tracker, source cursors, and stream markers.
    """
    context = machine_contexts.setdefault(machine_id, {})
    if "drift_tracker" not in context or context.get("drift_tracker") is None:
        context["drift_tracker"] = ai_engine.DriftTracker()
    if "source_offsets" not in context or not isinstance(context.get("source_offsets"), dict):
        context["source_offsets"] = {}
    return context


def _machine_numeric_code(machine_id: str) -> Optional[str]:
    if not isinstance(machine_id, str):
        return None
    text = machine_id.strip().upper()
    if not text:
        return None

    # Prefer explicit machine-id formats first (e.g. M231-11, M-231, M1207-30).
    match = re.search(r"^M[-_ ]?(\d{3,5})(?:[-_ ]\d+)?$", text)
    if match:
        return match.group(1)

    # Accept standalone MES variants (e.g. 231, 1207, 231-11).
    match = re.search(r"^(\d{3,5})(?:[-_ ]\d+)?$", text)
    if match:
        return match.group(1)

    # Fallback for embedded labels.
    match = re.search(r"\bM[-_ ]?(\d{3,5})\b", text)
    if match:
        return match.group(1)

    # Last resort: any 3-5 digit sequence.
    match = re.search(r"(\d{3,5})", text)
    return match.group(1) if match else None


def _normalize_mes_machine(machine_id: Any) -> Optional[str]:
    if machine_id is None:
        return None
    code = _machine_numeric_code(str(machine_id))
    if not code:
        return None
    return f"M-{code}"


def _normalize_part_number(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return None

    normalized = text.upper()
    if normalized in {"N", "NA", "N/A", "NONE", "NULL", "NAN", "AD", "-"}:
        return None

    # Keep only practical part tokens that include at least one digit.
    if not re.search(r"\d", normalized):
        return None

    return normalized


def _load_part_catalog(force_reload: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(MES_WORKBOOK_PATH):
        return {}

    try:
        mtime = os.path.getmtime(MES_WORKBOOK_PATH)
    except OSError:
        return {}

    cache_mtime = part_catalog_cache.get("mtime")
    if (not force_reload) and cache_mtime == mtime and isinstance(part_catalog_cache.get("data"), dict):
        return part_catalog_cache["data"]

    try:
        df_raw = pd.read_excel(MES_WORKBOOK_PATH, sheet_name="Data")
    except Exception as exc:
        logger.warning("Failed to read MES workbook for part catalog: %s", exc)
        return {}

    if df_raw.empty:
        return {}

    col_map = {str(col).strip().lower(): col for col in df_raw.columns}
    machine_col = col_map.get("machine_id")
    part_col = col_map.get("part_number")
    if machine_col is None or part_col is None:
        logger.warning(
            "MES workbook is missing required columns (machine_id, part_number): %s",
            MES_WORKBOOK_PATH,
        )
        return {}

    df = df_raw[[machine_col, part_col]].rename(
        columns={machine_col: "machine_id", part_col: "part_number"}
    )

    df["machine_id"] = df["machine_id"].map(_normalize_mes_machine)
    df["part_number"] = df["part_number"].map(_normalize_part_number)
    df = df.dropna(subset=["machine_id", "part_number"])

    if df.empty:
        return {}

    grouped = (
        df.groupby(["machine_id", "part_number"])
        .size()
        .reset_index(name="events")
        .sort_values(["machine_id", "events", "part_number"], ascending=[True, False, True])
    )

    mes_catalog: Dict[str, List[Dict[str, Any]]] = {}
    for _, row in grouped.iterrows():
        machine = str(row["machine_id"])
        mes_catalog.setdefault(machine, []).append(
            {"part_number": str(row["part_number"]), "events": int(row["events"])}
        )

    resolved_catalog: Dict[str, List[Dict[str, Any]]] = {}
    for machine_id in MACHINE_IDS:
        code = _machine_numeric_code(machine_id)
        mes_machine = f"M-{code}" if code else None
        resolved_catalog[machine_id] = mes_catalog.get(mes_machine, []) if mes_machine else []

    part_catalog_cache["mtime"] = mtime
    part_catalog_cache["data"] = resolved_catalog
    return resolved_catalog


def _runtime_machine_from_mes(machine_id: Any) -> Optional[str]:
    code = _machine_numeric_code(str(machine_id)) if machine_id is not None else None
    if not code:
        return None
    for runtime_machine in MACHINE_IDS:
        if _machine_numeric_code(runtime_machine) == code:
            return runtime_machine
    return None


def _parse_mes_time_seconds(raw_value: Any) -> Optional[int]:
    if raw_value is None:
        return None
    try:
        if pd.isna(raw_value):
            return None
    except Exception:
        pass

    # Already formatted clock string (e.g. "18:00:00")
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        if ":" in text:
            try:
                parts = [int(part) for part in text.split(":")]
            except ValueError:
                parts = []
            if len(parts) == 3:
                hh, mm, ss = parts
                if 0 <= hh < 48 and 0 <= mm < 60 and 0 <= ss < 60:
                    return (hh * 3600) + (mm * 60) + ss
            elif len(parts) == 2:
                mm, ss = parts
                if 0 <= mm < 60 and 0 <= ss < 60:
                    return (mm * 60) + ss

    try:
        numeric = int(float(raw_value))
    except (TypeError, ValueError):
        return None

    if numeric < 0:
        return None

    # MES exports often store event times as seconds since midnight.
    if numeric <= 172800:
        return numeric

    # Fallback for HHMMSS-like values.
    text = str(numeric).zfill(6)[-6:]
    try:
        hh = int(text[0:2])
        mm = int(text[2:4])
        ss = int(text[4:6])
    except ValueError:
        return None
    if 0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60:
        return (hh * 3600) + (mm * 60) + ss
    return None


def _parse_mes_datetime(date_value: Any, time_value: Any) -> Optional[datetime]:
    if date_value is None:
        return None
    try:
        date_ts = pd.Timestamp(date_value)
    except Exception:
        return None
    if pd.isna(date_ts):
        return None

    base = date_ts.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    seconds = _parse_mes_time_seconds(time_value)
    if seconds is None:
        return base
    return base + timedelta(seconds=int(seconds))


def _load_part_timeline(force_reload: bool = False) -> Dict[str, pd.DataFrame]:
    """
    Load MES part-change timeline and expose per-machine event stream:
    event_ts -> part_number.
    """
    if not os.path.exists(MES_WORKBOOK_PATH):
        return {}

    try:
        mtime = os.path.getmtime(MES_WORKBOOK_PATH)
    except OSError:
        return {}

    cache_mtime = part_timeline_cache.get("mtime")
    if (not force_reload) and cache_mtime == mtime and isinstance(part_timeline_cache.get("data"), dict):
        return part_timeline_cache["data"]

    try:
        df_raw = pd.read_excel(MES_WORKBOOK_PATH, sheet_name="Data")
    except Exception as exc:
        logger.warning("Failed to read MES workbook for part timeline: %s", exc)
        return {}

    if df_raw.empty:
        return {}

    col_map = {str(col).strip().lower(): col for col in df_raw.columns}
    machine_col = col_map.get("machine_id")
    part_col = col_map.get("part_number")
    if machine_col is None or part_col is None:
        return {}

    end_date_col = col_map.get("machine_event_end_date")
    end_time_col = col_map.get("machine_event_end_time")
    create_date_col = col_map.get("machine_event_create_date")
    create_time_col = col_map.get("machine_event_create_time")
    shift_ts_col = col_map.get("plant_shift_timestamp")
    shift_date_col = col_map.get("plant_shift_date")

    df = df_raw.copy()
    df["machine_id"] = df[machine_col].map(_runtime_machine_from_mes)
    df["part_number"] = df[part_col].map(_normalize_part_number)
    df = df.dropna(subset=["machine_id", "part_number"])
    if df.empty:
        return {}

    event_timestamps: List[Optional[datetime]] = []
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
                    event_ts = shift_ts.to_pydatetime().replace(tzinfo=None)
            except Exception:
                event_ts = None
        if event_ts is None and shift_date_col:
            try:
                shift_date = pd.Timestamp(row.get(shift_date_col))
                if not pd.isna(shift_date):
                    event_ts = shift_date.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            except Exception:
                event_ts = None
        event_timestamps.append(event_ts)

    df["event_ts"] = event_timestamps
    df = df.dropna(subset=["event_ts"])
    if df.empty:
        return {}

    df["event_ts"] = pd.to_datetime(df["event_ts"]).dt.tz_localize(None)
    df = df.sort_values(["machine_id", "event_ts"])

    timeline_by_machine: Dict[str, pd.DataFrame] = {}
    for machine_id, machine_df in df.groupby("machine_id"):
        timeline = machine_df[["event_ts", "part_number"]].copy()
        timeline = timeline.drop_duplicates(subset=["event_ts"], keep="last")
        timeline_by_machine[str(machine_id)] = timeline.reset_index(drop=True)

    part_timeline_cache["mtime"] = mtime
    part_timeline_cache["data"] = timeline_by_machine
    return timeline_by_machine


def _filter_cycles_by_part_timeline(
    cycles: List[models.Cycle],
    machine_id: str,
    part_number: Optional[str],
) -> Tuple[List[models.Cycle], Dict[str, Any]]:
    normalized_part = _normalize_part_number(part_number)
    base_meta = {
        "applied": False,
        "part_number": normalized_part,
        "total_cycles": len(cycles),
        "matched_cycles": len(cycles),
        "timeline_events": 0,
        "message": "Part filter not requested.",
    }
    if not cycles or not normalized_part:
        return cycles, base_meta

    timeline_by_machine = _load_part_timeline()
    timeline = timeline_by_machine.get(machine_id)
    if timeline is None or timeline.empty:
        meta = {
            "applied": True,
            "part_number": normalized_part,
            "total_cycles": len(cycles),
            "matched_cycles": 0,
            "timeline_events": 0,
            "message": "No MES part timeline available for this machine.",
        }
        return [], meta

    cycles_sorted = sorted(cycles, key=lambda cycle: (cycle.timestamp, int(getattr(cycle, "id", 0) or 0)))
    cycle_rows = [
        {
            "idx": idx,
            "cycle_ts": pd.Timestamp(cycle.timestamp).to_pydatetime().replace(tzinfo=None),
        }
        for idx, cycle in enumerate(cycles_sorted)
    ]
    cycle_df = pd.DataFrame(cycle_rows).sort_values("cycle_ts")
    timeline_df = timeline.copy().sort_values("event_ts")
    timeline_df["part_number"] = timeline_df["part_number"].astype(str).str.upper()

    merged = pd.merge_asof(
        cycle_df,
        timeline_df,
        left_on="cycle_ts",
        right_on="event_ts",
        direction="backward",
    )

    matched = merged[merged["part_number"] == normalized_part]
    matched_indices = matched["idx"].dropna().astype(int).tolist()
    filtered = [cycles_sorted[idx] for idx in matched_indices]
    meta = {
        "applied": True,
        "part_number": normalized_part,
        "total_cycles": len(cycles),
        "matched_cycles": len(filtered),
        "timeline_events": int(len(timeline_df)),
        "message": (
            "Part timeline filter matched cycles."
            if filtered
            else f"No cycles matched selected part '{normalized_part}' in MES timeline."
        ),
    }
    return filtered, meta


def _to_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN check
        return None
    return parsed


def _extract_scrap_counter(telemetry: Any) -> Optional[float]:
    if not isinstance(telemetry, dict):
        return None
    candidate = telemetry.get("scrap_counter")
    if not isinstance(candidate, dict):
        return None
    return _to_float(candidate.get("value"))


def _estimate_cycle_time_seconds(telemetry: Dict[str, Any]) -> float:
    cycle_item = telemetry.get("cycle_time")
    if isinstance(cycle_item, dict):
        cycle_seconds = _to_float(cycle_item.get("value"))
        if cycle_seconds is not None and cycle_seconds > 0.05:
            return cycle_seconds
    return 20.0


def _build_one_hour_forecast(
    param_data: Dict[str, Any],
    cycle_time_seconds: float,
    fallback_velocity: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    value = _to_float(param_data.get("value"))
    setpoint = _to_float(param_data.get("setpoint"))
    safe_min = _to_float(param_data.get("safe_min"))
    safe_max = _to_float(param_data.get("safe_max"))
    raw_velocity = _to_float(param_data.get("velocity"))

    if None in (value, setpoint, safe_min, safe_max):
        return None

    velocity_source = "telemetry"
    velocity = raw_velocity
    if velocity is None:
        velocity = fallback_velocity
        velocity_source = "history_fallback"
    elif abs(velocity) <= 1e-9 and fallback_velocity is not None and abs(fallback_velocity) > 1e-9:
        velocity = fallback_velocity
        velocity_source = "history_fallback"

    if velocity is None:
        return None

    tolerance = max(abs(safe_max - setpoint), abs(setpoint - safe_min))
    if tolerance <= 0:
        return None

    cycles_per_hour = _clamp(3600.0 / max(0.05, cycle_time_seconds), 1.0, 7200.0)
    predicted_value = value + (velocity * cycles_per_hour)
    current_deviation = abs(value - setpoint)
    predicted_deviation = abs(predicted_value - setpoint)
    deviation_change = predicted_deviation - current_deviation
    expected_excess = max(0.0, predicted_deviation - tolerance)

    trend = "flat"
    if velocity > 0.0001:
        trend = "up"
    elif velocity < -0.0001:
        trend = "down"

    ttqt_cycles = _to_float(param_data.get("ttqt"))
    expected_threshold_cross_minutes: Optional[float] = None
    if ttqt_cycles is not None and ttqt_cycles < 999:
        expected_threshold_cross_minutes = round((ttqt_cycles * cycle_time_seconds) / 60.0, 2)

    return {
        "horizon_minutes": 60,
        "predicted_value": round(predicted_value, 4),
        "predicted_deviation": round(predicted_deviation, 4),
        "deviation_change": round(deviation_change, 4),
        "will_exceed_tolerance": predicted_deviation > tolerance,
        "expected_excess": round(expected_excess, 4),
        "trend": trend,
        "expected_threshold_cross_minutes": expected_threshold_cross_minutes,
        "velocity_used": round(velocity, 6),
        "velocity_source": velocity_source,
    }


def _compute_velocity_fallbacks(cycles: List[Dict[str, Any]], lookback: int = 20) -> List[Dict[str, float]]:
    """
    Build per-cycle fallback velocity for each telemetry parameter using
    median of recent cycle-to-cycle deltas.
    """
    if not cycles:
        return []

    fallbacks: List[Dict[str, float]] = [{} for _ in cycles]
    prev_values: Dict[str, float] = {}
    diff_history: Dict[str, List[float]] = {}

    for idx, cycle in enumerate(cycles):
        telemetry = cycle.get("telemetry")
        if not isinstance(telemetry, dict):
            continue

        for param_name, param_data in telemetry.items():
            if not isinstance(param_data, dict):
                continue

            value = _to_float(param_data.get("value"))
            if value is None:
                continue

            prev_val = prev_values.get(param_name)
            if prev_val is not None:
                diff_history.setdefault(param_name, []).append(value - prev_val)
            prev_values[param_name] = value

        for param_name, deltas in diff_history.items():
            if not deltas:
                continue
            recent = deltas[-lookback:]
            fallbacks[idx][param_name] = float(median(recent))

    return fallbacks


def _enrich_telemetry_forecasts(
    cycle: Dict[str, Any],
    velocity_fallbacks: Optional[Dict[str, float]] = None,
    force_recompute: bool = False,
) -> None:
    telemetry = cycle.get("telemetry")
    if not isinstance(telemetry, dict):
        return

    cycle_time_seconds = _estimate_cycle_time_seconds(telemetry)
    for param_name, param_data in telemetry.items():
        if not isinstance(param_data, dict):
            continue
        if isinstance(param_data.get("forecast_1h"), dict) and not force_recompute:
            continue
        fallback_velocity = None
        if isinstance(velocity_fallbacks, dict):
            fallback_velocity = velocity_fallbacks.get(param_name)

        forecast = _build_one_hour_forecast(
            param_data,
            cycle_time_seconds,
            fallback_velocity=fallback_velocity,
        )
        if forecast:
            param_data["forecast_1h"] = forecast
            param_data["velocity_effective"] = forecast.get("velocity_used")
            param_data["velocity_source"] = forecast.get("velocity_source")


def _calibrate_predictions(cycles: List[Dict[str, Any]], initial_brier: float = 0.18) -> List[Dict[str, Any]]:
    """
    Calibrate confidence using empirical outcome quality from Scrap_counter increments.
    - Uses EWMA Brier score on observed outcomes when available.
    - Blends raw model confidence with empirical reliability.
    """
    if not cycles:
        return cycles

    prev_scrap_counter: Optional[float] = None
    brier_ewma = _clamp(initial_brier, 0.01, 0.99)
    observed_count = 0
    positive_count = 0
    prevalence_ewma = 0.08
    velocity_fallbacks = _compute_velocity_fallbacks(cycles)

    for idx, cycle in enumerate(cycles):
        fallback_map = velocity_fallbacks[idx] if idx < len(velocity_fallbacks) else None
        _enrich_telemetry_forecasts(cycle, velocity_fallbacks=fallback_map, force_recompute=True)
        predictions = cycle.get("predictions")
        if not isinstance(predictions, dict):
            continue

        raw_prob = _to_float(predictions.get("scrap_probability"))
        if raw_prob is None:
            raw_prob = 0.0
        prob = _clamp(raw_prob, 0.0, 1.0)

        raw_confidence = _to_float(predictions.get("confidence_raw"))
        if raw_confidence is None:
            raw_confidence = _to_float(predictions.get("confidence"))
        if raw_confidence is None:
            raw_confidence = 0.75
        raw_confidence = _clamp(raw_confidence, 0.0, 1.0)

        observed_scrap: Optional[int] = None
        current_scrap_counter = _extract_scrap_counter(cycle.get("telemetry"))
        if current_scrap_counter is not None and prev_scrap_counter is not None:
            observed_scrap = 1 if current_scrap_counter > prev_scrap_counter else 0
        if current_scrap_counter is not None:
            prev_scrap_counter = current_scrap_counter

        if observed_scrap is not None:
            observed_count += 1
            positive_count += int(observed_scrap)
            prevalence_ewma = (0.98 * prevalence_ewma) + (0.02 * float(observed_scrap))
            brier = (_clamp(prob, 0.02, 0.98) - observed_scrap) ** 2
            brier_ewma = (0.92 * brier_ewma) + (0.08 * brier)

        # Convert Brier error into a bounded confidence via skill score vs prevalence baseline.
        baseline_brier = max(prevalence_ewma * (1.0 - prevalence_ewma), 0.02)
        brier_skill = _clamp(1.0 - (brier_ewma / baseline_brier), -1.0, 1.0)
        empirical_confidence = _clamp(0.50 + (0.45 * brier_skill), 0.05, 0.95)

        # Sparse-label safeguard: when scrap events are rare, avoid over-penalizing confidence.
        if observed_count < 30:
            warmup_ratio = observed_count / 30.0
            empirical_confidence = ((1.0 - warmup_ratio) * 0.78) + (warmup_ratio * empirical_confidence)

        empirical_weight = min(0.55, 0.20 + (0.35 * min(1.0, observed_count / 120.0)))
        if positive_count < 3:
            empirical_weight *= 0.60

        margin_confidence = _clamp(abs(prob - 0.5) * 2.0, 0.0, 1.0)
        blended = ((1.0 - empirical_weight) * raw_confidence) + (empirical_weight * empirical_confidence)
        blended = (0.75 * blended) + (0.25 * (0.60 + (0.35 * margin_confidence)))
        calibrated = _clamp(blended, 0.58, 0.98)

        predictions["confidence_raw"] = round(raw_confidence, 4)
        predictions["confidence_empirical"] = round(empirical_confidence, 4)
        predictions["confidence_method"] = "calibrated_brier_skill_sparse_safe"
        predictions["confidence"] = round(calibrated, 4)

    return cycles


def _safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return float(numerator / denominator)


def _compute_machine_ai_kpis(
    db: Session,
    machine_id: str,
    window_cycles: int,
    risk_threshold: float,
    lead_window_cycles: int,
) -> Dict[str, Any]:
    cycles = (
        db.query(models.Cycle)
        .options(joinedload(models.Cycle.prediction))
        .filter(models.Cycle.machine_id == machine_id)
        .order_by(models.Cycle.timestamp.desc(), models.Cycle.id.desc())
        .limit(window_cycles)
        .all()
    )
    cycles = list(reversed(cycles))
    if not cycles:
        return {
            "machine_id": machine_id,
            "cycles_considered": 0,
            "labeled_samples": 0,
            "observed_scrap_events": 0,
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "accuracy": 0.0,
            "false_alarm_rate": 0.0,
            "missed_scrap_rate": 0.0,
            "brier_score": 0.0,
            "avg_confidence": 0.0,
            "lead_time_minutes_mean": 0.0,
            "lead_time_events": 0,
            "missed_events_no_lead_alert": 0,
            "_brier_sum": 0.0,
            "_brier_n": 0,
            "_confidence_sum": 0.0,
            "_confidence_n": 0,
        }

    probabilities: List[float] = []
    confidences: List[float] = []
    labels: List[int] = []
    preds: List[int] = []
    eval_probs: List[float] = []
    lead_minutes: List[float] = []
    observed_events = 0
    missed_events_no_lead_alert = 0

    prev_scrap_counter: Optional[float] = None
    for idx, cycle in enumerate(cycles):
        tele = cycle.data or {}
        pred = cycle.prediction
        prob = _to_float(pred.scrap_probability) if pred else None
        if prob is None:
            prob = 0.0
        prob = _clamp(float(prob), 0.0, 1.0)
        probabilities.append(prob)

        confidence = _to_float(pred.confidence) if pred else None
        if confidence is not None:
            confidences.append(_clamp(float(confidence), 0.0, 1.0))

        current_scrap_counter = _extract_scrap_counter(tele)
        observed_scrap: Optional[int] = None
        if current_scrap_counter is not None and prev_scrap_counter is not None:
            observed_scrap = 1 if current_scrap_counter > prev_scrap_counter else 0
        if current_scrap_counter is not None:
            prev_scrap_counter = current_scrap_counter

        if observed_scrap is None:
            continue

        predicted_scrap = 1 if prob >= risk_threshold else 0
        labels.append(observed_scrap)
        preds.append(predicted_scrap)
        eval_probs.append(prob)
        if observed_scrap == 1:
            observed_events += 1
            start_idx = max(0, idx - lead_window_cycles)
            first_alert_idx: Optional[int] = None
            for lookback_idx in range(start_idx, idx):
                if probabilities[lookback_idx] >= risk_threshold:
                    first_alert_idx = lookback_idx
                    break

            if first_alert_idx is None:
                missed_events_no_lead_alert += 1
            else:
                cycle_seconds = [
                    _estimate_cycle_time_seconds(cycles[k].data or {})
                    for k in range(first_alert_idx, idx)
                ]
                avg_cycle_seconds = (sum(cycle_seconds) / len(cycle_seconds)) if cycle_seconds else 20.0
                lead_cycles = max(0, idx - first_alert_idx)
                lead_minutes.append(float((lead_cycles * avg_cycle_seconds) / 60.0))

    tp = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 1)
    tn = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 0)
    fn = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 0)
    total = len(labels)

    brier_sum = sum((eval_probs[i] - labels[i]) ** 2 for i in range(len(labels))) if labels else 0.0
    brier_n = len(labels)

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2.0 * precision * recall, precision + recall) if (precision + recall) else 0.0
    accuracy = _safe_div(tp + tn, total)
    false_alarm_rate = _safe_div(fp, total)
    missed_scrap_rate = _safe_div(fn, tp + fn)

    avg_conf = _safe_div(sum(confidences), len(confidences)) if confidences else 0.0
    lead_mean = _safe_div(sum(lead_minutes), len(lead_minutes)) if lead_minutes else 0.0

    return {
        "machine_id": machine_id,
        "cycles_considered": len(cycles),
        "labeled_samples": total,
        "observed_scrap_events": observed_events,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "false_alarm_rate": round(false_alarm_rate, 4),
        "missed_scrap_rate": round(missed_scrap_rate, 4),
        "brier_score": round(_safe_div(brier_sum, brier_n), 6) if brier_n else 0.0,
        "avg_confidence": round(avg_conf, 4),
        "lead_time_minutes_mean": round(lead_mean, 4),
        "lead_time_events": len(lead_minutes),
        "missed_events_no_lead_alert": missed_events_no_lead_alert,
        "_brier_sum": float(brier_sum),
        "_brier_n": int(brier_n),
        "_confidence_sum": float(sum(confidences)),
        "_confidence_n": int(len(confidences)),
    }


def _normalize_machine_query(value: Any) -> str:
    if value is None:
        return ""
    # Accept lowercase, spacing, and underscore variants from clients.
    return str(value).strip().lower().replace("_", "-").replace(" ", "")


def _machine_match_candidates(machine_id: Any) -> List[str]:
    query = _normalize_machine_query(machine_id)
    if not query:
        return []

    normalized_ids = {
        mid: _normalize_machine_query(mid) for mid in MACHINE_IDS
    }

    exact = [mid for mid, norm in normalized_ids.items() if norm == query]
    if exact:
        return exact

    starts_with = [mid for mid, norm in normalized_ids.items() if norm.startswith(query)]
    if starts_with:
        return starts_with

    contains = [mid for mid, norm in normalized_ids.items() if query in norm]
    return contains


def _resolve_machine_id(machine_id: Any) -> Optional[str]:
    candidates = _machine_match_candidates(machine_id)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _machine_id_error_message(machine_id: Any, candidates: Optional[List[str]] = None) -> str:
    raw = "" if machine_id is None else str(machine_id).strip()
    valid_ids = ", ".join(MACHINE_IDS)
    if candidates:
        return f"Invalid machine ID '{raw}'. Did you mean: {', '.join(candidates)}? Valid IDs: {valid_ids}"
    return f"Invalid machine ID '{raw}'. Valid IDs: {valid_ids}"


def _require_machine_id(machine_id: Any) -> str:
    resolved = _resolve_machine_id(machine_id)
    if resolved:
        return resolved
    candidates = _machine_match_candidates(machine_id)
    raise HTTPException(status_code=400, detail=_machine_id_error_message(machine_id, candidates))


def _is_ws_closed_runtime_error(exc: RuntimeError) -> bool:
    msg = str(exc).lower()
    return (
        "websocket is not connected" in msg
        or "cannot call \"send\" once a close message has been sent" in msg
        or "unexpected asgi message 'websocket.send'" in msg
        or "after sending 'websocket.close'" in msg
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error_message(error: Any) -> Optional[str]:
    if error in (None, ""):
        return None
    msg = str(error).replace("\n", " ").strip()
    if len(msg) <= MAX_ERROR_MESSAGE_LEN:
        return msg
    return f"{msg[:MAX_ERROR_MESSAGE_LEN]}... [truncated]"


def _set_ingestion_state(**updates: Any) -> None:
    if "error" in updates:
        updates["error"] = _safe_error_message(updates.get("error"))
    ingestion_state.update(updates)


def _set_machine_state(machine_id: str, **updates: Any) -> None:
    if "error" in updates:
        updates["error"] = _safe_error_message(updates.get("error"))
    machine = ingestion_state["machines"].setdefault(machine_id, {})
    machine.update(updates)


def _resolve_machine_data_file(machine_id: str) -> Optional[str]:
    if not machine_id:
        return None

    candidates: List[str] = []
    # Primary expected names
    for ext in MACHINE_FILE_EXTENSIONS:
        candidates.append(os.path.join(DATA_DIR, f"{machine_id}{ext}"))

    # Alternate machine-name variants often used in MES exports
    code = _machine_numeric_code(machine_id)
    if code:
        variants = [f"M-{code}", f"M{code}", f"M_{code}"]
        for variant in variants:
            for ext in MACHINE_FILE_EXTENSIONS:
                candidates.append(os.path.join(DATA_DIR, f"{variant}{ext}"))

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def _ingestion_task_active() -> bool:
    task = getattr(app.state, "ingestion_task", None)
    return bool(task and not task.done())


def _csv_connectivity_snapshot() -> Dict[str, Any]:
    if not os.path.isdir(DATA_DIR):
        return {
            "data_dir": DATA_DIR,
            "exists": False,
            "csv_found": 0,
            "expected": len(MACHINE_IDS),
            "missing_machine_csv": MACHINE_IDS,
            "present_machine_csv": [],
        }

    present = []
    missing = []
    for machine_id in MACHINE_IDS:
        data_file = _resolve_machine_data_file(machine_id)
        if data_file:
            present.append(machine_id)
        else:
            missing.append(machine_id)

    return {
        "data_dir": DATA_DIR,
        "exists": True,
        "csv_found": len(present),
        "expected": len(MACHINE_IDS),
        "missing_machine_csv": missing,
        "present_machine_csv": present,
    }


def _norm_task_name(task: str) -> str:
    value = str(task or "").strip().lower()
    if value not in {"scrap_classifier", "sensor_forecaster"}:
        raise HTTPException(status_code=400, detail=f"Invalid task '{task}'.")
    return value


def _new_job_id() -> str:
    return f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _configure_auto_train_state() -> None:
    configured_ids: Optional[List[str]] = None
    if AUTO_TRAIN_MACHINE_IDS:
        resolved: List[str] = []
        for raw_mid in AUTO_TRAIN_MACHINE_IDS:
            mid = _resolve_machine_id(raw_mid)
            if mid and mid not in resolved:
                resolved.append(mid)
        configured_ids = resolved or None

    auto_train_state["enabled"] = bool(AUTO_TRAIN_ENABLED)
    auto_train_state["interval_seconds"] = int(AUTO_TRAIN_INTERVAL_SEC)
    auto_train_state["machine_ids"] = configured_ids
    auto_train_state["segment_id"] = AUTO_TRAIN_SEGMENT_ID or None
    auto_train_state["auto_promote"] = bool(AUTO_TRAIN_AUTO_PROMOTE)
    if auto_train_state.get("last_run_epoch") is None:
        auto_train_state["last_run_epoch"] = time.time()


def _active_training_job_id() -> Optional[str]:
    for jid, job in MODEL_JOBS.items():
        status = str((job or {}).get("status", "")).strip().lower()
        if status in {"queued", "running"}:
            return jid
    return None


def _prune_model_jobs() -> None:
    if len(MODEL_JOBS) <= MAX_MODEL_JOBS_HISTORY:
        return
    # Keep active jobs + newest completed jobs.
    active_items = []
    completed_items = []
    for jid, job in MODEL_JOBS.items():
        status = str((job or {}).get("status", "")).strip().lower()
        if status in {"queued", "running"}:
            active_items.append((jid, job))
        else:
            completed_items.append((jid, job))

    def _job_epoch(item: Tuple[str, Dict[str, Any]]) -> float:
        _, job = item
        ts = str((job or {}).get("created_at") or "")
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    completed_items.sort(key=_job_epoch, reverse=True)
    keep_completed = max(0, MAX_MODEL_JOBS_HISTORY - len(active_items))
    keep_ids = {jid for jid, _ in active_items}
    keep_ids.update(jid for jid, _ in completed_items[:keep_completed])

    delete_ids = [jid for jid in MODEL_JOBS.keys() if jid not in keep_ids]
    for jid in delete_ids:
        MODEL_JOBS.pop(jid, None)


def _enqueue_training_job(
    machine_ids: Optional[List[str]],
    segment_id: Optional[str],
    auto_promote: bool,
    source: str,
) -> Dict[str, Any]:
    resolved_machine_ids: Optional[List[str]] = None
    if machine_ids is not None:
        resolved_machine_ids = []
        for raw_mid in machine_ids:
            resolved = _resolve_machine_id(raw_mid)
            if not resolved:
                raise HTTPException(status_code=400, detail=_machine_id_error_message(raw_mid, _machine_match_candidates(raw_mid)))
            if resolved not in resolved_machine_ids:
                resolved_machine_ids.append(resolved)
        if not resolved_machine_ids:
            resolved_machine_ids = None

    job_id = _new_job_id()
    MODEL_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": _now_iso(),
        "request": {
            "machine_ids": resolved_machine_ids,
            "segment_id": segment_id,
            "auto_promote": bool(auto_promote),
            "_source": source,
        },
    }
    asyncio.create_task(
        _run_training_job(
            job_id=job_id,
            machine_ids=resolved_machine_ids,
            segment_id=segment_id,
            auto_promote=bool(auto_promote),
        )
    )
    _prune_model_jobs()
    return {"job_id": job_id, "status": "queued", "source": source, "machine_ids": resolved_machine_ids}


def _registry_signature() -> Optional[str]:
    try:
        registry = load_registry()
    except Exception:
        return None

    tasks = registry.get("tasks") or {}
    signature_payload = {
        "updated_at": registry.get("updated_at"),
        "scrap_active": ((tasks.get("scrap_classifier") or {}).get("active") or {}),
        "sensor_active": ((tasks.get("sensor_forecaster") or {}).get("active") or {}),
    }
    try:
        return json.dumps(signature_payload, sort_keys=True, separators=(",", ":"))
    except Exception:
        return None


def _refresh_sequence_runtime(reason: str, force: bool = True) -> Dict[str, Any]:
    global AI_MODEL
    outcome = {
        "ok": False,
        "reason": reason,
        "refreshed_at": _now_iso(),
        "model_version": None,
        "model_family": None,
        "unavailable_reason": None,
    }
    try:
        if AI_MODEL is None:
            model_path = os.path.join(MODELS_DIR, "lstm_scrap_risk.h5")
            AI_MODEL = ai_engine.LSTMPredictor(model_path=model_path, models_dir=MODELS_DIR)
            ai_engine.AI_MODEL = AI_MODEL

        service = getattr(AI_MODEL, "service", None)
        if hasattr(AI_MODEL, "refresh"):
            AI_MODEL.refresh()
        elif service is not None and hasattr(service, "load"):
            service.load(force=force)

        service = getattr(AI_MODEL, "service", None)
        available = bool(service is not None and hasattr(service, "is_available") and service.is_available())
        outcome["ok"] = available
        if service is not None:
            meta = getattr(service, "_meta", {}) or {}
            outcome["model_version"] = meta.get("model_version")
            outcome["model_family"] = meta.get("model_family")
            if (not available) and hasattr(service, "unavailable_reason"):
                outcome["unavailable_reason"] = str(service.unavailable_reason())
    except Exception as exc:
        outcome["ok"] = False
        outcome["unavailable_reason"] = str(exc)
        logger.warning("Sequence runtime refresh failed (%s): %s", reason, exc)

    model_runtime_state["last_refresh_at"] = outcome["refreshed_at"]
    model_runtime_state["last_refresh_reason"] = reason
    model_runtime_state["last_refresh_ok"] = bool(outcome["ok"])
    model_runtime_state["last_error"] = outcome.get("unavailable_reason")
    sig = _registry_signature()
    if sig:
        model_runtime_state["last_registry_signature"] = sig
    return outcome


async def _model_registry_refresh_loop() -> None:
    while True:
        try:
            signature = _registry_signature()
            last_signature = model_runtime_state.get("last_registry_signature")
            if signature and signature != last_signature:
                refresh_result = _refresh_sequence_runtime("registry_change_detected", force=True)
                if refresh_result.get("ok"):
                    logger.info("Sequence model runtime refreshed after registry update.")
                else:
                    logger.warning(
                        "Sequence model refresh after registry update failed: %s",
                        refresh_result.get("unavailable_reason"),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Model refresh watcher error: %s", exc)
        await asyncio.sleep(MODEL_REFRESH_INTERVAL_SEC)


async def _auto_training_loop() -> None:
    while True:
        try:
            enabled = bool(auto_train_state.get("enabled"))
            interval = max(300.0, float(auto_train_state.get("interval_seconds") or 3600.0))
            now_epoch = time.time()
            last_run_epoch = auto_train_state.get("last_run_epoch")
            if not enabled:
                auto_train_state["next_run_at"] = None
                await asyncio.sleep(10.0)
                continue

            if last_run_epoch is None:
                last_run_epoch = now_epoch
                auto_train_state["last_run_epoch"] = last_run_epoch

            next_run_epoch = float(last_run_epoch) + interval
            auto_train_state["next_run_at"] = datetime.fromtimestamp(next_run_epoch, timezone.utc).isoformat()

            if now_epoch >= next_run_epoch:
                active_job = _active_training_job_id()
                if active_job:
                    auto_train_state["skipped_overlap_count"] = int(auto_train_state.get("skipped_overlap_count", 0)) + 1
                    auto_train_state["last_error"] = f"Skipped due to active training job: {active_job}"
                else:
                    queued = _enqueue_training_job(
                        machine_ids=auto_train_state.get("machine_ids"),
                        segment_id=auto_train_state.get("segment_id"),
                        auto_promote=bool(auto_train_state.get("auto_promote")),
                        source="auto_scheduler",
                    )
                    logger.info("Auto-train scheduler queued job %s.", queued.get("job_id"))
                    auto_train_state["last_run_at"] = _now_iso()
                    auto_train_state["last_run_epoch"] = now_epoch
                    auto_train_state["last_job_id"] = queued.get("job_id")
                    auto_train_state["last_error"] = None
                    auto_train_state["last_result"] = {"status": "queued", "job_id": queued.get("job_id")}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            auto_train_state["last_error"] = str(exc)
            logger.warning("Auto-train scheduler error: %s", exc)
        await asyncio.sleep(10.0)


async def _run_training_job(
    job_id: str,
    machine_ids: Optional[List[str]],
    segment_id: Optional[str],
    auto_promote: bool,
) -> None:
    request_meta = (MODEL_JOBS.get(job_id) or {}).get("request") or {}
    source = str(request_meta.get("_source") or "manual")
    MODEL_JOBS[job_id]["status"] = "running"
    MODEL_JOBS[job_id]["started_at"] = _now_iso()
    db = database.SessionLocal()
    try:
        result = await asyncio.to_thread(
            run_training_pipeline,
            db,
            machine_ids,
            segment_id,
            auto_promote,
        )
        MODEL_JOBS[job_id]["status"] = "completed" if result.get("ok") else "failed"
        if result.get("ok"):
            MODEL_JOBS[job_id]["model_refresh"] = _refresh_sequence_runtime(
                reason="training_job_completed",
                force=True,
            )
        MODEL_JOBS[job_id]["result"] = result
        if source == "auto_scheduler":
            auto_train_state["last_result"] = result
            auto_train_state["last_error"] = None
    except Exception as exc:
        MODEL_JOBS[job_id]["status"] = "failed"
        MODEL_JOBS[job_id]["error"] = str(exc)
        if source == "auto_scheduler":
            auto_train_state["last_error"] = str(exc)
        logger.exception("Model training job failed (%s): %s", job_id, exc)
    finally:
        MODEL_JOBS[job_id]["finished_at"] = _now_iso()
        db.close()


async def _ensure_ingestion_task_running(reason: str, force_restart: bool = False) -> Dict[str, Any]:
    task = getattr(app.state, "ingestion_task", None)
    restarted = False

    if force_restart and task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        task = None

    if not task or task.done():
        app.state.ingestion_task = asyncio.create_task(_ingestion_loop())
        restarted = True

    if restarted:
        connectivity_state["reconnect_attempts"] += 1
        connectivity_state["last_reconnect_at"] = _now_iso()
        connectivity_state["last_reconnect_reason"] = reason
        connectivity_state["last_reconnect_ok"] = True
        logger.info("Ingestion task restarted (%s).", reason)

    return {
        "restarted": restarted,
        "reason": reason,
        "ingestion_active": _ingestion_task_active(),
    }


def _cycle_to_payload(cycle: models.Cycle) -> Dict[str, Any]:
    prediction = cycle.prediction
    prediction_attrs = prediction.attributions if prediction and isinstance(prediction.attributions, dict) else {}
    shap_features = prediction_attrs.get("features", []) if isinstance(prediction_attrs.get("features", []), list) else []
    engine_version = prediction_attrs.get("_engine", "XGBoost-Hybrid")
    model_name = prediction_attrs.get("_model_name", "XGBoost-Hyper")
    model_version = prediction_attrs.get("_model_version")
    model_label = prediction_attrs.get("_model_label") or engine_version
    model_family = prediction_attrs.get("_model_family") or "legacy"
    segment_scope = prediction_attrs.get("_segment_scope") or "global"
    feature_spec_hash = prediction_attrs.get("_feature_spec_hash")
    xai_summary = prediction_attrs.get("_xai_summary")
    payload = {
        "cycle_id": cycle.cycle_id,
        "timestamp": cycle.timestamp.isoformat(),
        "telemetry": cycle.data,
        "predictions": {
            "scrap_probability": prediction.scrap_probability,
            "expected_scrap_rate": prediction_attrs.get("_expected_scrap_rate"),
            "confidence": prediction.confidence,
            "risk_level": prediction.risk_level,
            "primary_defect_risk": prediction.primary_defect_risk,
            "model_name": model_name,
            "model_version": model_version,
            "model_label": model_label,
            "model_family": model_family,
            "segment_scope": segment_scope,
            "feature_spec_hash": feature_spec_hash,
            "confidence_raw": prediction_attrs.get("_confidence_raw"),
            "confidence_empirical": prediction_attrs.get("_confidence_empirical"),
            "confidence_method": prediction_attrs.get("_confidence_method"),
            "maintenance_urgency": prediction_attrs.get("_maintenance", "LOW"),
            "engine_version": engine_version,
            "synergy_detected": prediction_attrs.get("_synergy", False),
            "anomaly_contribution": prediction_attrs.get("_anomaly", 0.0),
            "xai_summary": xai_summary,
        }
        if prediction
        else None,
        "shap_attributions": shap_features,
    }
    _enrich_telemetry_forecasts(payload)
    return payload


def check_file_connection(file_path: str) -> bool:
    """Verifies that the machine data stream file is connected and readable by FastAPI."""
    if not os.path.exists(file_path):
        return False
    try:
        # Test if the file is locked / readable
        mode = "rb" if file_path.lower().endswith((".xlsx", ".xls")) else "r"
        kwargs = {} if mode == "rb" else {"encoding": "utf-8"}
        with open(file_path, mode, **kwargs) as f:
            pass
        return True
    except (IOError, OSError):
        return False

def _normalize_row_timestamp(raw_ts: Any) -> Optional[str]:
    if raw_ts is None:
        return None
    if isinstance(raw_ts, datetime):
        return raw_ts.isoformat()
    if isinstance(raw_ts, pd.Timestamp):
        try:
            return raw_ts.to_pydatetime().isoformat()
        except Exception:
            return str(raw_ts)
    text = str(raw_ts).strip()
    return text if text else None


def _is_new_timestamp(ts: str, last_timestamp: Optional[str]) -> bool:
    if not last_timestamp:
        return True
    ts_dt = _safe_cycle_timestamp(ts)
    last_dt = _safe_cycle_timestamp(last_timestamp)
    if ts_dt and last_dt:
        return ts_dt > last_dt
    return ts > last_timestamp


def _machine_row_matches_target(row: Dict[str, Any], machine_id: Optional[str]) -> bool:
    if not machine_id or not isinstance(row, dict):
        return True

    row_machine = (
        row.get("machine_definition")
        or row.get("machine_def")
        or row.get("machine_id")
        or row.get("Machine_definition")
        or row.get("Machine_def")
        or row.get("Machine_id")
    )
    if row_machine is None or str(row_machine).strip() == "":
        return True

    target_code = _machine_numeric_code(machine_id)
    row_code = _machine_numeric_code(str(row_machine))
    if target_code and row_code:
        return target_code == row_code

    return _normalize_machine_query(row_machine) == _normalize_machine_query(machine_id)


def _parse_csv_since(
    file_path: str,
    last_timestamp: Optional[str],
    machine_id: Optional[str] = None,
    source_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    shot_map: Dict[str, Dict[str, Any]] = {}
    last_seen_ts = last_timestamp

    if not check_file_connection(file_path):
        logger.warning(f"File connection blocked or missing: {file_path}. Data stream degraded.")
        return {"shots": [], "last_timestamp": last_seen_ts}

    if not isinstance(source_state, dict):
        source_state = {}

    try:
        current_size = int(os.path.getsize(file_path))
        current_mtime = float(os.path.getmtime(file_path))
    except OSError:
        current_size = 0
        current_mtime = 0.0

    last_offset = int(source_state.get("offset") or 0)
    last_size = int(source_state.get("size") or 0)
    last_mtime = float(source_state.get("mtime") or 0.0)
    cached_fieldnames = source_state.get("fieldnames")
    cached_fieldnames = list(cached_fieldnames) if isinstance(cached_fieldnames, (list, tuple)) else None

    can_resume = (
        last_offset > 0
        and current_size >= last_offset
        and current_size >= last_size
        and current_mtime >= last_mtime
        and bool(cached_fieldnames)
    )
    start_offset = last_offset if can_resume else 0

    def _process_row(row: Dict[str, Any]) -> None:
        nonlocal last_seen_ts
        if not isinstance(row, dict):
            return
        if not _machine_row_matches_target(row, machine_id):
            return

        ts = _normalize_row_timestamp(
            row.get("timestamp") or row.get("Timestamp") or row.get("time")
        )
        if not ts:
            return

        if not _is_new_timestamp(ts, last_timestamp):
            return

        if ts not in shot_map:
            shot_map[ts] = {"_timestamp": ts}

        var_name = row.get("variable_name") or row.get("variable") or row.get("VariableName")
        if not var_name:
            return

        raw_value = row.get("value")
        try:
            value: Any = float(raw_value) if raw_value is not None else None
        except (ValueError, TypeError):
            value = raw_value

        shot_map[ts][var_name] = value
        if not last_seen_ts or ts > last_seen_ts:
            last_seen_ts = ts

    final_offset = 0
    final_fieldnames: Optional[List[str]] = cached_fieldnames
    try:
        with open(file_path, mode="r", encoding="utf-8", errors="ignore", newline="") as csv_file:
            if start_offset > 0:
                csv_file.seek(start_offset)
                reader = csv.DictReader(csv_file, fieldnames=cached_fieldnames)
            else:
                reader = csv.DictReader(csv_file)

            buffer: List[Dict[str, Any]] = []
            for row in reader:
                buffer.append(row)
                if len(buffer) >= CSV_RESUME_CHUNK_ROWS:
                    for chunk_row in buffer:
                        _process_row(chunk_row)
                    buffer.clear()

            for chunk_row in buffer:
                _process_row(chunk_row)

            final_offset = int(csv_file.tell())
            if isinstance(reader.fieldnames, list) and reader.fieldnames:
                final_fieldnames = list(reader.fieldnames)
    except Exception as e:
        logger.error(f"Failed to read CSV connection {file_path}: {e}")
        source_state["offset"] = 0
        source_state["size"] = current_size
        source_state["mtime"] = current_mtime

    try:
        source_state["offset"] = int(final_offset)
        source_state["size"] = int(os.path.getsize(file_path))
        source_state["mtime"] = float(os.path.getmtime(file_path))
        if final_fieldnames:
            source_state["fieldnames"] = final_fieldnames
    except OSError:
        pass

    shots = sorted(shot_map.values(), key=lambda shot: shot["_timestamp"])
    return {"shots": shots, "last_timestamp": last_seen_ts}


def _parse_excel_since(
    file_path: str,
    last_timestamp: Optional[str],
    machine_id: Optional[str] = None,
    source_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    shot_map: Dict[str, Dict[str, Any]] = {}
    last_seen_ts = last_timestamp

    if not check_file_connection(file_path):
        logger.warning(f"File connection blocked or missing: {file_path}. Data stream degraded.")
        return {"shots": [], "last_timestamp": last_seen_ts}

    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        logger.error(f"Failed to read Excel connection {file_path}: {e}")
        return {"shots": [], "last_timestamp": last_seen_ts}

    if df.empty:
        return {"shots": [], "last_timestamp": last_seen_ts}

    columns_lower = {str(col).strip().lower(): col for col in df.columns}
    ts_col = columns_lower.get("timestamp")
    var_col = columns_lower.get("variable_name")
    val_col = columns_lower.get("value")
    machine_col = (
        columns_lower.get("machine_definition")
        or columns_lower.get("machine_def")
        or columns_lower.get("machine_id")
    )

    if ts_col is not None and var_col is not None and val_col is not None:
        for _, row in df.iterrows():
            if machine_col is not None:
                row_machine = row.get(machine_col)
                if (
                    row_machine is not None
                    and str(row_machine).strip() != ""
                    and not _machine_row_matches_target({"machine_definition": row_machine}, machine_id)
                ):
                    continue

            ts = _normalize_row_timestamp(row.get(ts_col))
            if not ts:
                continue
            if not _is_new_timestamp(ts, last_timestamp):
                continue
            if ts not in shot_map:
                shot_map[ts] = {"_timestamp": ts}

            var_name = row.get(var_col)
            if var_name is None or str(var_name).strip() == "":
                continue
            raw_value = row.get(val_col)
            try:
                value: Any = float(raw_value) if raw_value is not None else None
            except (ValueError, TypeError):
                value = raw_value
            shot_map[ts][str(var_name)] = value
            if not last_seen_ts or _is_new_timestamp(ts, last_seen_ts):
                last_seen_ts = ts
    else:
        # Wide fallback: use timestamp + numeric columns as variables.
        if ts_col is None:
            logger.warning("Excel file %s missing timestamp column; skipping.", file_path)
            return {"shots": [], "last_timestamp": last_seen_ts}

        meta_cols = {
            "device_name",
            "machine_definition",
            "variable_attribute",
            "device",
            "machine_def",
            "year",
            "month",
            "date",
        }
        for _, row in df.iterrows():
            ts = _normalize_row_timestamp(row.get(ts_col))
            if not ts:
                continue
            if not _is_new_timestamp(ts, last_timestamp):
                continue
            if ts not in shot_map:
                shot_map[ts] = {"_timestamp": ts}

            for col in df.columns:
                col_key = str(col).strip()
                if col_key.lower() in meta_cols or col_key.lower() == "timestamp":
                    continue
                raw_value = row.get(col)
                try:
                    value: Any = float(raw_value) if raw_value is not None else None
                except (ValueError, TypeError):
                    continue
                shot_map[ts][col_key] = value
            if not last_seen_ts or _is_new_timestamp(ts, last_seen_ts):
                last_seen_ts = ts

    shots = sorted(shot_map.values(), key=lambda shot: shot["_timestamp"])
    return {"shots": shots, "last_timestamp": last_seen_ts}


def _parse_machine_data_since(
    file_path: str,
    last_timestamp: Optional[str],
    machine_id: Optional[str] = None,
    source_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in {".xlsx", ".xls"}:
        return _parse_excel_since(
            file_path,
            last_timestamp,
            machine_id=machine_id,
            source_state=source_state,
        )
    return _parse_csv_since(
        file_path,
        last_timestamp,
        machine_id=machine_id,
        source_state=source_state,
    )


def _safe_cycle_timestamp(timestamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _build_recent_sensor_history(cycles: List[models.Cycle]) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    timestamps: List[pd.Timestamp] = []

    for cycle in cycles:
        telemetry = cycle.data or {}
        row = telemetry_to_sensor_row(telemetry)
        if not row:
            continue
        rows.append(row)
        timestamps.append(pd.Timestamp(cycle.timestamp))

    if not rows:
        return pd.DataFrame()

    history = pd.DataFrame(rows)
    history = history.ffill().fillna(0.0)
    if len(timestamps) == len(history):
        history.index = pd.DatetimeIndex(timestamps)
    return history


def _build_lstm_sequence_from_cycles(cycles: List[models.Cycle], max_steps: int = 60) -> List[Dict[str, float]]:
    if not cycles:
        return []
    ordered = sorted(cycles, key=lambda c: (c.timestamp, c.id))
    rows: List[Dict[str, float]] = []
    for cycle in ordered[-max_steps:]:
        telemetry = cycle.data or {}
        raw_row = telemetry_to_sensor_row(telemetry)
        if not raw_row:
            continue
        row: Dict[str, float] = {}
        for key, value in raw_row.items():
            numeric = _to_float(value)
            if numeric is None:
                continue
            row[str(key)] = float(numeric)
        if row:
            rows.append(row)
    return rows


@with_reconnect(max_retries=3)
def _persist_cycles(db: Session, machine_id: str, analyzed_cycles: List[Dict[str, Any]]) -> int:
    """Optimized batch persistence with duplicate detection."""
    if not analyzed_cycles:
        return 0

    inserted = 0
    # Collect all timestamps to check for existing records in one go
    timestamps = [
        _safe_cycle_timestamp(c.get("timestamp")) 
        for c in analyzed_cycles 
        if _safe_cycle_timestamp(c.get("timestamp"))
    ]
    
    if not timestamps:
        return 0

    # Find existing cycles to avoid IntegrityErrors via application-level filter
    existing_ts = {
        row[0] for row in db.query(models.Cycle.timestamp)
        .filter(models.Cycle.machine_id == machine_id)
        .filter(models.Cycle.timestamp.in_(timestamps))
        .all()
    }

    new_cycles = []
    
    for cycle in analyzed_cycles:
        ts = _safe_cycle_timestamp(cycle.get("timestamp"))
        if not ts or ts in existing_ts:
            continue

        prediction_data = cycle.get("predictions") or {}
        
        # Build relationship in memory to avoid per-row flushes
        db_cycle = models.Cycle(
            machine_id=machine_id,
            cycle_id=str(cycle.get("cycle_id", "")),
            timestamp=ts,
            data=cycle.get("telemetry", {}),
        )
        
        db_pred = models.Prediction(
            scrap_probability=prediction_data.get("scrap_probability", 0.0),
            confidence=prediction_data.get("confidence", 0.0),
            risk_level=prediction_data.get("risk_level", "NORMAL"),
            primary_defect_risk=prediction_data.get("primary_defect_risk", "None"),
            attributions={
                "features": cycle.get("shap_attributions", []),
                "_engine": prediction_data.get("engine_version", "XGBoost-Hybrid"),
                "_synergy": prediction_data.get("synergy_detected", False),
                "_maintenance": prediction_data.get("maintenance_urgency", "LOW"),
                "_anomaly": prediction_data.get("unsupervised_anomaly_contrib", 0.0),
                "_model_name": prediction_data.get("model_name"),
                "_model_version": prediction_data.get("model_version"),
                "_model_label": prediction_data.get("model_label"),
                "_model_family": prediction_data.get("model_family"),
                "_segment_scope": prediction_data.get("segment_scope"),
                "_feature_spec_hash": prediction_data.get("feature_spec_hash"),
                "_xai_summary": prediction_data.get("xai_summary"),
                "_confidence_raw": prediction_data.get("confidence_raw"),
                "_confidence_empirical": prediction_data.get("confidence_empirical"),
                "_confidence_method": prediction_data.get("confidence_method"),
                "_expected_scrap_rate": prediction_data.get("expected_scrap_rate"),
            },
        )
        db_cycle.prediction = db_pred
        new_cycles.append(db_cycle)

    if new_cycles:
        db.add_all(new_cycles)
        db.commit() # Single commit for the whole batch
        inserted = len(new_cycles)
    
    return inserted


@with_reconnect(max_retries=2)
def _prune_machine_history(db: Session, machine_id: str) -> int:
    total_cycles = (
        db.query(models.Cycle.id)
        .filter(models.Cycle.machine_id == machine_id)
        .count()
    )
    if total_cycles <= MAX_CYCLES_PER_MACHINE:
        return 0

    to_delete = total_cycles - MAX_CYCLES_PER_MACHINE
    deleted = 0

    while deleted < to_delete:
        batch_size = min(PRUNE_BATCH_SIZE, to_delete - deleted)
        stale_ids = [
            row[0]
            for row in db.query(models.Cycle.id)
            .filter(models.Cycle.machine_id == machine_id)
            .order_by(models.Cycle.timestamp.asc(), models.Cycle.id.asc())
            .limit(batch_size)
            .all()
        ]

        if not stale_ids:
            break

        db.query(models.Prediction).filter(models.Prediction.cycle_id.in_(stale_ids)).delete(
            synchronize_session=False
        )
        db.query(models.Cycle).filter(models.Cycle.id.in_(stale_ids)).delete(synchronize_session=False)
        db.commit()
        deleted += len(stale_ids)

    return deleted


async def _ingestion_loop() -> None:
    """Continuous background loop for data synchronization."""
    while True:
        try:
            logger.info("Starting background ingestion cycle...")
            # Use to_thread for the heavy CPU/IO processing
            await asyncio.to_thread(_ingest_machine_data)
        except asyncio.CancelledError:
            logger.info("Ingestion loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Ingestion loop error: {e}")
        
        await asyncio.sleep(10) # Process every 10 seconds


async def _connectivity_watchdog_loop() -> None:
    while True:
        try:
            db_ok = database.check_db_connection()
            csv_state = _csv_connectivity_snapshot()
            if db_ok and csv_state.get("exists") and not _ingestion_task_active():
                await _ensure_ingestion_task_running("watchdog_auto_reconnect")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Connectivity watchdog error: %s", exc, exc_info=True)
        await asyncio.sleep(WATCHDOG_INTERVAL_SEC)

def _ingest_machine_data() -> None:
    _set_ingestion_state(
        status="running",
        started_at=_now_iso(),
        finished_at=None,
        error=None
    )
    
    db = database.SessionLocal()
    try:
        machine_failures = 0
        for machine_id in MACHINE_IDS:
            try:
                _set_machine_state(
                    machine_id,
                    status="processing",
                    error=None,
                    inserted=0,
                    pruned=0,
                    source_rows=0,
                )
                context = _get_machine_context(machine_id)
                tracker = context["drift_tracker"]

                stats = (
                    db.query(models.MachineStats)
                    .filter(models.MachineStats.machine_id == machine_id)
                    .first()
                )
                file_path = _resolve_machine_data_file(machine_id)

                if not file_path:
                    _set_machine_state(
                        machine_id,
                        status="disconnected",
                        error=f"Machine data stream not found for {machine_id} in {DATA_DIR}. Supported extensions: {', '.join(MACHINE_FILE_EXTENSIONS)}",
                    )
                    logger.warning(f"[{machine_id}] Data stream file missing -> Retrying connection next heartbeat.")
                    continue

                # Explicitly 'ckeck to aree connect'
                if not check_file_connection(file_path):
                    _set_machine_state(machine_id, status="disconnected", error=f"Machine data stream is disconnected or missing: {file_path}. Will reconnect automatically.")
                    logger.warning(f"[{machine_id}] Data Connection Lost -> Retrying connection next heartbeat.")
                    continue

                last_ts = stats.last_loaded_timestamp if stats else None
                source_state = context["source_offsets"].setdefault(file_path, {})
                parse_result = _parse_machine_data_since(
                    file_path,
                    last_ts,
                    machine_id=machine_id,
                    source_state=source_state,
                )
                new_shots = parse_result["shots"]
                new_last_ts = parse_result["last_timestamp"]

                _set_machine_state(machine_id, source_rows=len(new_shots))

                analyzed = []
                inserted_count = 0
                pruned_count = 0

                if not new_shots:
                    if stats and stats.baselines:
                        tracker.baselines = stats.baselines
                    pruned_count = _prune_machine_history(db, machine_id)
                else:
                    if not last_ts and len(new_shots) > INITIAL_LOAD_CYCLES:
                        calibration_source = new_shots[: min(300, len(new_shots))]
                        tracker.calibrate(calibration_source)
                        shots_to_process = new_shots[-INITIAL_LOAD_CYCLES:]
                    else:
                        if stats and stats.baselines:
                            tracker.baselines = stats.baselines
                        shots_to_process = new_shots

                    analyzed = ai_engine.analyze_shot_sequence(
                        shots_to_process,
                        tracker,
                    )
                    
                    # 🚀 Online Training: Add high-stability cycles to refinement window
                    for cycle_data in analyzed:
                        pred = cycle_data.get("predictions", {})
                        if pred.get("risk_level") == "NORMAL" and pred.get("confidence", 0) > 0.85:
                            # Reconstruct raw-ish shot for baseline training
                            shot_tele = cycle_data.get("telemetry", {})
                            training_shot = {}
                            for csv_name, fe_key in ai_engine.VAR_KEY_MAP.items():
                                if fe_key in shot_tele:
                                    training_shot[csv_name] = shot_tele[fe_key].get("value")
                            tracker.good_cycles_window.append(training_shot)
                    
                    if len(tracker.good_cycles_window) >= 150:
                        logger.info(f"{machine_id}: Triggering adaptive baseline refinement (Training Mode).")
                        tracker.refine_baselines()

                    analyzed = _calibrate_predictions(analyzed)
                    
                    inserted_count = _persist_cycles(db, machine_id, analyzed)
                    pruned_count = _prune_machine_history(db, machine_id)

                # Save stats and dashboard snapshot
                if not stats:
                    stats = models.MachineStats(machine_id=machine_id)
                    db.add(stats)
                
                stats.baselines = tracker.baselines
                if new_last_ts:
                    stats.last_loaded_timestamp = new_last_ts
                
                # Update real-time metrics for dashboard
                stats_updated = False
                if analyzed:
                    latest = analyzed[-1]
                    pred = latest.get("predictions")
                    tele = latest.get("telemetry", {})
                    
                    status = "ok"
                    oee = 0
                    if pred:
                        if pred.get("risk_level") in {"CERTAIN", "VERY_HIGH"}:
                            status = "crit"
                        elif pred.get("risk_level") == "HIGH":
                            status = "warn"
                        # OEE: Use confidence-weighted quality estimate.
                        # Pure scrap_probability alone gives unrealistically low OEE.
                        scrap_p = float(pred.get("scrap_probability", 0) or 0)
                        confidence = float(pred.get("confidence", 0.75) or 0.75)
                        # Weighted risk: only penalise OEE for high-confidence high-risk situations
                        effective_risk = scrap_p * confidence
                        oee = max(0, min(100, int(100 * (1.0 - effective_risk))))
                    
                    # Abnormal params from SHAP attributions
                    abnormal = []
                    attrs = latest.get("shap_attributions", [])
                    sorted_attr = sorted(attrs, key=lambda x: abs(x.get("contribution", 0)), reverse=True)
                    top_risks = [a for a in sorted_attr if a.get("contribution", 0) > 0.05][:2]
                    for risk in top_risks:
                        label = risk.get("feature", "unknown").replace('_', ' ').title()
                        abnormal.append(label)

                    stats.last_status = status
                    stats.last_oee = oee
                    stats.last_temp = tele.get("temp_z2", {}).get("value") or tele.get("temp_z1", {}).get("value", 230)
                    stats.last_cushion = tele.get("cushion", {}).get("value", 0.0)
                    stats.last_cycles_count = int(latest["cycle_id"]) if str(latest["cycle_id"]).isdigit() else 0
                    stats.abnormal_params = abnormal
                    stats.maintenance_urgency = pred.get("maintenance_urgency", "LOW")
                    stats_updated = True
                
                # Fallback: if no new data, push latest from DB to snapshot if empty or stale
                if not stats_updated or (stats.last_oee == 0 and stats.last_status == "ok"):
                    last_cycle = (
                        db.query(models.Cycle)
                        .options(joinedload(models.Cycle.prediction))
                        .filter(models.Cycle.machine_id == machine_id)
                        .order_by(models.Cycle.timestamp.desc())
                        .first()
                    )
                    if last_cycle:
                        pred = last_cycle.prediction
                        tele = last_cycle.data or {}
                        
                        if pred:
                            if pred.risk_level in {"CERTAIN", "VERY_HIGH"}:
                                stats.last_status = "crit"
                            elif pred.risk_level == "HIGH":
                                stats.last_status = "warn"
                            scrap_p = float(pred.scrap_probability or 0)
                            confidence = float(pred.confidence or 0.75)
                            effective_risk = scrap_p * confidence
                            stats.last_oee = max(0, min(100, int(100 * (1.0 - effective_risk))))
                            
                            if pred.attributions:
                                feature_attrs = pred.attributions.get("features", []) if isinstance(pred.attributions, dict) else []
                                sorted_attr = sorted(feature_attrs, key=lambda x: abs(x.get("contribution", 0)), reverse=True)
                                top_risks = [a for a in sorted_attr if a.get("contribution", 0) > 0.05][:2]
                                stats.abnormal_params = [r.get("feature", "unknown").replace('_', ' ').title() for r in top_risks]

                        stats.last_temp = tele.get("temp_z2", {}).get("value") or tele.get("temp_z1", {}).get("value", 230)
                        stats.last_cushion = tele.get("cushion", {}).get("value", 0.0)
                        stats.last_cycles_count = int(last_cycle.cycle_id) if str(last_cycle.cycle_id).isdigit() else 0
                
                db.commit()
                
                _set_machine_state(machine_id, status="ready", inserted=inserted_count, pruned=pruned_count)
                logger.info(f"{machine_id}: Ingested {inserted_count} cycles.")

            except Exception as e:
                db.rollback()
                machine_failures += 1
                logger.error(f"{machine_id} ingestion failed: {e}", exc_info=True)
                _set_machine_state(machine_id, status="failed", error=e)

        _set_ingestion_state(status="ready" if machine_failures == 0 else "degraded", finished_at=_now_iso())
        logger.info(f"Ingestion completed. Failures: {machine_failures}")

    except Exception as e:
        logger.critical(f"Critical ingestion loop failure: {e}", exc_info=True)
        _set_ingestion_state(status="failed", finished_at=_now_iso(), error=e)
    finally:
        db.close()


@app.get("/", response_model=Dict[str, Any])
async def root():
    return {
        "ok": True,
        "backend": "fastapi",
        "message": "Smart Factory Brain backend is running.",
        "endpoints": [
            "/api/health",
            "/api/ai/metrics",
            "/api/ai/predict-batch",
            "/api/ai/explain-prediction",
            "/api/ai/lstm/predict",
            "/api/admin/models",
            "/api/admin/models/auto-train",
            "/api/admin/models/auto-train/run-now",
            "/api/machines",
            "/api/machines/{machine_id}/cycles",
            "/ws",
        ],
    }


@app.get("/api/health", response_model=SystemStatus)
async def health(auto_reconnect: bool = True):
    """
    Detailed connectivity and health check for all system components.
    """
    db_start = time.time()
    db_ok = database.check_db_connection()
    db_ping_ms = round((time.time() - db_start) * 1000, 2)
    csv_state = _csv_connectivity_snapshot()
    data_dir_ok = bool(csv_state.get("exists"))
    ingestion_active = _ingestion_task_active()
    reconnect_result = None

    if auto_reconnect and db_ok and data_dir_ok and not ingestion_active:
        reconnect_result = await _ensure_ingestion_task_running("health_auto_reconnect")
        ingestion_active = _ingestion_task_active()

    is_healthy = db_ok and data_dir_ok and ingestion_active and (ingestion_state.get("status") != "failed")
    
    return {
        "ok": is_healthy,
        "backend": "fastapi",
        "db_status": "connected" if db_ok else "disconnected",
        "data_status": "accessible" if data_dir_ok else "missing",
        "ingestion_status": ingestion_state.get("status", "unknown"),
        "uptime_seconds": time.time() - STARTUP_TIME,
        "details": {
            "ingestion_active": ingestion_active,
            "machine_count": len(MACHINE_IDS),
            "engine": "LSTM-Hyper v6.0.0-PRO",
            "db_ping_ms": db_ping_ms,
            "data_connectivity": csv_state,
            "auto_reconnect": reconnect_result,
            "reconnect_state": connectivity_state,
            "model_runtime": model_runtime_state,
            "auto_train": auto_train_state,
        }
    }


def _ensure_sequence_runtime() -> Any:
    global AI_MODEL
    if AI_MODEL is None:
        model_path = os.path.join(MODELS_DIR, "lstm_scrap_risk.h5")
        AI_MODEL = ai_engine.LSTMPredictor(model_path=model_path, models_dir=MODELS_DIR)
        ai_engine.AI_MODEL = AI_MODEL

    if AI_MODEL is None or not hasattr(AI_MODEL, "predict_batch"):
        raise HTTPException(status_code=503, detail="LSTM model runtime is not loaded.")

    service = getattr(AI_MODEL, "service", None)
    if service is None or not hasattr(service, "is_available"):
        raise HTTPException(status_code=503, detail="LSTM model runtime is not loaded.")

    if not service.is_available() and not service.load():
        reason = service.unavailable_reason() if hasattr(service, "unavailable_reason") else "No additional details available."
        raise HTTPException(status_code=503, detail=f"LSTM model runtime is not loaded. {reason}")

    return AI_MODEL


@app.post("/api/ai/predict-batch")
async def predict_batch(payload: PredictBatchRequest):
    runtime = _ensure_sequence_runtime()
    try:
        result = runtime.predict_batch(
            machine_id=payload.machine_id,
            sequence=payload.sequence,
            horizon_cycles=payload.horizon_cycles,
            part_number=payload.part_number,
            top_k=8,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LSTM inference failed: {exc}")

    return {"ok": True, **result}


@app.post("/api/ai/explain-prediction")
async def explain_prediction(payload: ExplainPredictionRequest):
    runtime = _ensure_sequence_runtime()
    try:
        result = runtime.explain_prediction(
            machine_id=payload.machine_id,
            sequence=payload.sequence,
            horizon_cycles=payload.horizon_cycles,
            part_number=payload.part_number,
            top_k=payload.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LSTM explain failed: {exc}")

    return {"ok": True, **result}


@app.post("/api/ai/lstm/predict")
async def predict_lstm_sequence(payload: ModelInputSequence):
    horizon_cycles = _horizon_minutes_to_cycles(int(payload.horizon_minutes))
    runtime = None
    lstm_unavailable_detail: Optional[str] = None
    try:
        runtime = _ensure_sequence_runtime()
    except HTTPException as exc:
        if int(exc.status_code) == 503:
            lstm_unavailable_detail = str(exc.detail)
        else:
            raise

    if runtime is None:
        fallback_probability = 0.5
        try:
            if AI_MODEL is not None and hasattr(AI_MODEL, "predict"):
                fallback_probability = _clamp(
                    float(
                        AI_MODEL.predict(
                            sequence=payload.sequence,
                            machine_id=payload.machine_id,
                            horizon_cycles=horizon_cycles,
                            part_number=None,
                        )
                    ),
                    0.0,
                    1.0,
                )
        except Exception:
            fallback_probability = 0.5

        return {
            "ok": False,
            "available": False,
            "detail": lstm_unavailable_detail or "LSTM model runtime is not loaded.",
            "machine_id": payload.machine_id,
            "horizon_minutes": int(payload.horizon_minutes),
            "sequence_length": len(payload.sequence),
            "scrap_probability": round(fallback_probability, 4),
            "expected_scrap_rate": None,
            "risk_level": (
                "VERY_HIGH" if fallback_probability >= 0.9
                else "HIGH" if fallback_probability >= 0.7
                else "ELEVATED" if fallback_probability >= 0.4
                else "NORMAL"
            ),
            "engine_version": "LSTM-Hyper v7.0.0",
            "model_name": "UNAVAILABLE",
            "model_label": "LSTM runtime unavailable (fallback)",
        }

    try:
        result = runtime.predict_batch(
            machine_id=payload.machine_id,
            sequence=payload.sequence,
            horizon_cycles=horizon_cycles,
            part_number=None,
            top_k=8,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LSTM inference failed: {exc}")

    probability = _clamp(float(result.get("scrap_probability", 0.0)), 0.0, 1.0)
    return {
        "ok": True,
        "machine_id": payload.machine_id,
        "horizon_minutes": int(payload.horizon_minutes),
        "sequence_length": len(payload.sequence),
        "scrap_probability": round(probability, 4),
        "expected_scrap_rate": result.get("expected_scrap_rate"),
        "risk_level": result.get("risk_level", "NORMAL"),
        "engine_version": "LSTM-Hyper v7.0.0",
        "model_name": result.get("model_name", "LSTM-Hyper"),
        "model_label": result.get("model_label", "LSTM-Scrap-AI-Core (TensorFlow 2.15+)"),
    }


@app.get("/api/ai/metrics")
async def get_ai_metrics(
    machine_id: Optional[str] = None,
    window_cycles: int = 600,
    risk_threshold: float = 0.60,
    lead_window_cycles: int = 30,
    db: Session = Depends(get_db),
):
    """
    AI-centric operational metrics for predictive quality.
    """
    clamped_window = max(120, min(window_cycles, 5000))
    clamped_threshold = _clamp(float(risk_threshold), 0.05, 0.95)
    clamped_lead_window = max(3, min(lead_window_cycles, 240))

    selected_machine_ids: List[str]
    if machine_id:
        selected_machine_ids = [_require_machine_id(machine_id)]
    else:
        selected_machine_ids = list(MACHINE_IDS)

    per_machine_raw = [
        _compute_machine_ai_kpis(
            db=db,
            machine_id=mid,
            window_cycles=clamped_window,
            risk_threshold=clamped_threshold,
            lead_window_cycles=clamped_lead_window,
        )
        for mid in selected_machine_ids
    ]

    total_tp = sum(item.get("tp", 0) for item in per_machine_raw)
    total_fp = sum(item.get("fp", 0) for item in per_machine_raw)
    total_tn = sum(item.get("tn", 0) for item in per_machine_raw)
    total_fn = sum(item.get("fn", 0) for item in per_machine_raw)
    total_labeled = sum(item.get("labeled_samples", 0) for item in per_machine_raw)
    total_observed_events = sum(item.get("observed_scrap_events", 0) for item in per_machine_raw)
    total_missed_no_lead = sum(item.get("missed_events_no_lead_alert", 0) for item in per_machine_raw)
    total_brier_sum = sum(item.get("_brier_sum", 0.0) for item in per_machine_raw)
    total_brier_n = sum(item.get("_brier_n", 0) for item in per_machine_raw)
    total_conf_sum = sum(item.get("_confidence_sum", 0.0) for item in per_machine_raw)
    total_conf_n = sum(item.get("_confidence_n", 0) for item in per_machine_raw)
    total_lead_events = sum(item.get("lead_time_events", 0) for item in per_machine_raw)
    weighted_lead_sum = sum(
        float(item.get("lead_time_minutes_mean", 0.0)) * int(item.get("lead_time_events", 0))
        for item in per_machine_raw
    )

    fleet_precision = _safe_div(total_tp, total_tp + total_fp)
    fleet_recall = _safe_div(total_tp, total_tp + total_fn)
    fleet_f1 = _safe_div(2.0 * fleet_precision * fleet_recall, fleet_precision + fleet_recall) if (fleet_precision + fleet_recall) else 0.0
    fleet_accuracy = _safe_div(total_tp + total_tn, total_labeled)
    fleet_false_alarm_rate = _safe_div(total_fp, total_labeled)
    fleet_missed_scrap_rate = _safe_div(total_fn, total_tp + total_fn)
    fleet_brier = _safe_div(total_brier_sum, total_brier_n)
    fleet_avg_confidence = _safe_div(total_conf_sum, total_conf_n)
    fleet_lead_minutes = _safe_div(weighted_lead_sum, total_lead_events)
    lead_coverage = _safe_div(total_observed_events - total_missed_no_lead, total_observed_events)

    per_machine: List[Dict[str, Any]] = []
    for item in per_machine_raw:
        clean_item = {k: v for k, v in item.items() if not str(k).startswith("_")}
        per_machine.append(clean_item)

    return {
        "generated_at": _now_iso(),
        "machine_scope": selected_machine_ids,
        "window_cycles": clamped_window,
        "risk_threshold": round(clamped_threshold, 4),
        "lead_window_cycles": clamped_lead_window,
        "fleet_metrics": {
            "labeled_samples": int(total_labeled),
            "observed_scrap_events": int(total_observed_events),
            "tp": int(total_tp),
            "fp": int(total_fp),
            "tn": int(total_tn),
            "fn": int(total_fn),
            "precision": round(fleet_precision, 4),
            "recall": round(fleet_recall, 4),
            "f1": round(fleet_f1, 4),
            "accuracy": round(fleet_accuracy, 4),
            "false_alarm_rate": round(fleet_false_alarm_rate, 4),
            "missed_scrap_rate": round(fleet_missed_scrap_rate, 4),
            "lead_alert_coverage": round(lead_coverage, 4),
            "lead_time_minutes_mean": round(fleet_lead_minutes, 4),
            "brier_score": round(fleet_brier, 6),
            "avg_confidence": round(fleet_avg_confidence, 4),
        },
        "per_machine": per_machine,
    }


@app.post("/api/admin/reconnect")
async def manual_reconnect():
    """
    Forces a reconnection to all backend services.
    """
    logger.info("Manual reconnection triggered.")
    
    # 1. Check DB
    db_ok = database.check_db_connection()
    if not db_ok:
        logger.warning("DB disconnected. Attempting engine re-init...")
        # engine is already globally created, SQLAlchemy pool_pre_ping=True helps recovery
    
    reconnect_result = await _ensure_ingestion_task_running("manual_reconnect", force_restart=True)
    return {
        "ok": bool(db_ok and reconnect_result.get("ingestion_active")),
        "message": "Reconnection sequence completed.",
        "db_connected": db_ok,
        "ingestion": reconnect_result,
        "reconnect_state": connectivity_state,
    }


@app.get("/api/admin/models")
async def admin_models():
    registry = load_registry()
    tasks = registry.get("tasks") or {}
    models_map = registry.get("models") or {}
    coverage: Dict[str, int] = {}
    for task_name, task_info in tasks.items():
        coverage[task_name] = len((task_info or {}).get("active") or {})
    return {
        "ok": True,
        "generated_at": _now_iso(),
        "registry_updated_at": registry.get("updated_at"),
        "coverage": coverage,
        "active": {k: (v or {}).get("active", {}) for k, v in tasks.items()},
        "models_count": len(models_map),
        "models": models_map,
        "auto_train": auto_train_state,
        "active_training_job_id": _active_training_job_id(),
        "model_jobs_retention_limit": MAX_MODEL_JOBS_HISTORY,
        "model_jobs_count": len(MODEL_JOBS),
    }


@app.post("/api/admin/models/train")
async def admin_models_train(req: ModelTrainRequest):
    active_job = _active_training_job_id()
    if active_job:
        raise HTTPException(status_code=409, detail=f"Training job already active: {active_job}")
    queued = _enqueue_training_job(
        machine_ids=req.machine_ids,
        segment_id=req.segment_id,
        auto_promote=bool(req.auto_promote),
        source="manual_api",
    )
    return {"ok": True, **queued}


@app.get("/api/admin/models/jobs/{job_id}")
async def admin_model_job_status(job_id: str):
    job = MODEL_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"ok": True, **job}


@app.get("/api/admin/models/auto-train")
async def admin_models_auto_train_status():
    return {
        "ok": True,
        "auto_train": auto_train_state,
        "active_job_id": _active_training_job_id(),
        "model_jobs_retention_limit": MAX_MODEL_JOBS_HISTORY,
        "model_jobs_count": len(MODEL_JOBS),
    }


@app.post("/api/admin/models/auto-train/start")
async def admin_models_auto_train_start(req: AutoTrainConfigRequest):
    if req.interval_seconds is not None:
        auto_train_state["interval_seconds"] = int(max(300, min(req.interval_seconds, 604800)))
    if req.machine_ids is not None:
        resolved: List[str] = []
        for raw_mid in req.machine_ids:
            mid = _resolve_machine_id(raw_mid)
            if not mid:
                raise HTTPException(status_code=400, detail=_machine_id_error_message(raw_mid, _machine_match_candidates(raw_mid)))
            if mid not in resolved:
                resolved.append(mid)
        auto_train_state["machine_ids"] = resolved or None
    if req.segment_id is not None:
        auto_train_state["segment_id"] = str(req.segment_id).strip() or None
    if req.auto_promote is not None:
        auto_train_state["auto_promote"] = bool(req.auto_promote)
    auto_train_state["enabled"] = True if req.enabled is None else bool(req.enabled)
    if auto_train_state.get("last_run_epoch") is None:
        auto_train_state["last_run_epoch"] = time.time()
    queued = None
    if bool(req.run_immediately):
        active_job = _active_training_job_id()
        if active_job:
            raise HTTPException(status_code=409, detail=f"Training job already active: {active_job}")
        queued = _enqueue_training_job(
            machine_ids=auto_train_state.get("machine_ids"),
            segment_id=auto_train_state.get("segment_id"),
            auto_promote=bool(auto_train_state.get("auto_promote")),
            source="auto_train_start_run_now",
        )
        auto_train_state["last_run_at"] = _now_iso()
        auto_train_state["last_run_epoch"] = time.time()
        auto_train_state["last_job_id"] = queued.get("job_id")
        auto_train_state["last_error"] = None
        auto_train_state["last_result"] = {"status": "queued", "job_id": queued.get("job_id")}
    return {"ok": True, "auto_train": auto_train_state, "queued_job": queued}


@app.post("/api/admin/models/auto-train/stop")
async def admin_models_auto_train_stop():
    auto_train_state["enabled"] = False
    auto_train_state["next_run_at"] = None
    return {"ok": True, "auto_train": auto_train_state}


@app.post("/api/admin/models/auto-train/run-now")
async def admin_models_auto_train_run_now():
    active_job = _active_training_job_id()
    if active_job:
        raise HTTPException(status_code=409, detail=f"Training job already active: {active_job}")
    queued = _enqueue_training_job(
        machine_ids=auto_train_state.get("machine_ids"),
        segment_id=auto_train_state.get("segment_id"),
        auto_promote=bool(auto_train_state.get("auto_promote")),
        source="auto_train_run_now",
    )
    auto_train_state["last_run_at"] = _now_iso()
    auto_train_state["last_run_epoch"] = time.time()
    auto_train_state["last_job_id"] = queued.get("job_id")
    auto_train_state["last_error"] = None
    auto_train_state["last_result"] = {"status": "queued", "job_id": queued.get("job_id")}
    return {"ok": True, "queued_job": queued, "auto_train": auto_train_state}


@app.get("/api/admin/models/benchmark")
async def admin_models_benchmark():
    data = load_latest_benchmark()
    return data


@app.post("/api/admin/models/promote")
async def admin_models_promote(req: ModelPromoteRequest):
    task = _norm_task_name(req.task)
    registry = load_registry()
    result = promote_model(
        registry=registry,
        task=task,
        model_id=req.model_id,
        machine_id=req.machine_id,
        part_number=req.part_number,
    )
    save_registry(registry)
    refresh_result = _refresh_sequence_runtime("model_promote", force=True)
    return {"ok": True, "result": result, "model_refresh": refresh_result}


@app.post("/api/admin/models/rollback")
async def admin_models_rollback(req: ModelRollbackRequest):
    task = _norm_task_name(req.task)
    registry = load_registry()
    result = rollback_model(
        registry=registry,
        task=task,
        machine_id=req.machine_id,
        part_number=req.part_number,
    )
    save_registry(registry)
    refresh_result = _refresh_sequence_runtime("model_rollback", force=True)
    return {"ok": True, "result": result, "model_refresh": refresh_result}


@app.post("/api/admin/models/refresh")
async def admin_models_refresh():
    result = _refresh_sequence_runtime("manual_refresh", force=True)
    return {"ok": bool(result.get("ok")), "model_refresh": result}


@app.get("/api/machines", response_model=List[MachineSummary])
async def get_machines(db: Session = Depends(get_db)):
    # Optimized: Pull directly from MachineStats which is updated during ingestion
    stats_list = db.query(models.MachineStats).filter(models.MachineStats.machine_id.in_(MACHINE_IDS)).all()
    stats_map = {m.machine_id: m for m in stats_list}
    
    results = []
    for machine_id in MACHINE_IDS:
        m_stats = stats_map.get(machine_id)
        
        if m_stats:
            results.append({
                "id": machine_id,
                "name": MACHINE_NAMES[machine_id],
                "status": m_stats.last_status,
                "oee": m_stats.last_oee,
                "scraps": 0, # Could be calculated if needed
                "temp": m_stats.last_temp,
                "cushion": m_stats.last_cushion,
                "cycles": m_stats.last_cycles_count,
                "abnormal_params": m_stats.abnormal_params or [],
                "maintenance_urgency": m_stats.maintenance_urgency or "LOW"
            })
        else:
            # Fallback if no stats yet
            results.append({
                "id": machine_id,
                "name": MACHINE_NAMES[machine_id],
                "status": "ok",
                "oee": 0,
                "scraps": 0,
                "temp": 230,
                "cushion": 0.0,
                "cycles": 0,
                "abnormal_params": []
            })
    return results


@app.get("/api/machines/{machine_id}/parts")
async def get_machine_parts(machine_id: str, limit: int = 50):
    machine_id = _require_machine_id(machine_id)
    clamped_limit = max(1, min(limit, 500))
    catalog = _load_part_catalog()
    parts = catalog.get(machine_id, [])
    return {
        "machine_id": machine_id,
        "parts": parts[:clamped_limit],
        "source": os.path.basename(MES_WORKBOOK_PATH),
    }


@app.get("/api/machines/{machine_id}/cycles", response_model=List[CyclePayload])
async def get_machine_cycles(
    machine_id: str, limit: int = 500, offset: int = 0, db: Session = Depends(get_db)
):
    machine_id = _require_machine_id(machine_id)
    clamped_limit = max(1, min(limit, MAX_API_LIMIT))
    clamped_offset = max(0, offset)
    
    cycles = (
        db.query(models.Cycle)
        .options(joinedload(models.Cycle.prediction))
        .filter(models.Cycle.machine_id == machine_id)
        .order_by(models.Cycle.timestamp.desc())
        .offset(clamped_offset)
        .limit(clamped_limit)
        .all()
    )
    payload = [_cycle_to_payload(cycle) for cycle in reversed(cycles)]
    return _calibrate_predictions(payload)


@app.get("/api/machines/{machine_id}/data-check")
async def get_machine_data_check(
    machine_id: str, sample: int = 200, db: Session = Depends(get_db)
):
    machine_id = _require_machine_id(machine_id)
    sample_size = max(20, min(sample, 1000))
    latest_cycles = (
        db.query(models.Cycle)
        .filter(models.Cycle.machine_id == machine_id)
        .order_by(models.Cycle.timestamp.desc())
        .limit(sample_size)
        .all()
    )
    latest_cycles = list(reversed(latest_cycles))

    if not latest_cycles:
        return {"machine_id": machine_id, "sample_size": 0, "message": "No cycles found"}

    def _numeric_values(param: str) -> List[float]:
        values = []
        for cycle in latest_cycles:
            tele = (cycle.data or {}).get(param)
            if not isinstance(tele, dict): continue
            raw_val = tele.get("value")
            if isinstance(raw_val, (int, float)): values.append(float(raw_val))
            elif isinstance(raw_val, str):
                try: values.append(float(raw_val))
                except ValueError: continue
        return values

    key_params = ["cushion", "injection_time", "dosage_time", "injection_pressure", "switch_pressure", "temp_z1", "temp_z2"]
    param_stats: Dict[str, Any] = {}
    for param in key_params:
        values = _numeric_values(param)
        if not values: continue
        unique_values = len({round(v, 6) for v in values})
        param_stats[param] = {
            "count": len(values),
            "unique": unique_values,
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "is_flatline": unique_values <= 2
        }

    predictions = [c.prediction for c in latest_cycles if c.prediction]
    risk_counts: Dict[str, int] = {}
    for p in predictions:
        risk_counts[p.risk_level] = risk_counts.get(p.risk_level, 0) + 1

    return {
        "machine_id": machine_id,
        "sample_size": len(latest_cycles),
        "param_stats": param_stats,
        "risk_summary": risk_counts,
        "ingestion_info": ingestion_state.get("machines", {}).get(machine_id, {})
    }

@app.get("/api/machines/{machine_id}/audit")
async def get_machine_audit(
    machine_id: str, db: Session = Depends(get_db)
):
    """
    Advanced Industrial Audit: Provides Trend Forecasting and Signal Stability Indexes.
    """
    machine_id = _require_machine_id(machine_id)
    
    recent_cycles = (
        db.query(models.Cycle)
        .options(joinedload(models.Cycle.prediction))
        .filter(models.Cycle.machine_id == machine_id)
        .order_by(models.Cycle.timestamp.desc())
        .limit(200)
        .all()
    )
    
    if not recent_cycles:
        raise HTTPException(status_code=404, detail="No process data available for audit.")

    # Calculate Time-to-Failure (TTQT) aggregates
    forecasts = {}
    one_hour_forecast: Dict[str, Any] = {}
    
    for cycle in recent_cycles:
        tele = cycle.data or {}
        for param, values in tele.items():
            if isinstance(values, dict) and "ttqt" in values:
                ttqt = values.get("ttqt", 999)
                if ttqt < 500: # Only track imminent drifts
                    forecasts[param] = min(forecasts.get(param, 999), ttqt)

    recent_payload = [{"telemetry": cycle.data or {}} for cycle in reversed(recent_cycles)]
    audit_fallbacks = _compute_velocity_fallbacks(recent_payload)
    latest_fallbacks = audit_fallbacks[-1] if audit_fallbacks else {}

    latest_telemetry = recent_cycles[0].data or {}
    cycle_time_seconds = _estimate_cycle_time_seconds(latest_telemetry) if isinstance(latest_telemetry, dict) else 20.0
    for param, values in (latest_telemetry.items() if isinstance(latest_telemetry, dict) else []):
        if not isinstance(values, dict):
            continue
        forecast = _build_one_hour_forecast(
            values,
            cycle_time_seconds,
            fallback_velocity=latest_fallbacks.get(param),
        )
        if forecast:
            one_hour_forecast[param] = forecast
        elif isinstance(values.get("forecast_1h"), dict):
            # Backward compatibility for records that already contain precomputed forecast blobs.
            one_hour_forecast[param] = values.get("forecast_1h")

    predicted_violations = sorted(
        [param for param, fc in one_hour_forecast.items() if fc.get("will_exceed_tolerance")],
        key=lambda p: one_hour_forecast[p].get("expected_excess", 0),
        reverse=True,
    )

    # Summarize health
    stats = db.query(models.MachineStats).filter(models.MachineStats.machine_id == machine_id).first()
    
    return {
        "machine_id": machine_id,
        "audit_timestamp": _now_iso(),
        "engine": "XGBoost-Hyper v5.0.1",
        "maintenance_index": stats.maintenance_urgency if stats else "LOW",
        "critical_drift_forecasts": forecasts,
        "one_hour_parameter_forecast": one_hour_forecast,
        "predicted_violations_next_1h": predicted_violations,
        "parameter_reliability": {
            p: "STABLE" if tt > 300 else "DEGRADED" if tt > 100 else "FAILING"
            for p, tt in forecasts.items()
        }
    }


@app.get("/api/machines/{machine_id}/control-room")
async def get_machine_control_room(
    machine_id: str,
    part_number: Optional[str] = None,
    history_window: int = 240,
    horizon_minutes: int = 1920,
    shift_hours: int = 24,
    db: Session = Depends(get_db),
):
    """
    Full predictive maintenance payload:
    - Dynamic safe limits (CSV-based)
    - Future sensor timeline + future scrap probability
    - Root-cause ranking and adjusted current risk
    """
    machine_id = _require_machine_id(machine_id)
    clamped_history_window = max(30, min(history_window, 1000))
    clamped_horizon = max(5, min(horizon_minutes, 1920))
    catalog = _load_part_catalog()
    machine_parts = catalog.get(machine_id, [])
    part_options = [item.get("part_number") for item in machine_parts if isinstance(item, dict) and item.get("part_number")]

    requested_part_raw = (part_number or "").strip()
    requested_part = _normalize_part_number(requested_part_raw)
    if requested_part:
        resolved_part = requested_part
    else:
        resolved_part = part_options[0] if part_options else "UNKNOWN"

    # Date/time filter: only use cycles from the current shift window
    clamped_shift_hours = max(1, min(shift_hours, 168))  # 1h to 1 week
    shift_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=clamped_shift_hours)
    raw_cycles = (
        db.query(models.Cycle)
        .options(joinedload(models.Cycle.prediction))
        .filter(models.Cycle.machine_id == machine_id)
        .filter(models.Cycle.timestamp >= shift_cutoff)
        .order_by(models.Cycle.timestamp.desc())
        .limit(clamped_history_window)
        .all()
    )
    # Fallback: if no cycles found within shift window, use all available (avoids empty response)
    if not raw_cycles:
        raw_cycles = (
            db.query(models.Cycle)
            .options(joinedload(models.Cycle.prediction))
            .filter(models.Cycle.machine_id == machine_id)
            .order_by(models.Cycle.timestamp.desc())
            .limit(clamped_history_window)
            .all()
    )
    if not raw_cycles:
        raise HTTPException(status_code=404, detail="No process data available for control-room analytics.")

    cycles_for_analytics = list(raw_cycles)
    part_filter_scope = "machine_only"
    part_filter_meta: Dict[str, Any] = {
        "applied": False,
        "part_number": resolved_part if resolved_part != "UNKNOWN" else None,
        "total_cycles": len(raw_cycles),
        "matched_cycles": len(raw_cycles),
        "timeline_events": 0,
        "message": "Part filter not requested.",
    }

    if resolved_part != "UNKNOWN":
        part_scoped_cycles, part_filter_meta = _filter_cycles_by_part_timeline(
            raw_cycles,
            machine_id,
            resolved_part,
        )
        if part_scoped_cycles:
            cycles_for_analytics = part_scoped_cycles
            part_filter_scope = "machine+part"
        elif requested_part:
            # Explicit part selection with no timeline match keeps response alive
            # while exposing fallback state to frontend.
            part_filter_scope = "machine_fallback"
        else:
            part_filter_scope = "machine_default_part_fallback"

    recent_cycles = list(reversed(cycles_for_analytics))
    history_df = _build_recent_sensor_history(recent_cycles)
    if history_df.empty:
        raise HTTPException(status_code=404, detail="No numeric sensor history available for forecasting.")

    safe_limits_raw = calculate_dynamic_limits(history_df)
    safe_limits_frontend = convert_safe_limits_to_frontend(safe_limits_raw)

    model_meta = get_active_model_metadata(machine_id=machine_id, part_number=resolved_part if resolved_part != "UNKNOWN" else None)
    horizon_prediction_bundle = predict_multi_horizon_scrap_risk(
        recent_history=history_df,
        machine_id=machine_id,
        part_number=resolved_part if resolved_part != "UNKNOWN" else None,
        horizons=(30, 240, 1440),
        top_k=3,
    )
    future_sensors = _generate_future_horizon(
        history_df,
        num_steps=clamped_horizon,
        machine_id=machine_id,
        part_number=resolved_part if resolved_part != "UNKNOWN" else None,
    )
    future_with_risk = predict_future_scrap_risk(
        future_sensors,
        safe_limits=safe_limits_raw,
        recent_history=history_df,
        machine_id=machine_id,
        part_number=resolved_part if resolved_part != "UNKNOWN" else None,
    )
    future_timeline = build_future_timeline(future_with_risk, safe_limits_raw)

    latest_cycle = recent_cycles[-1]
    base_probability = 0.0
    if latest_cycle.prediction and latest_cycle.prediction.scrap_probability is not None:
        base_probability = _clamp(float(latest_cycle.prediction.scrap_probability), 0.0, 1.0)
    elif not future_with_risk.empty:
        projected_prob = _to_float(future_with_risk.iloc[0].get("scrap_probability"))
        if projected_prob is not None:
            base_probability = _clamp(projected_prob, 0.0, 1.0)

    current_state = {key: float(value) for key, value in history_df.iloc[-1].to_dict().items() if _to_float(value) is not None}
    root_analysis = analyze_root_causes(current_state, safe_limits_raw, base_probability)
    lstm_sequence = _build_lstm_sequence_from_cycles(cycles_for_analytics, max_steps=60)
    lstm_prob: Optional[float] = None
    lstm_expected_scrap_rate: Optional[float] = None
    lstm_attention_attributions: List[Dict[str, Any]] = []
    lstm_preview_payload: Dict[str, Any] = {}
    lstm_runtime_ready = False
    lstm_unavailable_reason: Optional[str] = None
    if AI_MODEL is not None and hasattr(AI_MODEL, "predict_batch"):
        service = getattr(AI_MODEL, "service", None)
        if service is not None and hasattr(service, "is_available"):
            lstm_runtime_ready = bool(service.is_available())
            if not lstm_runtime_ready and hasattr(service, "load"):
                lstm_runtime_ready = bool(service.load())
            if (not lstm_runtime_ready) and hasattr(service, "unavailable_reason"):
                lstm_unavailable_reason = str(service.unavailable_reason())
        else:
            lstm_runtime_ready = True

    if lstm_runtime_ready and len(lstm_sequence) >= 10:
        try:
            lstm_preview_payload = AI_MODEL.predict_batch(
                machine_id=machine_id,
                sequence=lstm_sequence,
                horizon_cycles=_horizon_minutes_to_cycles(clamped_horizon),
                part_number=resolved_part if resolved_part != "UNKNOWN" else None,
                top_k=8,
            )
            lstm_prob = _clamp(float(lstm_preview_payload.get("scrap_probability", 0.0)), 0.0, 1.0)
            rate_candidate = _to_float(lstm_preview_payload.get("expected_scrap_rate"))
            if rate_candidate is not None:
                lstm_expected_scrap_rate = _clamp(rate_candidate, 0.0, 1.0)
            attention_rows = lstm_preview_payload.get("attention_attributions", [])
            if isinstance(attention_rows, list):
                lstm_attention_attributions = attention_rows[:8]
        except RuntimeError as exc:
            err = str(exc)
            if "not loaded" in err.lower():
                lstm_runtime_ready = False
                lstm_unavailable_reason = err
            else:
                logger.warning("LSTM preview failed for %s: %s", machine_id, exc)
        except Exception as exc:
            logger.warning("LSTM preview failed for %s: %s", machine_id, exc)

    future_probs = [
        _clamp(_to_float(record.get("scrap_probability")) or 0.0, 0.0, 1.0)
        for record in future_timeline
    ]
    predicted_scrap_events = sum(1 for record in future_timeline if int(record.get("predicted_scrap", 0)) == 1)
    one_hour_parameter_forecast = _build_control_room_parameter_forecast(
        latest_cycle.data or {},
        future_timeline,
    )

    return {
        "machine_id": machine_id,
        "part_number": resolved_part,
        "part_number_requested": requested_part,
        "part_number_known_for_machine": resolved_part in part_options if part_options else False,
        "part_options": part_options,
        "part_filter_scope": part_filter_scope,
        "part_filter_applied": bool(part_filter_meta.get("applied", False)),
        "part_filter_total_cycles": int(part_filter_meta.get("total_cycles", len(raw_cycles))),
        "part_filter_matched_cycles": int(part_filter_meta.get("matched_cycles", len(cycles_for_analytics))),
        "part_filter_timeline_events": int(part_filter_meta.get("timeline_events", 0)),
        "part_filter_message": str(part_filter_meta.get("message") or ""),
        "generated_at": _now_iso(),
        "history_window_cycles": int(len(history_df)),
        "forecast_horizon_minutes": clamped_horizon,
        "safe_limits": safe_limits_raw,
        "safe_limits_frontend": safe_limits_frontend,
        "current_state": {key: round(value, 4) for key, value in current_state.items()},
        "current_telemetry": {
            RAW_TO_FRONTEND_SENSOR_MAP.get(s, str(s).lower()): {
                "value": round(current_state.get(s, 0.0), 4),
                "safe_min": round(safe_limits_raw.get(s, {}).get("min", 0.0), 4),
                "safe_max": round(safe_limits_raw.get(s, {}).get("max", 0.0), 4),
                "setpoint": round((safe_limits_raw.get(s, {}).get("min", 0.0) + safe_limits_raw.get(s, {}).get("max", 0.0)) / 2.0, 4)
            } for s in safe_limits_raw
        },
        "current_risk": {
            "base_probability": round(base_probability, 4),
            "adjusted_probability": root_analysis.get("adjusted_risk", base_probability),
            "risk_penalty": root_analysis.get("risk_penalty", 0.0),
            "breach_count": root_analysis.get("breach_count", 0),
        },
        "root_causes": root_analysis.get("root_causes", []),
        "root_cause_attributions": lstm_attention_attributions or root_analysis.get("attributions", []),
        "future_summary": {
            "peak_scrap_probability": round(max(future_probs) if future_probs else 0.0, 4),
            "predicted_scrap_events": int(predicted_scrap_events),
        },
        "model_name": (model_meta.get("scrap_classifier") or {}).get("model_id") or "legacy",
        "model_version": (model_meta.get("scrap_classifier") or {}).get("model_id"),
        "model_label": (model_meta.get("scrap_classifier") or {}).get("family") or "legacy",
        "model_family": (model_meta.get("scrap_classifier") or {}).get("family") or "legacy",
        "segment_scope": (model_meta.get("scrap_classifier") or {}).get("scope") or part_filter_scope,
        "feature_spec_hash": (model_meta.get("scrap_classifier") or {}).get("feature_spec_hash"),
        "xai_summary": {
            "model_family": lstm_preview_payload.get("model_family") or (model_meta.get("scrap_classifier") or {}).get("family") or "legacy",
            "attribution_method": "hybrid_attention_shap" if lstm_attention_attributions else "normalized_contribution",
            "top_features": (lstm_attention_attributions or root_analysis.get("attributions", []))[:5],
        },
        "model_registry": model_meta,
        "horizon_predictions": horizon_prediction_bundle.get("predictions", {}),
        "horizon_model_meta": horizon_prediction_bundle.get("model_meta", {}),
        "horizon_feature_top3": horizon_prediction_bundle.get("feature_top3", {}),
        "lstm_preview": {
            "enabled": bool(lstm_runtime_ready),
            "model_name": lstm_preview_payload.get("model_name", "LSTM-Hyper"),
            "model_version": lstm_preview_payload.get("model_version"),
            "model_label": lstm_preview_payload.get("model_label"),
            "model_family": lstm_preview_payload.get("model_family", "lstm_attention_dual"),
            "engine_version": "LSTM-Hyper v7.0.0",
            "sequence_length": int(len(lstm_sequence)),
            "scrap_probability": round(lstm_prob, 4) if lstm_prob is not None else None,
            "expected_scrap_rate": round(lstm_expected_scrap_rate, 4) if lstm_expected_scrap_rate is not None else None,
            "attention_attributions": lstm_attention_attributions,
            "unavailable_reason": lstm_unavailable_reason,
            "risk_level": (
                "VERY_HIGH" if (lstm_prob is not None and lstm_prob >= 0.9)
                else "HIGH" if (lstm_prob is not None and lstm_prob >= 0.7)
                else "ELEVATED" if (lstm_prob is not None and lstm_prob >= 0.4)
                else "NORMAL" if lstm_prob is not None
                else "UNAVAILABLE"
            ),
        },
        "one_hour_parameter_forecast": one_hour_parameter_forecast,
        "future_timeline": future_timeline,
    }


@app.get("/api/machines/{machine_id}/insight")
async def get_machine_insight(
    machine_id: str, db: Session = Depends(get_db)
):
    """
    Translates AI signals into human-readable industrial insights.
    """
    machine_id = _require_machine_id(machine_id)
    stats = db.query(models.MachineStats).filter(models.MachineStats.machine_id == machine_id).first()
    
    if not stats:
        raise HTTPException(status_code=404, detail="Stats not found.")
        
    insights = []
    if stats.last_status == "crit":
        insights.append(f"Immediate intervention required: {', '.join(stats.abnormal_params)} are violating safety envelopes.")
    elif stats.last_status == "warn":
        insights.append(f"Process stability is degrading due to {', '.join(stats.abnormal_params)} instability.")
    else:
        insights.append("Process is currently within nominal operating bounds.")

    if stats.maintenance_urgency == "HIGH":
        insights.append("Predictive maintenance audit recommended within the next 8 hours.")
        
    return {
        "machine_id": machine_id,
        "status_summary": stats.last_status,
        "insights": insights,
        "maintenance_urgency": stats.maintenance_urgency,
        "oee_snapshot": stats.last_oee
    }


def _latest_stream_cursor(machine_id: str) -> Tuple[Optional[datetime], Optional[int]]:
    db = database.SessionLocal()
    try:
        latest = (
            db.query(models.Cycle)
            .filter(models.Cycle.machine_id == machine_id)
            .order_by(models.Cycle.timestamp.desc(), models.Cycle.id.desc())
            .first()
        )
        if not latest:
            return None, None
        return latest.timestamp, int(latest.id)
    finally:
        db.close()


def _load_stream_updates(
    machine_id: str,
    since_timestamp: Optional[datetime],
    since_cycle_row_id: Optional[int],
) -> List[Tuple[Dict[str, Any], datetime, int]]:
    db = database.SessionLocal()
    try:
        query = (
            db.query(models.Cycle)
            .options(joinedload(models.Cycle.prediction))
            .filter(models.Cycle.machine_id == machine_id)
        )
        if since_timestamp is not None and since_cycle_row_id is not None:
            query = query.filter(
                or_(
                    models.Cycle.timestamp > since_timestamp,
                    and_(
                        models.Cycle.timestamp == since_timestamp,
                        models.Cycle.id > int(since_cycle_row_id),
                    ),
                )
            )
        elif since_timestamp is not None:
            query = query.filter(models.Cycle.timestamp > since_timestamp)

        cycles = (
            query.order_by(models.Cycle.timestamp.asc(), models.Cycle.id.asc())
            .limit(max(1, WS_STREAM_LIMIT))
            .all()
        )
        if not cycles:
            return []

        payloads = _calibrate_predictions([_cycle_to_payload(cycle) for cycle in cycles])
        updates: List[Tuple[Dict[str, Any], datetime, int]] = []
        for idx, cycle in enumerate(cycles):
            updates.append((payloads[idx], cycle.timestamp, int(cycle.id)))
        return updates
    finally:
        db.close()


def _build_control_room_parameter_forecast(
    latest_telemetry: Dict[str, Any],
    future_timeline: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Build per-parameter horizon forecast summary from control-room future timeline.
    """
    if not isinstance(latest_telemetry, dict) or not future_timeline:
        return {}

    horizon_minutes = max(1, len(future_timeline))
    first_future_telemetry = (
        future_timeline[0].get("telemetry", {})
        if isinstance(future_timeline[0], dict)
        else {}
    )
    last_future_telemetry = (
        future_timeline[-1].get("telemetry", {})
        if isinstance(future_timeline[-1], dict)
        else {}
    )

    forecast: Dict[str, Dict[str, Any]] = {}
    for sensor, current_payload in latest_telemetry.items():
        if not isinstance(current_payload, dict):
            continue

        current_value = _to_float(current_payload.get("value"))
        if current_value is None:
            continue

        first_future_payload = first_future_telemetry.get(sensor)
        last_future_payload = last_future_telemetry.get(sensor)
        if not isinstance(last_future_payload, dict):
            continue

        predicted_value = _to_float(last_future_payload.get("value"))
        if predicted_value is None:
            continue

        safe_min = _to_float(current_payload.get("safe_min"))
        safe_max = _to_float(current_payload.get("safe_max"))
        if safe_min is None:
            safe_min = _to_float(last_future_payload.get("safe_min"))
        if safe_max is None:
            safe_max = _to_float(last_future_payload.get("safe_max"))

        setpoint = _to_float(current_payload.get("setpoint"))
        if setpoint is None:
            setpoint = _to_float(last_future_payload.get("setpoint"))
        if setpoint is None and safe_min is not None and safe_max is not None:
            setpoint = (safe_min + safe_max) / 2.0

        current_deviation = abs(current_value - setpoint) if setpoint is not None else 0.0
        predicted_deviation = abs(predicted_value - setpoint) if setpoint is not None else 0.0
        deviation_change = predicted_deviation - current_deviation

        expected_excess = 0.0
        will_exceed_tolerance = False
        if safe_min is not None and safe_max is not None:
            if predicted_value > safe_max:
                expected_excess = predicted_value - safe_max
                will_exceed_tolerance = True
            elif predicted_value < safe_min:
                expected_excess = safe_min - predicted_value
                will_exceed_tolerance = True

        expected_threshold_cross_minutes: Optional[float] = None
        if safe_min is not None and safe_max is not None:
            for minute_idx, item in enumerate(future_timeline, start=1):
                future_telemetry = item.get("telemetry", {}) if isinstance(item, dict) else {}
                future_param = future_telemetry.get(sensor)
                if not isinstance(future_param, dict):
                    continue
                future_value = _to_float(future_param.get("value"))
                if future_value is None:
                    continue
                if future_value < safe_min or future_value > safe_max:
                    expected_threshold_cross_minutes = float(minute_idx)
                    break

        trend = "flat"
        first_future_value = (
            _to_float(first_future_payload.get("value"))
            if isinstance(first_future_payload, dict)
            else None
        )
        trend_delta = (
            (predicted_value - first_future_value)
            if first_future_value is not None
            else (predicted_value - current_value)
        )
        if trend_delta > 1e-6:
            trend = "up"
        elif trend_delta < -1e-6:
            trend = "down"

        forecast[sensor] = {
            "horizon_minutes": int(horizon_minutes),
            "predicted_value": round(predicted_value, 4),
            "predicted_deviation": round(predicted_deviation, 4),
            "deviation_change": round(deviation_change, 4),
            "will_exceed_tolerance": bool(will_exceed_tolerance),
            "expected_excess": round(expected_excess, 4),
            "trend": trend,
            "expected_threshold_cross_minutes": expected_threshold_cross_minutes,
        }

    return forecast


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    current_machine = "M231-11"
    stream_task: Optional[asyncio.Task] = None

    async def safe_send(payload: Dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except WebSocketDisconnect:
            return False
        except RuntimeError as exc:
            if _is_ws_closed_runtime_error(exc):
                return False
            raise

    async def cancel_stream_task(task: Optional[asyncio.Task]) -> None:
        if not task:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except WebSocketDisconnect:
            pass
        except RuntimeError as exc:
            if not _is_ws_closed_runtime_error(exc):
                logger.debug("WebSocket stream task runtime error: %s", exc)
        except Exception as exc:
            logger.debug("WebSocket stream task ended with error: %s", exc)

    async def stream_machine(machine_id: str) -> None:
        # Start at the latest committed row so the stream is truly forward/live.
        last_stream_ts, last_stream_row_id = _latest_stream_cursor(machine_id)
        while True:
            updates = _load_stream_updates(machine_id, last_stream_ts, last_stream_row_id)
            if not updates:
                sent = await safe_send(
                    {"type": "heartbeat", "machine_id": machine_id, "timestamp": _now_iso()}
                )
                if not sent:
                    break
                await asyncio.sleep(WS_STREAM_INTERVAL_SEC)
                continue

            for cycle_payload, cycle_ts, cycle_row_id in updates:
                sent = await safe_send(
                    {
                        "type": "cycle_update",
                        "machine_id": machine_id,
                        "cycle": cycle_payload,
                    }
                )
                if not sent:
                    break
                last_stream_ts = cycle_ts
                last_stream_row_id = cycle_row_id
            else:
                await asyncio.sleep(0.25)
                continue

            break

    try:
        stream_task = asyncio.create_task(stream_machine(current_machine))
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except json.JSONDecodeError:
                sent = await safe_send({"type": "error", "message": "Invalid JSON message"})
                if not sent:
                    break
                continue

            msg_type = data.get("type")
            if msg_type == "switch_machine":
                new_machine = data.get("machine_id")
                resolved_machine = _resolve_machine_id(new_machine)
                if not resolved_machine:
                    candidates = _machine_match_candidates(new_machine)
                    sent = await safe_send(
                        {
                            "type": "error",
                            "message": _machine_id_error_message(new_machine, candidates),
                            "valid_ids": MACHINE_IDS,
                        }
                    )
                    if not sent:
                        break
                    continue
                current_machine = resolved_machine
                if stream_task:
                    await cancel_stream_task(stream_task)
                stream_task = asyncio.create_task(stream_machine(current_machine))
            elif msg_type == "ping":
                sent = await safe_send({"type": "pong"})
                if not sent:
                    break
            else:
                sent = await safe_send({"type": "error", "message": "Unsupported message type"})
                if not sent:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if stream_task:
            await cancel_stream_task(stream_task)
