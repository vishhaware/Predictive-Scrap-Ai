#!/usr/bin/env python3
"""
Analyze Locust CSV outputs and print latency/error summaries.

Usage:
  python analyze_load_test.py --stats results_stats.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def analyze(stats_file: Path) -> dict:
    if not stats_file.exists():
        raise FileNotFoundError(f"Missing file: {stats_file}")

    df = pd.read_csv(stats_file)
    if df.empty:
        return {"ok": False, "message": "No rows in stats file."}

    # Locust CSV schema can vary by version; use robust lookups.
    req_col = "# requests" if "# requests" in df.columns else "Request Count"
    fail_col = "# failures" if "# failures" in df.columns else "Failure Count"
    avg_col = "Average Response Time" if "Average Response Time" in df.columns else "Average"
    p95_col = "95%" if "95%" in df.columns else ("95th percentile" if "95th percentile" in df.columns else None)
    rps_col = "Requests/s" if "Requests/s" in df.columns else ("req/s" if "req/s" in df.columns else None)

    total_requests = float(df[req_col].fillna(0).sum()) if req_col in df.columns else 0.0
    total_failures = float(df[fail_col].fillna(0).sum()) if fail_col in df.columns else 0.0
    avg_ms = float(df[avg_col].fillna(0).mean()) if avg_col in df.columns else 0.0
    p95_ms = float(df[p95_col].fillna(0).mean()) if p95_col and p95_col in df.columns else 0.0
    max_rps = float(df[rps_col].fillna(0).max()) if rps_col and rps_col in df.columns else 0.0
    error_rate = (total_failures / max(1.0, total_requests)) * 100.0

    return {
        "ok": True,
        "rows": int(len(df)),
        "total_requests": int(total_requests),
        "total_failures": int(total_failures),
        "error_rate_percent": round(error_rate, 4),
        "avg_response_ms": round(avg_ms, 3),
        "p95_response_ms": round(p95_ms, 3),
        "max_throughput_rps": round(max_rps, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Locust CSV stats.")
    parser.add_argument("--stats", default="results_stats.csv", help="Path to Locust stats CSV file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = analyze(Path(args.stats))
    if not result.get("ok"):
        print(result.get("message", "Unknown error"))
        return
    print("Load Test Summary")
    print(f"  Requests: {result['total_requests']}")
    print(f"  Failures: {result['total_failures']}")
    print(f"  Error rate: {result['error_rate_percent']}%")
    print(f"  Avg latency: {result['avg_response_ms']} ms")
    print(f"  P95 latency: {result['p95_response_ms']} ms")
    print(f"  Max throughput: {result['max_throughput_rps']} req/s")


if __name__ == "__main__":
    main()
