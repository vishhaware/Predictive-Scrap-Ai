import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.multioutput import MultiOutputRegressor

# Keep noisy/optional ML frameworks lazy-loaded (imported only when needed).
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    import lightgbm as lgb
except Exception:
    lgb = None

try:
    import xgboost as xgb
except Exception:
    xgb = None

try:
    from .ml_dataset import build_training_dataset
    from .ml_features import build_features
    from .ml_preprocess import apply_scaler, chronological_split, clean_dataset, fill_missing, fit_scaler
    from .model_registry import (
        load_registry,
        register_model_bundle,
        resolve_active_model_id,
        save_registry,
    )
except ImportError:
    from ml_dataset import build_training_dataset
    from ml_features import build_features
    from ml_preprocess import apply_scaler, chronological_split, clean_dataset, fill_missing, fit_scaler
    from model_registry import (
        load_registry,
        register_model_bundle,
        resolve_active_model_id,
        save_registry,
    )


BASE_DIR = os.path.dirname(__file__)
MODELS_DIR = os.path.join(BASE_DIR, "models")
BUNDLES_DIR = os.path.join(MODELS_DIR, "registry", "bundles")
BENCHMARK_PATH = os.path.join(MODELS_DIR, "registry", "latest_benchmark.json")

TARGET_SENSORS = [
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


@dataclass
class TrainConfig:
    min_segment_rows: int = 180
    min_validation_rows: int = 15
    min_positive_rows: int = 6
    num_lags: int = 3
    rolling_windows: Tuple[int, ...] = (3, 5, 10, 20)
    train_ratio: float = 0.8
    recall_improvement_delta: float = 0.01
    recall_floor: float = 0.45
    false_alarm_guardrail: float = 0.10
    brier_regression_guardrail: float = 0.02
    forecast_rmse_regression_guardrail: float = 0.20
    latency_budget_ms: float = 350.0
    sequence_length: int = 30
    horizon_cycles: int = 30
    lstm_epochs: int = 18
    lstm_batch_size: int = 64
    shap_background_samples: int = 32


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if np.isnan(out):
        return default
    return out


def _mse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(mean_squared_error(y_true, y_pred))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return _mse(y_true, y_pred) ** 0.5


def _smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denominator = np.abs(y_true) + np.abs(y_pred)
    denominator = np.where(denominator == 0, 1.0, denominator)
    return float(np.mean(2.0 * np.abs(y_pred - y_true) / denominator))


def _classifier_metrics(y_true: np.ndarray, proba: np.ndarray, threshold: float = 0.5) -> Dict[str, float]:
    pred = (proba >= threshold).astype(int)
    precision = precision_score(y_true, pred, zero_division=0)
    recall = recall_score(y_true, pred, zero_division=0)
    f1 = f1_score(y_true, pred, zero_division=0)
    tn = int(((y_true == 0) & (pred == 0)).sum())
    fp = int(((y_true == 0) & (pred == 1)).sum())
    false_alarm_rate = float(fp / max(1, (fp + tn)))
    metrics: Dict[str, float] = {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_alarm_rate": false_alarm_rate,
        "brier": float(brier_score_loss(y_true, proba)),
        "logloss": float(log_loss(y_true, np.clip(proba, 1e-6, 1 - 1e-6))),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, proba))
        metrics["pr_auc"] = float(average_precision_score(y_true, proba))
    else:
        metrics["roc_auc"] = 0.5
        metrics["pr_auc"] = 0.0
    return metrics


def _choose_recall_threshold(
    y_true: np.ndarray,
    proba: np.ndarray,
    false_alarm_guardrail: float,
) -> Tuple[float, Dict[str, float]]:
    """
    Choose the best threshold under false-alarm guardrail with recall-first objective.
    """
    candidates = np.linspace(0.15, 0.85, 29)
    best_threshold = 0.5
    best_metrics = _classifier_metrics(y_true, proba, threshold=best_threshold)

    for th in candidates:
        metrics = _classifier_metrics(y_true, proba, threshold=float(th))
        if metrics["false_alarm_rate"] > false_alarm_guardrail:
            continue
        # Recall-first, then F1 as tie-break.
        if (
            metrics["recall"] > best_metrics["recall"]
            or (
                abs(metrics["recall"] - best_metrics["recall"]) < 1e-9
                and metrics["f1"] > best_metrics["f1"]
            )
        ):
            best_threshold = float(th)
            best_metrics = metrics

    best_metrics["decision_threshold"] = float(best_threshold)
    return float(best_threshold), best_metrics


