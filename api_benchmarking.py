#!/usr/bin/env python3
"""
PHASE 3: API Performance Benchmarking Tool

Measures response times, throughput, and identifies bottleneck endpoints.
Usage:
    python api_benchmarking.py --base-url http://localhost:8000 --runs 10 --json-report .runtime/bench-report.json
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import statistics

import httpx


@dataclass
class BenchmarkResult:
    """Single endpoint benchmark result"""
    endpoint: str
    method: str
    runs: int
    min_ms: float
    max_ms: float
    mean_ms: float
    median_ms: float
    std_dev_ms: float
    p95_ms: float
    p99_ms: float
    throughput_rps: float
    status_code: int
    errors: int


class APIBenchmarker:
    """Benchmarks API endpoints for performance"""

    # Define benchmark endpoints grouped by category
    ENDPOINTS = {
        "health": [
            ("GET", "/api/health"),
        ],
        "machines": [
            ("GET", "/api/machines"),
            ("GET", "/api/machines/M001"),
            ("POST", "/api/machines/M001/baseline", {"horizon_minutes": 60}),
        ],
        "cycles": [
            ("GET", "/api/machines/M001/cycles"),
        ],
        "control_room": [
            ("GET", "/api/machines/M001/control-room"),
        ],
        "charts": [
            ("GET", "/api/machines/M001/chart-data?horizon_minutes=120"),
            ("GET", "/api/machines/fleet-chart-data?horizon_minutes=120"),
        ],
        "metrics": [
            ("GET", "/api/ai/metrics-dashboard"),
            ("GET", "/api/ai/metrics-history?window_hours=24"),
        ],
        "validation": [
            ("GET", "/api/admin/validation-rules"),
        ],
        "parameters": [
            ("GET", "/api/admin/parameters"),
        ],
    }

    def __init__(self, base_url: str, runs: int = 10, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.runs = runs
        self.timeout = timeout
        self.results: Dict[str, List[float]] = {}
        self.errors: Dict[str, int] = {}

    async def benchmark_endpoint(
        self, method: str, path: str, json_data: Optional[dict] = None, timeout: float = 30
    ) -> tuple[float, int, Optional[str]]:
        """Benchmark a single endpoint call, return (time_ms, status_code, error)"""
        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                start = time.perf_counter()

                if method == "GET":
                    response = await client.get(url)
                elif method == "POST":
                    response = await client.post(url, json=json_data or {})
                else:
                    return 0, 0, f"Unsupported method: {method}"

                elapsed_ms = (time.perf_counter() - start) * 1000
                return elapsed_ms, response.status_code, None if response.status_code == 200 else f"Status {response.status_code}"

        except httpx.TimeoutException:
            return timeout * 1000, 0, "Timeout"
        except Exception as e:
            return 0, 0, str(e)

    async def benchmark_category(self, category: str, endpoints: List[tuple]):
        """Benchmark all endpoints in a category"""
        print(f"\n📊 Benchmarking {category.upper()} ({len(endpoints)} endpoints) × {self.runs} runs...")

        results = []

        for method, path, *json_data in endpoints:
            json_payload = json_data[0] if json_data else None
            times = []
            status = 0
            errors = 0

            print(f"  {method:4} {path[:50]:<50}", end="", flush=True)

            for run in range(self.runs):
                elapsed_ms, status_code, error = await self.benchmark_endpoint(
                    method, path, json_payload, self.timeout
                )
                times.append(elapsed_ms)
                status = status_code

                if error:
                    errors += 1

            if times:
                times_sorted = sorted(times)
                result = BenchmarkResult(
                    endpoint=path,
                    method=method,
                    runs=self.runs,
                    min_ms=min(times),
                    max_ms=max(times),
                    mean_ms=statistics.mean(times),
                    median_ms=statistics.median(times),
                    std_dev_ms=statistics.stdev(times) if len(times) > 1 else 0,
                    p95_ms=times_sorted[int(len(times_sorted) * 0.95)],
                    p99_ms=times_sorted[int(len(times_sorted) * 0.99)],
                    throughput_rps=1000 / statistics.mean(times) if statistics.mean(times) > 0 else 0,
                    status_code=status,
                    errors=errors,
                )
                results.append(result)

                status_label = "✓" if errors == 0 else "✗"
                print(f" {status_label} mean={result.mean_ms:.2f}ms p95={result.p95_ms:.2f}ms")
            else:
                print(" ✗ FAILED")

        return results

    async def run_all_benchmarks(self) -> Dict[str, List[BenchmarkResult]]:
        """Run all benchmarks"""
        print(f"🚀 Starting API Benchmarks ({self.base_url})")
        print(f"   Runs per endpoint: {self.runs}")
        print(f"   Timeout: {self.timeout}s")

        all_results = {}

        for category, endpoints in self.ENDPOINTS.items():
            all_results[category] = await self.benchmark_category(category, endpoints)

        return all_results

    def print_summary(self, results: Dict[str, List[BenchmarkResult]]):
        """Print benchmark summary"""
        print("\n" + "=" * 100)
        print("BENCHMARK SUMMARY")
        print("=" * 100)

        total_endpoints = 0
        total_errors = 0
        slowest_endpoints = []

        for category, category_results in results.items():
            print(f"\n### {category.upper()}")
            print(f"{'Endpoint':<50} {'Method':<6} {'Mean':<10} {'P95':<10} {'ThroughPut':<12} {'Errors':<8}")
            print("-" * 100)

            for result in category_results:
                total_endpoints += 1
                total_errors += result.errors
                slowest_endpoints.append(result)

                print(
                    f"{result.endpoint:<50} {result.method:<6} "
                    f"{result.mean_ms:>8.2f}ms {result.p95_ms:>8.2f}ms "
                    f"{result.throughput_rps:>10.2f} rps {result.errors:>6}"
                )

        slowest_endpoints.sort(key=lambda x: x.mean_ms, reverse=True)

        print("\n" + "=" * 100)
        print("TOP 5 SLOWEST ENDPOINTS")
        print("=" * 100)
        for result in slowest_endpoints[:5]:
            print(
                f"{result.endpoint:<50} {result.method:<6} "
                f"mean={result.mean_ms:.2f}ms p99={result.p99_ms:.2f}ms"
            )

        print(f"\n📈 Total Endpoints: {total_endpoints}")
        print(f"❌ Total Errors: {total_errors}")

        # Performance classification
        avg_response_times = [
            r.mean_ms
            for category_results in results.values()
            for r in category_results
        ]

        if avg_response_times:
            overall_mean = statistics.mean(avg_response_times)
            if overall_mean < 50:
                rating = "🟢 EXCELLENT (< 50ms)"
            elif overall_mean < 200:
                rating = "🟡 GOOD (50-200ms)"
            elif overall_mean < 500:
                rating = "🟠 MODERATE (200-500ms)"
            else:
                rating = "🔴 SLOW (> 500ms)"

            print(f"\n📊 Overall Rating: {rating}")
            print(f"   Average Response Time: {overall_mean:.2f}ms")

    def export_json(self, results: Dict[str, List[BenchmarkResult]], filepath: str):
        """Export results to JSON"""
        data = {
            "base_url": self.base_url,
            "runs": self.runs,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": {
                category: [asdict(r) for r in category_results]
                for category, category_results in results.items()
            },
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\n✅ Report exported to: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="API Performance Benchmarking Tool")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of runs per endpoint (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--json-report",
        help="Export results to JSON file",
    )

    args = parser.parse_args()

    benchmarker = APIBenchmarker(
        base_url=args.base_url,
        runs=args.runs,
        timeout=args.timeout,
    )

    try:
        results = await benchmarker.run_all_benchmarks()
        benchmarker.print_summary(results)

        if args.json_report:
            benchmarker.export_json(results, args.json_report)

    except KeyboardInterrupt:
        print("\n\n⚠️  Benchmark interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
