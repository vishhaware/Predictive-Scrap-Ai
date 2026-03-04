#!/usr/bin/env python3
"""
PHASE 3: Load Testing Tool

Simulates concurrent user traffic to identify bottlenecks and maximum capacity.
Usage:
    python api_load_testing.py --base-url http://localhost:8000 --concurrency 10 --duration 30 --json-report report.json
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import statistics
import random

import httpx


@dataclass
class LoadTestMetrics:
    """Aggregate metrics for load test run"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time_seconds: float
    requests_per_second: float
    min_response_ms: float
    max_response_ms: float
    mean_response_ms: float
    median_response_ms: float
    p95_response_ms: float
    p99_response_ms: float
    std_dev_ms: float
    concurrent_users: int
    error_distribution: Dict[str, int]


class LoadTester:
    """Performs load testing on API endpoints"""

    # Mix of endpoints simulating real user behavior
    ENDPOINT_MIX = [
        ("GET", "/api/health", None, 0.5),  # 50% health checks (lightweight)
        ("GET", "/api/machines", None, 2.0),  # 20% list machines
        ("GET", "/api/machines/M001", None, 1.5),  # 15% get machine details
        ("GET", "/api/machines/M001/chart-data", None, 1.0),  # 10% chart data
        ("GET", "/api/machines/M001/control-room", None, 1.0),  # 10% control room
        ("GET", "/api/ai/metrics-dashboard", None, 0.5),  # 5% metrics
    ]

    def __init__(
        self,
        base_url: str,
        concurrency: int = 10,
        duration_seconds: int = 30,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.concurrency = concurrency
        self.duration_seconds = duration_seconds
        self.timeout = timeout
        self.response_times: List[float] = []
        self.errors: Dict[str, int] = {}
        self.start_time: float = 0
        self.stop_time: float = 0

    def choose_random_endpoint(self) -> tuple[str, str, Optional[dict]]:
        """Choose an endpoint weighted by frequency"""
        total_weight = sum(w for _, _, _, w in self.ENDPOINT_MIX)
        choice = random.uniform(0, total_weight)
        current = 0

        for method, path, json_data, weight in self.ENDPOINT_MIX:
            current += weight
            if choice <= current:
                return method, path, json_data

        return self.ENDPOINT_MIX[0][0], self.ENDPOINT_MIX[0][1], None

    async def make_request(self, method: str, path: str, json_data: Optional[dict] = None) -> tuple[float, str]:
        """Make a single request, return (response_time_ms, error_type or 'OK')"""
        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                start = time.perf_counter()

                if method == "GET":
                    response = await client.get(url)
                elif method == "POST":
                    response = await client.post(url, json=json_data or {})
                else:
                    return 0, f"BadMethod:{method}"

                elapsed_ms = (time.perf_counter() - start) * 1000

                if response.status_code == 200:
                    return elapsed_ms, "OK"
                else:
                    return elapsed_ms, f"HTTP{response.status_code}"

        except httpx.TimeoutException:
            return self.timeout * 1000, "Timeout"
        except httpx.ConnectError:
            return 0, "ConnectError"
        except Exception as e:
            return 0, f"Error:{type(e).__name__}"

    async def worker(self, worker_id: int):
        """Worker that continuously makes requests for the duration"""
        requests_made = 0

        while time.perf_counter() - self.start_time < self.duration_seconds:
            method, path, json_data = self.choose_random_endpoint()
            response_time_ms, error = await self.make_request(method, path, json_data)

            self.response_times.append(response_time_ms)
            self.errors[error] = self.errors.get(error, 0) + 1

            if error != "OK":
                print(f"  [Worker {worker_id}] ✗ {error} on {method} {path[:40]}")

            requests_made += 1

        print(f"  Worker {worker_id}: {requests_made} requests")

    async def run_load_test(self) -> LoadTestMetrics:
        """Run the load test with concurrent workers"""
        print(f"\n🔥 Starting Load Test")
        print(f"   Base URL: {self.base_url}")
        print(f"   Concurrent Users: {self.concurrency}")
        print(f"   Duration: {self.duration_seconds} seconds")
        print(f"   Request Mix: Health/Machines/Charts/Metrics")
        print("\n   Starting workers...")

        self.start_time = time.perf_counter()

        # Create worker tasks
        workers = [self.worker(i) for i in range(self.concurrency)]

        # Run all workers concurrently
        try:
            await asyncio.gather(*workers)
        except KeyboardInterrupt:
            print("\n⚠️  Load test interrupted")

        self.stop_time = time.perf_counter()

        # Calculate metrics
        total_time = self.stop_time - self.start_time
        ok_requests = self.errors.get("OK", 0)
        total_requests = len(self.response_times)
        failed_requests = total_requests - ok_requests

        response_times_sorted = sorted(self.response_times)
        response_times_ok = sorted([t for t, e in zip(self.response_times, self.errors.keys()) if e == "OK"])

        metrics = LoadTestMetrics(
            total_requests=total_requests,
            successful_requests=ok_requests,
            failed_requests=failed_requests,
            total_time_seconds=total_time,
            requests_per_second=total_requests / total_time if total_time > 0 else 0,
            min_response_ms=min(self.response_times) if self.response_times else 0,
            max_response_ms=max(self.response_times) if self.response_times else 0,
            mean_response_ms=statistics.mean(self.response_times) if self.response_times else 0,
            median_response_ms=statistics.median(self.response_times) if self.response_times else 0,
            p95_response_ms=(
                response_times_sorted[int(len(response_times_sorted) * 0.95)]
                if response_times_sorted
                else 0
            ),
            p99_response_ms=(
                response_times_sorted[int(len(response_times_sorted) * 0.99)]
                if response_times_sorted
                else 0
            ),
            std_dev_ms=statistics.stdev(self.response_times) if len(self.response_times) > 1 else 0,
            concurrent_users=self.concurrency,
            error_distribution=self.errors,
        )

        return metrics

    def print_summary(self, metrics: LoadTestMetrics):
        """Print load test summary"""
        print("\n" + "=" * 100)
        print("LOAD TEST RESULTS")
        print("=" * 100)

        print(f"\n📊 Test Configuration:")
        print(f"   Concurrent Users: {metrics.concurrent_users}")
        print(f"   Duration: {metrics.total_time_seconds:.2f} seconds")

        print(f"\n📈 Throughput:")
        print(f"   Total Requests: {metrics.total_requests}")
        print(f"   Successful: {metrics.successful_requests} ({metrics.successful_requests*100/metrics.total_requests:.1f}%)")
        print(f"   Failed: {metrics.failed_requests} ({metrics.failed_requests*100/metrics.total_requests:.1f}%)")
        print(f"   Throughput: {metrics.requests_per_second:.2f} req/sec")

        print(f"\n⏱️  Response Times:")
        print(f"   Min: {metrics.min_response_ms:.2f}ms")
        print(f"   Max: {metrics.max_response_ms:.2f}ms")
        print(f"   Mean: {metrics.mean_response_ms:.2f}ms")
        print(f"   Median: {metrics.median_response_ms:.2f}ms")
        print(f"   P95: {metrics.p95_response_ms:.2f}ms")
        print(f"   P99: {metrics.p99_response_ms:.2f}ms")
        print(f"   Std Dev: {metrics.std_dev_ms:.2f}ms")

        print(f"\n❌ Error Distribution:")
        for error_type, count in sorted(metrics.error_distribution.items(), key=lambda x: x[1], reverse=True):
            if error_type == "OK":
                print(f"   ✓ {error_type}: {count}")
            else:
                pct = count * 100 / metrics.total_requests
                print(f"   ✗ {error_type}: {count} ({pct:.1f}%)")

        print("\n" + "=" * 100)

        # Health assessment
        if metrics.failed_requests == 0 and metrics.mean_response_ms < 100:
            print("✅ EXCELLENT: API handles load well")
        elif metrics.failed_requests == 0 and metrics.mean_response_ms < 500:
            print("🟡 ACCEPTABLE: API handles load but response times are moderate")
        elif metrics.failed_requests * 100 / metrics.total_requests < 10:
            print("🟠 NEEDS OPTIMIZATION: Some failures/slow responses under load")
        else:
            print("🔴 FAILING: High error rate or very slow responses")

    def export_json(self, metrics: LoadTestMetrics, filepath: str):
        """Export results to JSON"""
        data = {
            "base_url": self.base_url,
            "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "metrics": asdict(metrics),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        print(f"✅ Report exported to: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="API Load Testing Tool")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent users (default: 10)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration of test in seconds (default: 30)",
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

    tester = LoadTester(
        base_url=args.base_url,
        concurrency=args.concurrency,
        duration_seconds=args.duration,
        timeout=args.timeout,
    )

    try:
        metrics = await tester.run_load_test()
        tester.print_summary(metrics)

        if args.json_report:
            tester.export_json(metrics, args.json_report)

    except KeyboardInterrupt:
        print("\n\n⚠️  Load test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