def _forecast_metrics(y_true: np.ndarray, y_pred: np.ndarray, sensor_cols: List[str]) -> Dict[str, Any]:
    by_sensor: Dict[str, Dict[str, float]] = {}
    rmses: List[float] = []
    maes: List[float] = []
    smapes: List[float] = []
    for i, sensor in enumerate(sensor_cols):
        y_t = y_true[:, i]
        y_p = y_pred[:, i]
        rmse_v = _rmse(y_t, y_p)
        mae_v = float(mean_absolute_error(y_t, y_p))
        smape_v = _smape(y_t, y_p)
        by_sensor[sensor] = {"rmse": rmse_v, "mae": mae_v, "smape": smape_v}
        rmses.append(rmse_v)
        maes.append(mae_v)
        smapes.append(smape_v)
    return {
        "rmse_mean": float(np.mean(rmses) if rmses else 0.0),
        "mae_mean": float(np.mean(maes) if maes else 0.0),
        "smape_mean": float(np.mean(smapes) if smapes else 0.0),
        "by_sensor": by_sensor,
    }


def _fit_classifier(
    family: str,
    x_train: pd.DataFrame,
    y_train: pd.Series,
) -> Optional[Any]:
    if family == "lightgbm":
        if lgb is None:
            return None
        positives = int(y_train.sum())
        negatives = int(len(y_train) - positives)
        scale_pos_weight = max(1.0, negatives / max(1, positives))
        model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=350,
            learning_rate=0.04,
            num_leaves=63,
            random_state=42,
            n_jobs=-1,
            scale_pos_weight=scale_pos_weight,
        )
        model.fit(x_train, y_train)
        return model
    if family == "xgboost":
        if xgb is None:
            return None
        positives = int(y_train.sum())
        negatives = int(len(y_train) - positives)
        scale_pos_weight = max(1.0, negatives / max(1, positives))
        model = xgb.XGBClassifier(
            objective="binary:logistic",
            n_estimators=280,
            learning_rate=0.05,
            max_depth=7,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(x_train, y_train)
        return model
    if family == "random_forest":
        model = RandomForestClassifier(
            n_estimators=240,
            max_depth=18,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )
        model.fit(x_train, y_train)
        return model
    return None


def _build_lstm_classifier_windows(
    seg_df: pd.DataFrame,
    sensor_cols: List[str],
    train_mask: pd.Series,
    scaler: Optional[Any],
    sequence_length: int,
    horizon_cycles: int,
) -> Optional[Dict[str, np.ndarray]]:
    if seg_df.empty or not sensor_cols:
        return None
    if "scrap_event" not in seg_df.columns:
        return None

    numeric_df = seg_df[sensor_cols].copy()
    numeric_df = numeric_df.apply(pd.to_numeric, errors="coerce").ffill().fillna(0.0)
    values = np.asarray(numeric_df.values, dtype=np.float32)
    if scaler is not None:
        try:
            values = np.asarray(scaler.transform(values), dtype=np.float32)
        except Exception:
            values = np.asarray(values, dtype=np.float32)

    events = np.asarray(pd.to_numeric(seg_df["scrap_event"], errors="coerce").fillna(0).astype(int).values, dtype=np.int32)
    if len(values) <= (sequence_length + horizon_cycles):
        return None

    train_mask_arr = np.asarray(train_mask.values, dtype=bool)
    if train_mask_arr.size != len(values) or not np.any(train_mask_arr):
        return None
    train_end_idx = int(np.where(train_mask_arr)[0].max())

    x_train: List[np.ndarray] = []
    y_event_train: List[float] = []
    y_rate_train: List[float] = []
    x_val: List[np.ndarray] = []
    y_event_val: List[float] = []
    y_rate_val: List[float] = []

    max_end_idx = len(values) - horizon_cycles - 1
    for end_idx in range(sequence_length - 1, max_end_idx + 1):
        future_window = events[end_idx + 1 : end_idx + 1 + horizon_cycles]
        if len(future_window) < horizon_cycles:
            continue
        event_target = float(1 if np.any(future_window > 0) else 0)
        rate_target = float(np.mean(future_window))
        seq_window = values[end_idx - sequence_length + 1 : end_idx + 1]
        if seq_window.shape[0] != sequence_length:
            continue

        # Prevent leakage: train windows must have label horizon fully inside train split.
        if (end_idx + horizon_cycles) <= train_end_idx:
            x_train.append(seq_window)
            y_event_train.append(event_target)
            y_rate_train.append(rate_target)
        elif end_idx > train_end_idx:
            x_val.append(seq_window)
            y_event_val.append(event_target)
            y_rate_val.append(rate_target)

    if not x_train or not x_val:
        return None

    return {
        "x_train": np.asarray(x_train, dtype=np.float32),
        "y_event_train": np.asarray(y_event_train, dtype=np.float32),
        "y_rate_train": np.asarray(y_rate_train, dtype=np.float32),
        "x_val": np.asarray(x_val, dtype=np.float32),
        "y_event_val": np.asarray(y_event_val, dtype=np.float32),
        "y_rate_val": np.asarray(y_rate_val, dtype=np.float32),
    }


def _fit_lstm_attention_classifier(
    windows: Dict[str, np.ndarray],
    cfg: TrainConfig,
) -> Optional[Dict[str, Any]]:
    try:
        import tensorflow as tf
    except Exception:
        return None

    x_train = windows["x_train"]
    y_event_train = windows["y_event_train"]
    y_rate_train = windows["y_rate_train"]
    x_val = windows["x_val"]
    y_event_val = windows["y_event_val"]
    y_rate_val = windows["y_rate_val"]

    if int(np.sum(y_event_train)) < cfg.min_positive_rows:
        return None
    if len(x_val) < cfg.min_validation_rows:
        return None

    tf.keras.backend.clear_session()
    tf.random.set_seed(42)

    inputs = tf.keras.layers.Input(shape=(x_train.shape[1], x_train.shape[2]), name="sequence_input")
    x = tf.keras.layers.LSTM(64, return_sequences=True, name="lstm_1")(inputs)
    x = tf.keras.layers.Dropout(0.25, name="dropout_1")(x)
    x = tf.keras.layers.LSTM(32, return_sequences=True, name="lstm_2")(x)
    attention_logits = tf.keras.layers.Dense(1, activation="tanh", name="attention_logits")(x)
    attention_weights = tf.keras.layers.Softmax(axis=1, name="attention_weights")(attention_logits)
    context = tf.keras.layers.Dot(axes=1, name="attention_context")([attention_weights, x])
    context = tf.keras.layers.Flatten(name="attention_context_flat")(context)
    event_prob = tf.keras.layers.Dense(1, activation="sigmoid", name="event_prob")(context)
    rate_pred = tf.keras.layers.Dense(1, activation="sigmoid", name="rate_pred")(context)

    model = tf.keras.Model(inputs=inputs, outputs=[event_prob, rate_pred], name="lstm_attention_dual")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss={
            "event_prob": "binary_crossentropy",
            "rate_pred": "mse",
        },
        loss_weights={
            "event_prob": 1.0,
            "rate_pred": 0.35,
        },
        metrics={
            "event_prob": [
                tf.keras.metrics.AUC(name="auc"),
                tf.keras.metrics.Precision(name="precision"),
                tf.keras.metrics.Recall(name="recall"),
            ],
            "rate_pred": [tf.keras.metrics.MeanAbsoluteError(name="mae")],
        },
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_event_prob_auc",
            mode="max",
            patience=4,
            restore_best_weights=True,
        )
    ]
    model.fit(
        x_train,
        {"event_prob": y_event_train, "rate_pred": y_rate_train},
        validation_data=(x_val, {"event_prob": y_event_val, "rate_pred": y_rate_val}),
        epochs=max(6, int(cfg.lstm_epochs)),
        batch_size=max(16, int(cfg.lstm_batch_size)),
        verbose=0,
        callbacks=callbacks,
    )

    pred_event, pred_rate = model.predict(x_val, verbose=0)
    proba_val = np.asarray(pred_event, dtype=float).reshape(-1)
    rate_val_pred = np.asarray(pred_rate, dtype=float).reshape(-1)
    threshold, metrics = _choose_recall_threshold(
        np.asarray(y_event_val, dtype=int),
        proba_val,
        false_alarm_guardrail=cfg.false_alarm_guardrail,
    )
    metrics["rate_mae"] = float(mean_absolute_error(np.asarray(y_rate_val, dtype=float), rate_val_pred))
    metrics["rate_rmse"] = float(mean_squared_error(np.asarray(y_rate_val, dtype=float), rate_val_pred) ** 0.5)
    metrics["sequence_length"] = int(x_train.shape[1])
    metrics["horizon_cycles"] = int(cfg.horizon_cycles)

    bg_count = min(max(1, int(cfg.shap_background_samples)), len(x_train))
    background_samples = np.asarray(x_train[:bg_count], dtype=np.float32)

    return {
        "model": model,
        "proba_val": proba_val,
        "metrics": metrics,
        "decision_threshold": threshold,
        "background_samples": background_samples,
        "x_val_rows": int(len(x_val)),
    }


