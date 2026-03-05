import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch_metrics(base_url: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/admin/chart-rollout-metrics"
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor chart-data-v2 rollout health.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--fallback-threshold", type=float, default=0.20)
    parser.add_argument("--max-http-5xx", type=int, default=0)
    parser.add_argument("--max-empty-past", type=int, default=50)
    args = parser.parse_args()

    try:
        payload = fetch_metrics(args.base_url)
    except urllib.error.URLError as exc:
        print(f"ERROR: failed to fetch rollout metrics: {exc}")
        return 2
    except Exception as exc:
        print(f"ERROR: unexpected monitoring failure: {exc}")
        return 2

    v2 = payload.get("v2", {})
    fallback = payload.get("fallback", {})

    fallback_rate = float(fallback.get("fallback_rate", 0.0))
    http_5xx = int(v2.get("http_5xx", 0))
    empty_past = int(v2.get("empty_past", 0))

    print("chart-data-v2 rollout metrics")
    print("-" * 80)
    print(f"generated_at:       {payload.get('generated_at')}")
    print(f"v2.requests:        {v2.get('requests')}")
    print(f"v2.success_rate:    {v2.get('success_rate')}")
    print(f"v2.http_5xx:        {http_5xx}")
    print(f"v2.empty_past:      {empty_past}")
    print(f"v2.seam_false:      {v2.get('seam_false')}")
    print(f"fallback.hits:      {fallback.get('legacy_fallback_hits')}")
    print(f"fallback.rate:      {fallback_rate}")
    print(f"latency.avg(ms):    {v2.get('latency_ms_avg')}")
    print(f"latency.p95(ms):    {v2.get('latency_ms_p95')}")
    print("-" * 80)

    problems = []
    if fallback_rate > float(args.fallback_threshold):
        problems.append(f"fallback_rate {fallback_rate:.3f} > {args.fallback_threshold:.3f}")
    if http_5xx > int(args.max_http_5xx):
        problems.append(f"http_5xx {http_5xx} > {args.max_http_5xx}")
    if empty_past > int(args.max_empty_past):
        problems.append(f"empty_past {empty_past} > {args.max_empty_past}")

    if problems:
        print("ALERT:")
        for item in problems:
            print(f"- {item}")
        return 1

    print("OK: rollout health within configured thresholds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
