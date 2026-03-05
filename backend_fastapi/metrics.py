#!/usr/bin/env python3
"""
Prometheus metrics helpers for FastAPI endpoints.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


PROMETHEUS_ENABLED = False
_IMPORT_ERROR: Optional[str] = None

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest  # type: ignore

    PROMETHEUS_ENABLED = True
except Exception as exc:  # pragma: no cover - optional dependency
    _IMPORT_ERROR = str(exc)
    Counter = Gauge = Histogram = None  # type: ignore
    generate_latest = None  # type: ignore


if PROMETHEUS_ENABLED:
    chart_data_requests = Counter(
        "chart_data_requests_total",
        "Total chart-data requests",
        ["endpoint", "machine_id", "status"],
    )
    chart_data_latency = Histogram(
        "chart_data_latency_seconds",
        "Chart-data response latency",
        ["endpoint", "machine_id"],
    )
    lstm_inference_time = Histogram(
        "lstm_inference_seconds",
        "LSTM inference latency",
        ["machine_id"],
    )
    cache_hits = Counter(
        "cache_hits_total",
        "Chart-data cache hit count",
        ["endpoint", "machine_id"],
    )
    data_freshness_minutes = Gauge(
        "data_freshness_minutes",
        "Minutes since latest cleaned row",
        ["machine_id"],
    )
else:  # pragma: no cover - optional dependency
    chart_data_requests = None
    chart_data_latency = None
    lstm_inference_time = None
    cache_hits = None
    data_freshness_minutes = None


def metrics_enabled() -> bool:
    return bool(PROMETHEUS_ENABLED)


def metrics_import_error() -> Optional[str]:
    return _IMPORT_ERROR


def observe_chart_data_request(
    *,
    endpoint: str,
    machine_id: str,
    status_code: int,
    latency_seconds: float,
    cache_hit: bool = False,
) -> None:
    if not PROMETHEUS_ENABLED:
        return
    status = str(int(status_code))
    chart_data_requests.labels(endpoint=endpoint, machine_id=machine_id, status=status).inc()
    chart_data_latency.labels(endpoint=endpoint, machine_id=machine_id).observe(max(0.0, float(latency_seconds)))
    if cache_hit:
        cache_hits.labels(endpoint=endpoint, machine_id=machine_id).inc()


def observe_lstm_inference(*, machine_id: str, latency_seconds: float) -> None:
    if not PROMETHEUS_ENABLED:
        return
    lstm_inference_time.labels(machine_id=machine_id).observe(max(0.0, float(latency_seconds)))


def set_data_freshness(*, machine_id: str, freshness_minutes: float) -> None:
    if not PROMETHEUS_ENABLED:
        return
    data_freshness_minutes.labels(machine_id=machine_id).set(max(0.0, float(freshness_minutes)))


def get_metrics_payload() -> bytes:
    if PROMETHEUS_ENABLED:
        return generate_latest()
    err = (_IMPORT_ERROR or "prometheus_client_not_installed").replace("\n", " ").replace('"', "'")
    fallback = (
        "# HELP app_metrics_enabled Prometheus client availability (1=enabled,0=disabled)\n"
        "# TYPE app_metrics_enabled gauge\n"
        "app_metrics_enabled 0\n"
        "# HELP app_metrics_import_error Import error marker (always 1 when disabled)\n"
        "# TYPE app_metrics_import_error gauge\n"
        f"app_metrics_import_error{{reason=\"{err}\"}} 1\n"
    )
    return fallback.encode("utf-8")


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self._start)


def health_payload() -> Dict[str, Any]:
    return {
        "enabled": PROMETHEUS_ENABLED,
        "import_error": _IMPORT_ERROR,
    }