def _fit_forecaster(
    family: str,
    x_train: pd.DataFrame,
    y_train: pd.DataFrame,
    sensor_cols: List[str],
    df_train_rows: pd.DataFrame,
) -> Optional[Any]:
    if family == "lightgbm":
        if lgb is None:
            return None
        model = MultiOutputRegressor(
            lgb.LGBMRegressor(
                objective="regression",
                n_estimators=220,
                learning_rate=0.05,
                num_leaves=63,
                random_state=42,
                n_jobs=-1,
            )
        )
        model.fit(x_train, y_train)
        return model
    if family == "arima":
        try:
            from statsmodels.tsa.arima.model import ARIMA
        except Exception:
            return None
        models: Dict[str, Any] = {}
        for sensor in sensor_cols:
            series = pd.to_numeric(df_train_rows[sensor], errors="coerce").ffill().fillna(0.0)
            if len(series) < 30:
                return None
            models[sensor] = ARIMA(series, order=(2, 1, 1)).fit()
        return {"family": "arima", "models": models}
    if family == "prophet":
        try:
            from prophet import Prophet
        except Exception:
            return None
        models = {}
        for sensor in sensor_cols:
            train_df = pd.DataFrame(
                {
                    "ds": pd.to_datetime(df_train_rows["timestamp"], errors="coerce"),
                    "y": pd.to_numeric(df_train_rows[sensor], errors="coerce"),
                }
            ).dropna()
            if len(train_df) < 40:
                return None
            p = Prophet(daily_seasonality=True, weekly_seasonality=True)
            p.fit(train_df)
            models[sensor] = p
        return {"family": "prophet", "models": models}
    if family == "lstm":
        try:
            import tensorflow as tf
        except Exception:
            return None
        tf.random.set_seed(42)
        model = tf.keras.Sequential(
            [
                tf.keras.layers.Input(shape=(1, x_train.shape[1])),
                tf.keras.layers.LSTM(32, activation="tanh"),
                tf.keras.layers.Dense(y_train.shape[1]),
            ]
        )
        model.compile(optimizer="adam", loss="mse")
        x_arr = np.asarray(x_train, dtype=np.float32).reshape((-1, 1, x_train.shape[1]))
        y_arr = np.asarray(y_train, dtype=np.float32)
        model.fit(x_arr, y_arr, epochs=10, batch_size=64, verbose=0)
        return {"family": "lstm", "model": model}
    return None


