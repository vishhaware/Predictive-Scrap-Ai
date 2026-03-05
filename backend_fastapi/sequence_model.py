import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd

try:
    import tensorflow as tf
except Exception:
    tf = None

try:
    import shap
except Exception:
    shap = None

try:
    from model_registry import get_model_bundle, load_registry, resolve_active_model_id
except ImportError:
    from .model_registry import get_model_bundle, load_registry, resolve_active_model_id

logger = logging.getLogger(__name__)


DEFAULT_SENSOR_COLUMNS = [
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

RAW_TO_FRONTEND_SENSOR_MAP: Dict[str, str] = {
    "Cushion": "cushion",
    "Injection_time": "injection_time",
    "Dosage_time": "dosage_time",
    "Injection_pressure": "injection_pressure",
    "Switch_pressure": "switch_pressure",
    "Switch_position": "switch_position",
    "Cycle_time": "cycle_time",
    "Cyl_tmp_z1": "temp_z1",
    "Cyl_tmp_z2": "temp_z2",
    "Cyl_tmp_z3": "temp_z3",
    "Cyl_tmp_z4": "temp_z4",
    "Cyl_tmp_z5": "temp_z5",
    "Cyl_tmp_z6": "temp_z6",
    "Cyl_tmp_z7": "temp_z7",
    "Cyl_tmp_z8": "temp_z8",
    "Shot_size": "shot_size",
    "Ejector_fix_deviation_torque": "ejector_torque",
    "Extruder_start_position": "extruder_start_position",
    "Extruder_torque": "extruder_torque",
    "Peak_pressure_time": "peak_pressure_time",
    "Peak_pressure_position": "peak_pressure_position",
    "Scrap_counter": "scrap_counter",
    "Shot_counter": "shot_counter",
}
FRONTEND_TO_RAW_SENSOR_MAP = {
    frontend_key: raw_name for raw_name, frontend_key in RAW_TO_FRONTEND_SENSOR_MAP.items()
}
RAW_SENSOR_LOWER_MAP = {raw.lower(): raw for raw in RAW_TO_FRONTEND_SENSOR_MAP.keys()}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    if np.isnan(out):
        return None
    return out


def _risk_level(probability: float) -> str:
    if probability >= 0.9:
        return "VERY_HIGH"
    if probability >= 0.7:
        return "HIGH"
    if probability >= 0.4:
        return "ELEVATED"
    return "NORMAL"


class _TTLCache:
    def __init__(self, max_size: int, ttl_seconds: int) -> None:
        self.max_size = max(16, int(max_size))
        self.ttl_seconds = max(5, int(ttl_seconds))
        self._data: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()
        self._lock = threading.Lock()

    def _purge_expired(self) -> None:
        now = time.time()
        stale = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl_seconds]
        for key in stale:
            self._data.pop(key, None)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._purge_expired()
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if time.time() - ts > self.ttl_seconds:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return dict(value)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._purge_expired()
            self._data[key] = (time.time(), dict(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


@dataclass
class _NormalizedSequence:
    arr: np.ndarray
    missing_features: List[str]
    missing_feature_ratio: float
    seq_len: int


class SequenceModelService:
    """
    Sequence model runtime for scrap prediction and explainability.
    Supports:
    - LSTM + attention inference
    - On-demand SHAP with timeout
    - TTL caches for predict and explain payloads
    """

    def __init__(
        self,
        models_dir: str,
        default_model_path: Optional[str] = None,
        cache_size: int = 512,
        cache_ttl_seconds: int = 120,
    ) -> None:
        self.models_dir = models_dir
        self.default_model_path = default_model_path or os.path.join(models_dir, "lstm_scrap_risk.h5")
        self._predict_cache = _TTLCache(max_size=cache_size, ttl_seconds=cache_ttl_seconds)
        self._explain_cache = _TTLCache(max_size=max(64, cache_size // 2), ttl_seconds=max(30, cache_ttl_seconds))
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shap-xai")
        self._lock = threading.Lock()

        self._loaded = False
        self._model: Any = None
        self._event_model: Any = None
        self._attention_model: Any = None
        self._sequence_scaler: Any = None
        self._background_samples: Optional[np.ndarray] = None
        self._last_load_error: str = ""
        self._last_reported_unavailable_reason: str = ""
        self._meta: Dict[str, Any] = {
            "model_id": None,
            "model_name": "LSTM-Hyper",
            "model_version": None,
            "model_label": "LSTM-Scrap-AI-Core (TensorFlow 2.15+)",
            "model_family": "lstm_attention_dual",
            "segment_scope": "global",
            "feature_spec_hash": None,
            "decision_threshold": 0.5,
            "sensor_cols": list(DEFAULT_SENSOR_COLUMNS),
            "sequence_length": 30,
            "horizon_cycles": 30,
            "xai_method": "hybrid_attention_shap",
        }

    def close(self) -> None:
        self._predict_cache.clear()
        self._explain_cache.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def is_available(self) -> bool:
        return bool(self._model is not None and tf is not None)

    def unavailable_reason(self) -> str:
        reason = str(self._last_load_error or "").strip()
        if reason:
            return reason
        return "No compatible LSTM model artifact is currently available."

    def _report_unavailable_once(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if not normalized:
            return
        if normalized != self._last_reported_unavailable_reason:
            logger.warning("Sequence model unavailable: %s", normalized)
            self._last_reported_unavailable_reason = normalized

    def refresh(self) -> None:
        with self._lock:
            self._loaded = False
        self.load(force=True)

    def load(self, force: bool = False) -> bool:
        with self._lock:
            if self._loaded and not force:
                return self.is_available()
            self._loaded = True

        self._model = None
        self._event_model = None
        self._attention_model = None
        self._sequence_scaler = None
        self._background_samples = None
        self._last_load_error = ""
        self._predict_cache.clear()
        self._explain_cache.clear()

        if tf is None:
            self._last_load_error = "TensorFlow is unavailable; sequence model service is disabled."
            self._report_unavailable_once(self._last_load_error)
            return False

        registry_error = ""
        fallback_error = ""

        artifact, scope, resolve_reason = self._resolve_lstm_registry_artifact()
        if isinstance(artifact, dict):
            model_path = str(artifact.get("model_path") or "")
            if model_path and os.path.exists(model_path):
                try:
                    self._model = tf.keras.models.load_model(model_path, compile=False)
                    self._sequence_scaler = artifact.get("sequence_scaler")
                    bg = artifact.get("background_samples")
                    if bg is not None:
                        bg_arr = np.asarray(bg, dtype=np.float32)
                        if bg_arr.ndim == 3 and bg_arr.size > 0:
                            self._background_samples = bg_arr
                    self._meta.update(
                        {
                            "model_id": artifact.get("model_id"),
                            "model_name": artifact.get("model_name") or "LSTM-Hyper",
                            "model_version": artifact.get("model_version") or artifact.get("model_id"),
                            "model_label": artifact.get("model_label") or "LSTM-Scrap-AI-Core (TensorFlow 2.15+)",
                            "model_family": artifact.get("family") or "lstm_attention_dual",
                            "segment_scope": scope,
                            "feature_spec_hash": artifact.get("feature_spec_hash"),
                            "decision_threshold": float(artifact.get("decision_threshold", 0.5)),
                            "sensor_cols": list(artifact.get("sensor_cols") or self._meta["sensor_cols"]),
                            "sequence_length": int(artifact.get("sequence_length", 30)),
                            "horizon_cycles": int(artifact.get("horizon_cycles", 30)),
                            "xai_method": artifact.get("xai_method") or "hybrid_attention_shap",
                        }
                    )
                except Exception as exc:
                    registry_error = f"Failed to load LSTM registry model at '{model_path}': {exc}"
            else:
                registry_error = f"LSTM registry artifact is missing model_path or file does not exist: {model_path or '<empty>'}."
        else:
            registry_error = resolve_reason

        if self._model is None and os.path.exists(self.default_model_path):
            try:
                self._model = tf.keras.models.load_model(self.default_model_path, compile=False)
                self._meta.update(
                    {
                        "model_id": "legacy_lstm_h5",
                        "model_version": "legacy_lstm_h5",
                        "model_family": "lstm_h5",
                        "segment_scope": "global",
                    }
                )
            except Exception as exc:
                fallback_error = f"Failed to load fallback LSTM model at '{self.default_model_path}': {exc}"

        if self._model is None:
            if not fallback_error and not os.path.exists(self.default_model_path):
                fallback_error = f"Fallback LSTM model file not found at '{self.default_model_path}'."

            reasons = [reason for reason in (registry_error, fallback_error) if str(reason).strip()]
            if not reasons:
                reasons = ["No compatible LSTM model artifact was found."]
            self._last_load_error = " ".join(reasons)
            self._report_unavailable_once(self._last_load_error)
            return False

        self._build_runtime_heads()
        self._last_load_error = ""
        self._last_reported_unavailable_reason = ""
        return True

    def predict(
        self,
        sequence: Sequence[Dict[str, Any]],
        machine_id: str = "unknown",
        horizon_cycles: int = 30,
        part_number: Optional[str] = None,
    ) -> float:
        result = self.predict_batch(
            machine_id=machine_id,
            sequence=sequence,
            horizon_cycles=horizon_cycles,
            part_number=part_number,
            top_k=8,
        )
        return float(result.get("scrap_probability", 0.5))

    def predict_batch(
        self,
        machine_id: str,
        sequence: Sequence[Dict[str, Any]],
        horizon_cycles: int = 30,
        part_number: Optional[str] = None,
        top_k: int = 8,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        if not self.is_available() and not self.load():
            raise RuntimeError(f"LSTM model is not loaded. {self.unavailable_reason()}")

        norm = self._normalize_sequence(sequence, sensor_cols=self._meta["sensor_cols"])
        clamped_horizon = max(5, min(int(horizon_cycles), 120))
        clamped_top_k = max(3, min(int(top_k), 20))
        key = self._cache_key(
            arr=norm.arr,
            machine_id=str(machine_id),
            part_number=part_number,
            horizon_cycles=clamped_horizon,
            top_k=clamped_top_k,
            kind="predict",
        )
        cached = self._predict_cache.get(key)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        event_prob_raw, rate_pred, attn_weights = self._predict_core(norm.arr)
        event_prob_raw = float(_clamp(event_prob_raw, 0.0, 1.0))
        rate_pred = float(_clamp(rate_pred, 0.0, 1.0))
        decision_threshold = float(_clamp(float(self._meta.get("decision_threshold", 0.5)), 0.05, 0.95))
        quality_score = self._compute_input_quality(
            seq_len=norm.seq_len,
            missing_feature_ratio=norm.missing_feature_ratio,
        )
        event_prob = 0.5 + ((event_prob_raw - 0.5) * quality_score)
        event_prob = float(_clamp(event_prob, 0.0, 1.0))
        confidence = float(_clamp(0.35 + (0.65 * quality_score), 0.05, 0.99))
        attention_features, top_timesteps = self._attention_attributions(
            norm.arr, attn_weights, sensor_cols=self._meta["sensor_cols"], top_k=clamped_top_k
        )

        payload: Dict[str, Any] = {
            "machine_id": str(machine_id),
            "part_number": part_number,
            "horizon_cycles": clamped_horizon,
            "sequence_length": norm.seq_len,
            "scrap_probability": round(event_prob, 6),
            "scrap_probability_raw": round(event_prob_raw, 6),
            "expected_scrap_rate": round(rate_pred, 6),
            "decision_threshold": round(decision_threshold, 6),
            "confidence_raw": round(quality_score, 6),
            "confidence": round(confidence, 6),
            "input_quality_score": round(quality_score, 6),
            "degraded_input": bool(quality_score < 0.75),
            "risk_level": _risk_level(event_prob),
            "risk_level_raw": _risk_level(event_prob_raw),
            "model_name": str(self._meta.get("model_name") or "LSTM-Hyper"),
            "model_version": self._meta.get("model_version"),
            "model_label": str(self._meta.get("model_label") or "LSTM-Scrap-AI-Core"),
            "model_family": str(self._meta.get("model_family") or "lstm_attention_dual"),
            "segment_scope": str(self._meta.get("segment_scope") or "global"),
            "feature_spec_hash": self._meta.get("feature_spec_hash"),
            "attention_attributions": attention_features,
            "top_timesteps": top_timesteps,
            "missing_features": norm.missing_features,
            "missing_feature_ratio": round(norm.missing_feature_ratio, 6),
            "cache_hit": False,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        self._predict_cache.set(key, payload)
        return payload

    def explain_prediction(
        self,
        machine_id: str,
        sequence: Sequence[Dict[str, Any]],
        horizon_cycles: int = 30,
        part_number: Optional[str] = None,
        top_k: int = 8,
        shap_timeout_seconds: float = 1.25,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        clamped_top_k = max(3, min(int(top_k), 20))
        clamped_horizon = max(5, min(int(horizon_cycles), 120))

        norm = self._normalize_sequence(sequence, sensor_cols=self._meta["sensor_cols"])
        cache_key = self._cache_key(
            arr=norm.arr,
            machine_id=str(machine_id),
            part_number=part_number,
            horizon_cycles=clamped_horizon,
            top_k=clamped_top_k,
            kind="explain",
        )
        cached = self._explain_cache.get(cache_key)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

        base = self.predict_batch(
            machine_id=machine_id,
            sequence=sequence,
            horizon_cycles=clamped_horizon,
            part_number=part_number,
            top_k=clamped_top_k,
        )

        shap_status = "unavailable"
        shap_features: List[Dict[str, Any]] = []
        if self.is_available() and shap is not None and self._event_model is not None:
            future = self._executor.submit(self._compute_shap_attributions, norm.arr, clamped_top_k)
            try:
                shap_features = future.result(timeout=max(0.25, float(shap_timeout_seconds)))
                shap_status = "ok"
            except FutureTimeoutError:
                shap_status = "timeout"
                future.cancel()
            except Exception as exc:
                shap_status = "unavailable"
                logger.debug("SHAP explain failed: %s", exc)

        combined = self._merge_explanations(
            attention_features=base.get("attention_attributions", []),
            shap_features=shap_features,
            shap_status=shap_status,
            top_k=clamped_top_k,
        )

        explained = dict(base)
        explained.update(
            {
                "shap_attributions": shap_features,
                "combined_explanation": combined,
                "explanation_method": "hybrid_attention_shap",
                "shap_status": shap_status,
                "cache_hit": False,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        )
        self._explain_cache.set(cache_key, explained)
        return explained

    def _resolve_lstm_registry_artifact(self) -> Tuple[Optional[Dict[str, Any]], str, str]:
        try:
            registry = load_registry()
        except Exception as exc:
            return None, "none", f"Failed to load model registry: {exc}"

        model_id, scope = resolve_active_model_id(registry, "scrap_classifier", None, None)
        bundle = get_model_bundle(registry, model_id)
        candidate_bundle: Optional[Dict[str, Any]] = None
        candidate_model_id: Optional[str] = None
        candidate_scope = scope

        if isinstance(bundle, dict) and str(bundle.get("family")) == "lstm_attention_dual":
            candidate_bundle = bundle
            candidate_model_id = model_id
        else:
            models_map = registry.get("models") or {}
            lstm_candidates: List[Tuple[str, Dict[str, Any]]] = []
            for mid, meta in models_map.items():
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("family")) != "lstm_attention_dual":
                    continue
                lstm_candidates.append((str(mid), meta))
            if lstm_candidates:
                lstm_candidates.sort(key=lambda item: str((item[1] or {}).get("trained_at") or ""), reverse=True)
                candidate_model_id, candidate_bundle = lstm_candidates[0]
                candidate_scope = "shadow_latest"

        if not isinstance(candidate_bundle, dict):
            return None, "none", "No LSTM model entries were found in registry."

        artifact_path = candidate_bundle.get("artifact_path")
        if not artifact_path:
            return None, candidate_scope, f"LSTM registry model '{candidate_model_id}' has no artifact_path."
        if not os.path.exists(str(artifact_path)):
            return None, candidate_scope, f"LSTM registry artifact file is missing: {artifact_path}"

        try:
            payload = joblib.load(str(artifact_path))
        except Exception as exc:
            return None, candidate_scope, f"Failed to load LSTM registry artifact '{artifact_path}': {exc}"
        if not isinstance(payload, dict):
            return None, candidate_scope, f"LSTM registry artifact '{artifact_path}' is not a valid payload."
        payload = dict(payload)
        payload.setdefault("model_id", candidate_model_id)
        payload.setdefault("family", candidate_bundle.get("family"))
        payload.setdefault("feature_spec_hash", candidate_bundle.get("feature_spec_hash"))
        payload.setdefault("model_name", "LSTM-Hyper")
        payload.setdefault("model_label", "LSTM-Scrap-AI-Core (TensorFlow 2.15+)")
        return payload, candidate_scope, ""

    def _build_runtime_heads(self) -> None:
        if tf is None or self._model is None:
            return
        model = self._model
        event_tensor = None
        rate_tensor = None
        attention_tensor = None
        model_inputs: List[Any] = []
        model_outputs: List[Any] = []

        def _refresh_model_io() -> None:
            nonlocal model_inputs, model_outputs
            try:
                model_inputs = list(getattr(model, "inputs", []) or [])
            except Exception:
                model_inputs = []
            try:
                model_outputs = list(getattr(model, "outputs", []) or [])
            except Exception:
                model_outputs = []

        _refresh_model_io()
        if not model_inputs or not model_outputs:
            # Keras 3 can load Sequential models without resolved graph tensors.
            seq_len = max(10, int(self._meta.get("sequence_length", 30)))
            feat_count = max(1, len(self._meta.get("sensor_cols") or []))
            dummy = np.zeros((1, seq_len, feat_count), dtype=np.float32)
            try:
                _ = model(dummy, training=False)
            except Exception as exc:
                logger.warning("Sequence model graph warm-up failed: %s", exc)
            _refresh_model_io()

        if not model_inputs or not model_outputs:
            logger.warning("Sequence model has no resolved inputs/outputs; using base model runtime fallback.")
            self._event_model = model
            self._attention_model = model
            return

        with tf.name_scope("sequence_runtime_heads"):
            for layer_name in ("event_prob", "event_probability", "event_output"):
                try:
                    event_tensor = model.get_layer(layer_name).output
                    break
                except Exception:
                    continue

            for layer_name in ("rate_pred", "scrap_rate", "rate_output"):
                try:
                    rate_tensor = model.get_layer(layer_name).output
                    break
                except Exception:
                    continue

            for layer_name in ("attention_weights", "attention", "attn_weights"):
                try:
                    attention_tensor = model.get_layer(layer_name).output
                    break
                except Exception:
                    continue

        outputs = model_outputs
        if event_tensor is None and len(outputs) >= 1:
            event_tensor = outputs[0]
        if rate_tensor is None and len(outputs) >= 2:
            rate_tensor = outputs[1]
        if rate_tensor is None and event_tensor is not None:
            rate_tensor = event_tensor
        if attention_tensor is None and len(outputs) >= 3:
            attention_tensor = outputs[2]

        model_input_tensor: Any = model_inputs if len(model_inputs) > 1 else model_inputs[0]

        if event_tensor is not None:
            try:
                self._event_model = tf.keras.Model(inputs=model_input_tensor, outputs=event_tensor)
            except Exception as exc:
                logger.warning("Failed to build sequence event head model: %s", exc)
                self._event_model = model
        else:
            self._event_model = model

        try:
            if event_tensor is not None and rate_tensor is not None and attention_tensor is not None:
                self._attention_model = tf.keras.Model(
                    inputs=model_input_tensor,
                    outputs=[event_tensor, rate_tensor, attention_tensor],
                )
            elif event_tensor is not None and rate_tensor is not None:
                self._attention_model = tf.keras.Model(inputs=model_input_tensor, outputs=[event_tensor, rate_tensor])
            else:
                self._attention_model = model
        except Exception as exc:
            logger.warning("Failed to build sequence attention head model: %s", exc)
            self._attention_model = model

    def _normalize_sequence(self, sequence: Sequence[Dict[str, Any]], sensor_cols: List[str]) -> _NormalizedSequence:
        if not isinstance(sequence, (list, tuple)) or len(sequence) < 10:
            raise ValueError("sequence must contain at least 10 timesteps.")
        if len(sequence) > 240:
            raise ValueError("sequence cannot exceed 240 timesteps.")

        records: List[Dict[str, float]] = []
        for row in sequence:
            if not isinstance(row, dict):
                continue
            normalized_row: Dict[str, float] = {}
            for key, value in row.items():
                numeric = _safe_float(value)
                if numeric is None:
                    continue
                raw_key = self._to_raw_sensor_key(str(key))
                if raw_key in sensor_cols:
                    normalized_row[raw_key] = float(numeric)
            records.append(normalized_row)

        if len(records) < 10:
            raise ValueError("sequence does not contain enough numeric sensor data after preprocessing.")

        df = pd.DataFrame(records)
        missing_features: List[str] = []
        for col in sensor_cols:
            if col not in df.columns:
                missing_features.append(col)
                df[col] = np.nan
        df = df[sensor_cols]
        df = df.apply(pd.to_numeric, errors="coerce")
        df = df.ffill()
        medians = df.median(numeric_only=True)
        for col in sensor_cols:
            med = _safe_float(medians.get(col))
            df[col] = df[col].fillna(med if med is not None else 0.0)
        df = df.fillna(0.0)

        arr = np.asarray(df.values, dtype=np.float32)
        if self._sequence_scaler is not None:
            try:
                arr = np.asarray(self._sequence_scaler.transform(arr), dtype=np.float32)
            except Exception as exc:
                logger.debug("Failed to apply sequence scaler: %s", exc)
        arr = arr.reshape((1, arr.shape[0], arr.shape[1]))
        missing_ratio = 0.0
        if sensor_cols:
            missing_ratio = float(len(missing_features) / float(len(sensor_cols)))
        return _NormalizedSequence(
            arr=arr,
            missing_features=missing_features,
            missing_feature_ratio=missing_ratio,
            seq_len=int(arr.shape[1]),
        )

    def _compute_input_quality(self, seq_len: int, missing_feature_ratio: float) -> float:
        target_len = max(10, int(self._meta.get("sequence_length", 30)))
        length_score = _clamp(float(seq_len) / float(target_len), 0.0, 1.0)
        feature_score = _clamp(1.0 - float(missing_feature_ratio), 0.0, 1.0)
        quality = (0.6 * feature_score) + (0.4 * length_score)
        return float(_clamp(quality, 0.05, 1.0))

    def _to_raw_sensor_key(self, key: str) -> str:
        key_clean = key.strip()
        if key_clean in FRONTEND_TO_RAW_SENSOR_MAP:
            return FRONTEND_TO_RAW_SENSOR_MAP[key_clean]
        if key_clean in RAW_TO_FRONTEND_SENSOR_MAP:
            return key_clean
        lower = key_clean.lower()
        if lower in RAW_SENSOR_LOWER_MAP:
            return RAW_SENSOR_LOWER_MAP[lower]
        return key_clean

    def _cache_key(
        self,
        arr: np.ndarray,
        machine_id: str,
        part_number: Optional[str],
        horizon_cycles: int,
        top_k: int,
        kind: str,
    ) -> str:
        rounded = np.round(arr, 5)
        payload = {
            "kind": kind,
            "machine_id": machine_id,
            "part_number": part_number,
            "horizon_cycles": horizon_cycles,
            "top_k": top_k,
            "model_version": self._meta.get("model_version"),
            "shape": list(rounded.shape),
            "data_hash": hashlib.sha256(rounded.tobytes()).hexdigest(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _predict_core(self, arr: np.ndarray) -> Tuple[float, float, Optional[np.ndarray]]:
        if self._attention_model is None:
            raise RuntimeError("LSTM runtime model is not prepared.")

        event_prob = 0.5
        rate_pred = 0.0
        attn_weights: Optional[np.ndarray] = None

        try:
            outputs = self._attention_model.predict(arr, verbose=0)
        except Exception as exc:
            logger.warning("Attention model predict failed, trying base model: %s", exc)
            # Fallback to base model
            if self._model is not None:
                try:
                    outputs = self._model.predict(arr, verbose=0)
                except Exception as exc2:
                    logger.error("Base model predict also failed: %s", exc2)
                    return event_prob, rate_pred, attn_weights
            else:
                return event_prob, rate_pred, attn_weights

        if isinstance(outputs, (list, tuple)):
            if len(outputs) >= 1:
                event_prob = float(np.asarray(outputs[0]).reshape(-1)[0])
            if len(outputs) >= 2:
                rate_pred = float(np.asarray(outputs[1]).reshape(-1)[0])
            if len(outputs) >= 3:
                attn_weights = np.asarray(outputs[2], dtype=np.float32)
        else:
            event_prob = float(np.asarray(outputs).reshape(-1)[0])

        return event_prob, rate_pred, attn_weights

    def _attention_attributions(
        self,
        arr: np.ndarray,
        attn_weights: Optional[np.ndarray],
        sensor_cols: List[str],
        top_k: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        seq = np.asarray(arr[0], dtype=np.float32)
        seq_len = int(seq.shape[0])
        feat_count = int(seq.shape[1])
        if seq_len <= 0 or feat_count <= 0:
            return [], []

        if attn_weights is None:
            weights = np.full((seq_len,), fill_value=1.0 / seq_len, dtype=np.float32)
        else:
            weights = np.asarray(attn_weights).reshape(-1)
            if weights.shape[0] != seq_len:
                weights = np.resize(weights, seq_len)
            sum_w = float(np.sum(np.abs(weights)))
            if sum_w <= 1e-8:
                weights = np.full((seq_len,), fill_value=1.0 / seq_len, dtype=np.float32)
            else:
                weights = np.abs(weights) / sum_w

        med = np.median(seq, axis=0)
        std = np.std(seq, axis=0)
        std = np.where(std <= 1e-6, 1.0, std)
        z = (seq - med) / std
        contrib = np.sum(z * weights[:, None], axis=0)

        rows: List[Dict[str, Any]] = []
        for idx, value in enumerate(contrib):
            raw_name = sensor_cols[idx] if idx < len(sensor_cols) else f"feature_{idx}"
            frontend_name = RAW_TO_FRONTEND_SENSOR_MAP.get(raw_name, str(raw_name).lower())
            val = float(value)
            rows.append(
                {
                    "feature": frontend_name,
                    "raw_feature": raw_name,
                    "contribution": float(round(val, 6)),
                    "direction": "positive" if val >= 0 else "negative",
                }
            )

        rows.sort(key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True)
        top_rows = rows[:top_k]

        timestep_order = np.argsort(weights)[::-1][: min(5, seq_len)]
        top_timesteps = [
            {"timestep": int(i + 1), "weight": float(round(float(weights[i]), 6))}
            for i in timestep_order
        ]
        return top_rows, top_timesteps

    def _compute_shap_attributions(self, arr: np.ndarray, top_k: int) -> List[Dict[str, Any]]:
        if shap is None or self._event_model is None or tf is None:
            raise RuntimeError("SHAP backend is unavailable.")

        bg = self._background_samples
        if bg is None or bg.ndim != 3 or bg.shape[-1] != arr.shape[-1]:
            bg = arr.copy()
        if bg.shape[0] > 32:
            bg = bg[:32]

        shap_values = None
        last_error: Optional[Exception] = None
        for explainer_kind in ("deep", "gradient", "kernel"):
            try:
                if explainer_kind == "deep":
                    explainer = shap.DeepExplainer(self._event_model, bg)
                    shap_values = explainer.shap_values(arr)
                elif explainer_kind == "gradient":
                    explainer = shap.GradientExplainer(self._event_model, bg)
                    shap_values = explainer.shap_values(arr)
                else:
                    bg_flat = bg.reshape((bg.shape[0], -1))
                    arr_flat = arr.reshape((arr.shape[0], -1))

                    def _kernel_predict(x_flat: np.ndarray) -> np.ndarray:
                        x = x_flat.reshape((-1, arr.shape[1], arr.shape[2]))
                        y = self._event_model.predict(x, verbose=0)
                        return np.asarray(y).reshape((-1, 1))

                    explainer = shap.KernelExplainer(_kernel_predict, bg_flat)
                    shap_values = explainer.shap_values(arr_flat, nsamples=80)
                break
            except Exception as exc:
                last_error = exc
                shap_values = None

        if shap_values is None:
            raise RuntimeError(f"SHAP explainer failed: {last_error}")

        shap_arr = np.asarray(shap_values)
        if shap_arr.ndim == 4:
            shap_seq = shap_arr[0, 0, :, :]
        elif shap_arr.ndim == 3:
            shap_seq = shap_arr[0, :, :]
        elif shap_arr.ndim == 2:
            shap_seq = shap_arr.reshape((arr.shape[1], arr.shape[2]))
        else:
            shap_seq = np.zeros((arr.shape[1], arr.shape[2]), dtype=np.float32)

        aggregated = np.sum(shap_seq, axis=0)
        rows: List[Dict[str, Any]] = []
        for idx, value in enumerate(aggregated):
            raw_name = self._meta["sensor_cols"][idx] if idx < len(self._meta["sensor_cols"]) else f"feature_{idx}"
            frontend_name = RAW_TO_FRONTEND_SENSOR_MAP.get(raw_name, str(raw_name).lower())
            val = float(value)
            rows.append(
                {
                    "feature": frontend_name,
                    "raw_feature": raw_name,
                    "contribution": float(round(val, 6)),
                    "direction": "positive" if val >= 0 else "negative",
                }
            )
        rows.sort(key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True)
        return rows[:top_k]

    def _merge_explanations(
        self,
        attention_features: List[Dict[str, Any]],
        shap_features: List[Dict[str, Any]],
        shap_status: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}

        for row in attention_features:
            feature = str(row.get("feature", ""))
            if not feature:
                continue
            merged[feature] = {
                "feature": feature,
                "contribution": float(row.get("contribution", 0.0)) * 0.4,
                "sources": ["attention"],
            }

        if shap_status == "ok":
            for row in shap_features:
                feature = str(row.get("feature", ""))
                if not feature:
                    continue
                shap_contrib = float(row.get("contribution", 0.0))
                if feature not in merged:
                    merged[feature] = {"feature": feature, "contribution": 0.0, "sources": []}
                merged[feature]["contribution"] += shap_contrib * 0.6
                merged[feature]["sources"].append("shap")

        rows = list(merged.values())
        for row in rows:
            val = float(row.get("contribution", 0.0))
            row["contribution"] = float(round(val, 6))
            row["direction"] = "positive" if val >= 0 else "negative"

        rows.sort(key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True)
        return rows[:top_k]


_SERVICE: Optional[SequenceModelService] = None
_SERVICE_LOCK = threading.Lock()


def get_sequence_model_service(models_dir: Optional[str] = None) -> SequenceModelService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            base_dir = models_dir or os.path.join(os.path.dirname(__file__), "models")
            _SERVICE = SequenceModelService(models_dir=base_dir)
            _SERVICE.load()
        return _SERVICE