def _predict_forecaster(
    family: str,
    model: Any,
    x_val: pd.DataFrame,
    y_template: pd.DataFrame,
    sensor_cols: List[str],
    df_val_rows: pd.DataFrame,
) -> np.ndarray:
    if family == "lightgbm":
        return np.asarray(model.predict(x_val), dtype=float)
    if family == "arima":
        preds: List[np.ndarray] = []
        steps = len(x_val)
        for sensor in sensor_cols:
            fitted = model["models"][sensor]
            preds.append(np.asarray(fitted.forecast(steps=steps), dtype=float))
        return np.vstack(preds).T
    if family == "prophet":
        preds = []
        val_dates = pd.to_datetime(df_val_rows["timestamp"], errors="coerce")
        for sensor in sensor_cols:
            p = model["models"][sensor]
            future_df = pd.DataFrame({"ds": val_dates})
            fc = p.predict(future_df)
            preds.append(np.asarray(fc["yhat"], dtype=float))
        return np.vstack(preds).T
    if family == "lstm":
        lstm = model["model"]
        x_arr = np.asarray(x_val, dtype=np.float32).reshape((-1, 1, x_val.shape[1]))
        return np.asarray(lstm.predict(x_arr, verbose=0), dtype=float)
    return np.zeros_like(np.asarray(y_template, dtype=float))


def _promote_candidate(
    cfg: TrainConfig,
    challenger: Dict[str, Any],
    incumbent: Optional[Dict[str, Any]],
    task: str,
) -> bool:
    if task == "scrap_classifier":
        rec = _safe_float(challenger.get("metrics", {}).get("recall"))
        fa = _safe_float(challenger.get("metrics", {}).get("false_alarm_rate"))
        brier = _safe_float(challenger.get("metrics", {}).get("brier"))
        if fa > cfg.false_alarm_guardrail:
            return False
        if incumbent:
            inc_rec = _safe_float(incumbent.get("metrics", {}).get("recall"))
            inc_brier = _safe_float(incumbent.get("metrics", {}).get("brier"))
            if rec < max(cfg.recall_floor, inc_rec + cfg.recall_improvement_delta):
                return False
            if brier > (inc_brier + cfg.brier_regression_guardrail):
                return False
        else:
            if rec < cfg.recall_floor:
                return False
        return True
    rmse = _safe_float(challenger.get("metrics", {}).get("rmse_mean"))
    if incumbent:
        inc_rmse = _safe_float(incumbent.get("metrics", {}).get("rmse_mean"))
        return rmse <= (inc_rmse + cfg.forecast_rmse_regression_guardrail)
    return True


def _segment_scope_key(segment: str) -> Tuple[Optional[str], Optional[str]]:
    if "|" in segment:
        machine, part = segment.split("|", 1)
        return machine, part
    if segment.startswith("machine:"):
        return segment.split(":", 1)[1], None
    return None, None


def _safe_segment_token(segment: str) -> str:
    return (
        str(segment)
        .replace("|", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )


def _build_training_units(
    feat_df: pd.DataFrame,
    cfg: TrainConfig,
    segment_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    added = set()

    # 1) Machine+Part segments
    for seg, seg_df in feat_df.groupby("segment_id", sort=True):
        segment_id = str(seg)
        machine_id, part_number = _segment_scope_key(segment_id)
        if len(seg_df) < cfg.min_segment_rows:
            continue
        if segment_filter and segment_filter != segment_id:
            continue
        units.append(
            {
                "segment_id": segment_id,
                "scope": "machine+part",
                "machine_id": machine_id,
                "part_number": part_number,
                "group_cols": ["segment_id"],
                "df": seg_df.copy().sort_values("timestamp"),
            }
        )
        added.add(segment_id)

    # 2) Machine-level fallback segments
    for machine_id, machine_df in feat_df.groupby("machine_id", sort=True):
        if len(machine_df) < cfg.min_segment_rows:
            continue
        segment_id = f"machine:{machine_id}"
        if segment_filter and segment_filter != segment_id:
            continue
        if segment_id in added:
            continue
        units.append(
            {
                "segment_id": segment_id,
                "scope": "machine",
                "machine_id": str(machine_id),
                "part_number": None,
                "group_cols": ["machine_id", "part_number"],
                "df": machine_df.copy().sort_values("timestamp"),
            }
        )
        added.add(segment_id)

    # 3) Global fallback segment
    if len(feat_df) >= cfg.min_segment_rows:
        segment_id = "global"
        if (not segment_filter) or (segment_filter == segment_id):
            if segment_id not in added:
                units.append(
                    {
                        "segment_id": segment_id,
                        "scope": "global",
                        "machine_id": None,
                        "part_number": None,
                        "group_cols": ["machine_id", "part_number"],
                        "df": feat_df.copy().sort_values("timestamp"),
                    }
                )

    return units


def _save_bundle_artifact(model_id: str, payload: Dict[str, Any]) -> str:
    os.makedirs(BUNDLES_DIR, exist_ok=True)
    path = os.path.join(BUNDLES_DIR, f"{model_id}.pkl")
    joblib.dump(payload, path)
    return path


def run_training_pipeline(
    db,
    machine_ids: Optional[List[str]] = None,
    segment_filter: Optional[str] = None,
    auto_promote: bool = False,
    cfg: Optional[TrainConfig] = None,
) -> Dict[str, Any]:
    config = cfg or TrainConfig()
    started = time.time()

    dataset, data_meta = build_training_dataset(
        db=db,
        machine_ids=machine_ids,
        lookback_cycles=15000,
        lookback_hours=24,
    )
    if dataset.empty:
        return {"ok": False, "error": "No training data found", "dataset": data_meta}

    sensor_cols = [s for s in TARGET_SENSORS if s in dataset.columns]
    if not sensor_cols:
        return {"ok": False, "error": "No sensor columns found in training dataset", "dataset": data_meta}

    dataset = clean_dataset(dataset, numeric_cols=sensor_cols + ["scrap_counter", "scrap_probability_label"])
    dataset = fill_missing(dataset, numeric_cols=sensor_cols + ["scrap_counter", "scrap_probability_label"])
    feat_df, feature_cols, feature_spec, spec_hash = build_features(
        dataset,
        sensors=sensor_cols,
        num_lags=config.num_lags,
        rolling_windows=list(config.rolling_windows),
    )

    # forecast labels (next step)
    target_cols = [f"target_next_{sensor}" for sensor in sensor_cols]
    target_data = {
        f"target_next_{sensor}": feat_df.groupby("segment_id")[sensor].shift(-1)
        for sensor in sensor_cols
    }
    feat_df = pd.concat([feat_df, pd.DataFrame(target_data, index=feat_df.index)], axis=1)

    feat_df = feat_df.dropna(subset=target_cols).reset_index(drop=True)
    if feat_df.empty:
        return {"ok": False, "error": "No rows after target construction", "dataset": data_meta}

    units = _build_training_units(feat_df, cfg=config, segment_filter=segment_filter)
    if not units:
        return {"ok": False, "error": f"No segment rows for segment_filter={segment_filter}"}

    registry = load_registry()
    benchmark_rows: List[Dict[str, Any]] = []
    promoted_rows: List[Dict[str, Any]] = []

    skipped_units: List[Dict[str, Any]] = []
    for unit in units:
        segment = unit["segment_id"]
        seg_df = unit["df"]
        machine_id = unit.get("machine_id")
        part_number = unit.get("part_number")
        group_cols = unit.get("group_cols") or ["segment_id"]

        if len(seg_df) < config.min_segment_rows:
            skipped_units.append({"segment_id": segment, "reason": "insufficient_rows"})
            continue

        train_mask, val_mask = chronological_split(seg_df, group_cols=group_cols, train_ratio=config.train_ratio)
        if int(val_mask.sum()) < config.min_validation_rows:
            skipped_units.append({"segment_id": segment, "reason": "insufficient_validation_rows"})
            continue

        scaler = fit_scaler(seg_df, feature_cols=feature_cols, train_mask=train_mask)
        seg_scaled = apply_scaler(seg_df, feature_cols=feature_cols, scaler=scaler)

        x_train = seg_scaled.loc[train_mask, feature_cols]
        x_val = seg_scaled.loc[val_mask, feature_cols]
        y_train_cls = seg_scaled.loc[train_mask, "scrap_event"].astype(int)
        y_val_cls = seg_scaled.loc[val_mask, "scrap_event"].astype(int)
        y_train_reg = seg_scaled.loc[train_mask, target_cols]
        y_val_reg = seg_scaled.loc[val_mask, target_cols]
        val_rows = seg_scaled.loc[val_mask, ["timestamp"] + sensor_cols]
        train_rows = seg_scaled.loc[train_mask, ["timestamp"] + sensor_cols]

        if int(y_train_cls.sum()) < config.min_positive_rows:
            skipped_units.append({"segment_id": segment, "reason": "insufficient_positive_rows"})
            continue

        for family in ["lightgbm", "xgboost", "random_forest"]:
            model = _fit_classifier(family, x_train=x_train, y_train=y_train_cls)
            if model is None:
                continue
            t0 = time.time()
            proba = np.asarray(model.predict_proba(x_val))[:, 1]
            latency_ms = ((time.time() - t0) * 1000.0) / max(1, len(x_val))
            threshold, metrics = _choose_recall_threshold(
                np.asarray(y_val_cls),
                proba,
                false_alarm_guardrail=config.false_alarm_guardrail,
            )
            metrics["latency_ms_per_row"] = float(latency_ms)
            model_id = f"scrap_classifier__{family}__{_safe_segment_token(segment)}__{int(time.time()*1000)}"
            bundle = {
                "model_id": model_id,
                "task": "scrap_classifier",
                "family": family,
                "machine_id": machine_id,
                "part_number": part_number,
                "segment_id": segment,
                "segment_scope": unit.get("scope"),
                "feature_cols": feature_cols,
                "feature_spec": feature_spec,
                "feature_spec_hash": spec_hash,
                "decision_threshold": threshold,
                "metrics": metrics,
                "trained_at": _now_iso(),
                "artifact_path": "",
                "model_object": model,
                "scaler": scaler,
            }
            artifact_payload = {
                "model": model,
                "scaler": scaler,
                "feature_cols": feature_cols,
                "feature_spec": feature_spec,
                "feature_spec_hash": spec_hash,
                "family": family,
                "task": "scrap_classifier",
                "decision_threshold": threshold,
                "metrics": metrics,
            }
            bundle["artifact_path"] = _save_bundle_artifact(model_id, artifact_payload)
            register_model_bundle(registry, "scrap_classifier", model_id, {k: v for k, v in bundle.items() if k not in {"model_object", "scaler"}})

            incumbent_id, _ = resolve_active_model_id(registry, "scrap_classifier", machine_id, part_number)
            incumbent = registry.get("models", {}).get(incumbent_id) if incumbent_id else None
            recommended = (
                latency_ms <= config.latency_budget_ms
                and _promote_candidate(config, {"metrics": metrics}, incumbent, "scrap_classifier")
            )
            benchmark_rows.append(
                {
                    "task": "scrap_classifier",
                    "segment_id": segment,
                    "model_id": model_id,
                    "family": family,
                    "segment_scope": unit.get("scope"),
                    "metrics": metrics,
                    "recommended": bool(recommended),
                }
            )
            if auto_promote and recommended:
                from model_registry import promote_model

                promoted_rows.append(promote_model(registry, "scrap_classifier", model_id, machine_id, part_number))

        # Sequence classifier candidate (parallel shadow): LSTM + attention + dual-output target.
        sequence_scaler = fit_scaler(seg_df, feature_cols=sensor_cols, train_mask=train_mask)
        windows = _build_lstm_classifier_windows(
            seg_df=seg_df,
            sensor_cols=sensor_cols,
            train_mask=train_mask,
            scaler=sequence_scaler,
            sequence_length=config.sequence_length,
            horizon_cycles=config.horizon_cycles,
        )
        if windows is not None:
            lstm_candidate = _fit_lstm_attention_classifier(windows=windows, cfg=config)
            if lstm_candidate is not None:
                model = lstm_candidate["model"]
                metrics = dict(lstm_candidate["metrics"])
                threshold = float(lstm_candidate["decision_threshold"])
                val_rows_count = max(1, int(lstm_candidate.get("x_val_rows", 1)))
                t0 = time.time()
                _ = model.predict(windows["x_val"][: min(len(windows["x_val"]), 32)], verbose=0)
                latency_ms = ((time.time() - t0) * 1000.0) / min(val_rows_count, 32)
                metrics["latency_ms_per_row"] = float(latency_ms)

                model_id = f"scrap_classifier__lstm_attention_dual__{_safe_segment_token(segment)}__{int(time.time()*1000)}"
                os.makedirs(BUNDLES_DIR, exist_ok=True)
                keras_model_path = os.path.join(BUNDLES_DIR, f"{model_id}.keras")
                model.save(keras_model_path, include_optimizer=False)

                artifact_payload = {
                    "model_id": model_id,
                    "family": "lstm_attention_dual",
                    "task": "scrap_classifier",
                    "model_path": keras_model_path,
                    "sequence_scaler": sequence_scaler,
                    "sequence_length": int(config.sequence_length),
                    "horizon_cycles": int(config.horizon_cycles),
                    "sensor_cols": sensor_cols,
                    "feature_spec_hash": spec_hash,
                    "feature_spec": feature_spec,
                    "decision_threshold": threshold,
                    "metrics": metrics,
                    "model_name": "LSTM-Hyper",
                    "model_label": "LSTM-Scrap-AI-Core (TensorFlow 2.15+)",
                    "model_version": model_id,
                    "xai_method": "hybrid_attention_shap",
                    "background_samples": lstm_candidate.get("background_samples"),
                }
                artifact_path = _save_bundle_artifact(model_id, artifact_payload)

                bundle = {
                    "model_id": model_id,
                    "task": "scrap_classifier",
                    "family": "lstm_attention_dual",
                    "machine_id": machine_id,
                    "part_number": part_number,
                    "segment_id": segment,
                    "segment_scope": unit.get("scope"),
                    "feature_cols": feature_cols,
                    "feature_spec_hash": spec_hash,
                    "metrics": metrics,
                    "trained_at": _now_iso(),
                    "artifact_path": artifact_path,
                    "sequence_length": int(config.sequence_length),
                    "horizon_cycles": int(config.horizon_cycles),
                    "sensor_cols": sensor_cols,
                    "artifact_paths": {
                        "metadata": artifact_path,
                        "keras_model": keras_model_path,
                    },
                    "xai_method": "hybrid_attention_shap",
                }
                register_model_bundle(registry, "scrap_classifier", model_id, bundle)

                incumbent_id, _ = resolve_active_model_id(registry, "scrap_classifier", machine_id, part_number)
                incumbent = registry.get("models", {}).get(incumbent_id) if incumbent_id else None
                recommended = (
                    latency_ms <= config.latency_budget_ms
                    and _promote_candidate(config, {"metrics": metrics}, incumbent, "scrap_classifier")
                )
                benchmark_rows.append(
                    {
                        "task": "scrap_classifier",
                        "segment_id": segment,
                        "model_id": model_id,
                        "family": "lstm_attention_dual",
                        "segment_scope": unit.get("scope"),
                        "metrics": metrics,
                        "recommended": bool(recommended),
                    }
                )
                if auto_promote and recommended:
                    from model_registry import promote_model

                    promoted_rows.append(promote_model(registry, "scrap_classifier", model_id, machine_id, part_number))

        for family in ["lightgbm", "arima", "prophet", "lstm"]:
            model = _fit_forecaster(
                family,
                x_train=x_train,
                y_train=y_train_reg,
                sensor_cols=sensor_cols,
                df_train_rows=train_rows,
            )
            if model is None:
                continue
            t0 = time.time()
            pred = _predict_forecaster(
                family,
                model=model,
                x_val=x_val,
                y_template=y_val_reg,
                sensor_cols=sensor_cols,
                df_val_rows=val_rows,
            )
            latency_ms = ((time.time() - t0) * 1000.0) / max(1, len(x_val))
            metrics = _forecast_metrics(np.asarray(y_val_reg), pred, sensor_cols=sensor_cols)
            metrics["latency_ms_per_row"] = float(latency_ms)
            model_id = f"sensor_forecaster__{family}__{_safe_segment_token(segment)}__{int(time.time()*1000)}"
            artifact_payload = {
                "model": model,
                "scaler": scaler,
                "feature_cols": feature_cols,
                "feature_spec": feature_spec,
                "feature_spec_hash": spec_hash,
                "family": family,
                "task": "sensor_forecaster",
                "metrics": metrics,
                "sensor_cols": sensor_cols,
            }
            artifact_path = _save_bundle_artifact(model_id, artifact_payload)
            bundle = {
                "model_id": model_id,
                "task": "sensor_forecaster",
                "family": family,
                "machine_id": machine_id,
                "part_number": part_number,
                "segment_id": segment,
                "segment_scope": unit.get("scope"),
                "feature_cols": feature_cols,
                "feature_spec_hash": spec_hash,
                "metrics": metrics,
                "trained_at": _now_iso(),
                "artifact_path": artifact_path,
            }
            register_model_bundle(registry, "sensor_forecaster", model_id, bundle)

            incumbent_id, _ = resolve_active_model_id(registry, "sensor_forecaster", machine_id, part_number)
            incumbent = registry.get("models", {}).get(incumbent_id) if incumbent_id else None
            recommended = (
                latency_ms <= config.latency_budget_ms
                and _promote_candidate(config, {"metrics": metrics}, incumbent, "sensor_forecaster")
            )
            benchmark_rows.append(
                {
                    "task": "sensor_forecaster",
                    "segment_id": segment,
                    "model_id": model_id,
                    "family": family,
                    "segment_scope": unit.get("scope"),
                    "metrics": metrics,
                    "recommended": bool(recommended),
                }
            )
            if auto_promote and recommended:
                from model_registry import promote_model

                promoted_rows.append(promote_model(registry, "sensor_forecaster", model_id, machine_id, part_number))

    save_registry(registry)
    benchmark_payload = {
        "generated_at": _now_iso(),
        "dataset": data_meta,
        "feature_spec_hash": spec_hash,
        "training_units": len(units),
        "skipped_units": skipped_units,
        "benchmark_rows": benchmark_rows,
        "promoted": promoted_rows,
        "duration_seconds": round(time.time() - started, 3),
    }
    os.makedirs(os.path.dirname(BENCHMARK_PATH), exist_ok=True)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(benchmark_payload, f, indent=2)

    return {"ok": True, **benchmark_payload}


def load_latest_benchmark() -> Dict[str, Any]:
    if not os.path.exists(BENCHMARK_PATH):
        return {"ok": False, "error": "No benchmark report found"}
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
