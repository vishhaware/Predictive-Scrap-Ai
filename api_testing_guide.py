#!/usr/bin/env python3
"""
Grouped live API test runner for the Manufacturing Analytics backend.

Usage examples:
  python api_testing_guide.py --group all --strict
  python api_testing_guide.py --group 2 --base-url http://127.0.0.1:8000
  python api_testing_guide.py --group 1 --json-report .runtime/api-test-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MACHINE_ID = "M231-11"
DEFAULT_MODEL_ID = "lightgbm_v1"


@dataclass
class TestResult:
    group: str
    name: str
    passed: bool
    status_code: Optional[int]
    duration_ms: int
    message: str


class APITestRunner:
    def __init__(self, base_url: str, strict: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.strict = strict
        self.session = requests.Session()
        self.results: List[TestResult] = []
        self.context: Dict[str, Any] = {}

    def request_json(
        self,
        method: str,
        path: str,
        expected_status: Optional[Any] = None,
        **kwargs: Any,
    ) -> Tuple[requests.Response, Any]:
        url = f"{self.base_url}{path}"
        response = self.session.request(method=method, url=url, timeout=12, **kwargs)

        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if expected_status is not None:
            expected_values: List[int]
            if isinstance(expected_status, (list, tuple, set)):
                expected_values = [int(v) for v in expected_status]
            else:
                expected_values = [int(expected_status)]
            if response.status_code not in expected_values:
                snippet = response.text[:400].replace("\n", " ")
                raise AssertionError(
                    f"{method.upper()} {path} expected {expected_values}, got {response.status_code}. "
                    f"Response: {snippet}"
                )

        return response, payload

    def run_case(self, group: str, name: str, fn: Callable[[], Optional[str]]) -> None:
        start = time.time()
        status_code: Optional[int] = None
        message = ""
        passed = True
        try:
            info = fn()
            if info:
                message = info
        except Exception as exc:
            passed = False
            message = str(exc)
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                status_code = exc.response.status_code
        duration_ms = int((time.time() - start) * 1000)

        result = TestResult(
            group=group,
            name=name,
            passed=passed,
            status_code=status_code,
            duration_ms=duration_ms,
            message=message,
        )
        self.results.append(result)

        marker = "PASS" if passed else "FAIL"
        base_line = f"[{marker}] [G{group}] {name} ({duration_ms} ms)"
        if message:
            print(f"{base_line} - {message}")
        else:
            print(base_line)

    def finalize(self, json_report: Optional[str], selected_groups: List[str]) -> int:
        total = len(self.results)
        failed = len([r for r in self.results if not r.passed])
        passed = total - failed

        print("\n=== API Test Summary ===")
        print(f"Base URL      : {self.base_url}")
        print(f"Groups        : {', '.join(selected_groups)}")
        print(f"Total         : {total}")
        print(f"Passed        : {passed}")
        print(f"Failed        : {failed}")

        if json_report:
            report_path = Path(json_report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "base_url": self.base_url,
                "selected_groups": selected_groups,
                "context": self.context,
                "summary": {"total": total, "passed": passed, "failed": failed},
                "results": [
                    {
                        "group": r.group,
                        "name": r.name,
                        "passed": r.passed,
                        "status_code": r.status_code,
                        "duration_ms": r.duration_ms,
                        "message": r.message,
                    }
                    for r in self.results
                ],
            }
            report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"JSON report    : {report_path}")

        if self.strict and failed > 0:
            return 1
        return 0


def require_keys(obj: Any, keys: List[str], label: str) -> None:
    if not isinstance(obj, dict):
        raise AssertionError(f"{label} should be an object")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AssertionError(f"{label} missing keys: {missing}")


def ensure_baseline_data(runner: APITestRunner) -> Dict[str, Any]:
    _, health = runner.request_json("GET", "/api/health", expected_status=200)
    require_keys(health, ["ok"], "health payload")

    _, machines = runner.request_json("GET", "/api/machines", expected_status=200)
    if not isinstance(machines, list):
        raise AssertionError("/api/machines should return a list")
    if not machines:
        raise AssertionError("Baseline data missing: no machine_stats-derived records available")

    machine_id = DEFAULT_MACHINE_ID
    machine_ids = [m.get("id") for m in machines if isinstance(m, dict) and m.get("id")]
    if machine_id not in machine_ids:
        machine_id = machine_ids[0]

    _, cycles = runner.request_json(
        "GET",
        f"/api/machines/{machine_id}/cycles",
        expected_status=200,
        params={"limit": 1},
    )
    if not isinstance(cycles, list):
        raise AssertionError(f"/api/machines/{machine_id}/cycles should return a list")
    if len(cycles) == 0:
        raise AssertionError(
            f"Baseline data missing: no cycles found for {machine_id}. "
            "Seed or ingest cycle data before running API tests."
        )

    metrics_seeded = False
    _, metrics_payload = runner.request_json(
        "GET",
        f"/api/ai/model-metrics/{DEFAULT_MODEL_ID}",
        expected_status=200,
        params={"machine_id": machine_id},
    )
    metrics_obj = metrics_payload.get("metrics") if isinstance(metrics_payload, dict) else None
    if metrics_obj is None:
        _, compute_payload = runner.request_json(
            "POST",
            "/api/ai/compute-metrics",
            expected_status=200,
            params={"machine_id": machine_id, "window_hours": 24},
        )
        if isinstance(compute_payload, dict) and compute_payload.get("status") in {"success", "no_data"}:
            metrics_seeded = True
        else:
            raise AssertionError("Metrics pre-seed call failed for /api/ai/compute-metrics")

    return {
        "machine_id": machine_id,
        "model_id": DEFAULT_MODEL_ID,
        "metrics_seeded": metrics_seeded,
        "machines_count": len(machines),
    }


def run_group_1(runner: APITestRunner, ctx: Dict[str, Any]) -> None:
    machine_id = str(ctx["machine_id"])
    parameter_name = "API_TEST_CUSHION"

    state: Dict[str, Any] = {}

    def case_list_parameters() -> str:
        _, payload = runner.request_json("GET", "/api/admin/parameters", expected_status=200)
        if not isinstance(payload, list):
            raise AssertionError("/api/admin/parameters should return a list")

        revert_candidate = None
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("parameter_name") == parameter_name and item.get("machine_id") == machine_id:
                if item.get("csv_original_plus") is not None and item.get("csv_original_minus") is not None:
                    revert_candidate = item
                    break

        if revert_candidate:
            state["revert_id"] = revert_candidate.get("id")
        return f"rows={len(payload)}"

    runner.run_case("1", "GET /api/admin/parameters", case_list_parameters)

    def case_create_update_parameter() -> str:
        body = {
            "parameter_name": parameter_name,
            "machine_id": machine_id,
            "part_number": None,
            "tolerance_plus": 0.55,
            "tolerance_minus": -0.45,
            "default_set_value": 3.5,
            "reason": "API grouped integration test",
        }
        _, payload = runner.request_json("POST", "/api/admin/parameters", expected_status=200, json=body)
        require_keys(payload, ["id", "parameter_name", "tolerance_plus", "tolerance_minus", "source"], "parameter upsert")

        state["param_id"] = payload["id"]
        if state.get("revert_id") is None:
            state["revert_id"] = payload["id"]
        if payload.get("parameter_name") != parameter_name:
            raise AssertionError("Unexpected parameter_name in create/update response")
        return f"id={payload['id']}"

    runner.run_case("1", "POST /api/admin/parameters", case_create_update_parameter)

    def case_get_parameter() -> str:
        param_id = state.get("param_id")
        if not param_id:
            raise AssertionError("No parameter id available from create/update test")
        _, payload = runner.request_json("GET", f"/api/admin/parameters/{param_id}", expected_status=200)
        require_keys(payload, ["id", "parameter_name", "tolerance_plus", "tolerance_minus"], "parameter get")
        if int(payload["id"]) != int(param_id):
            raise AssertionError("Parameter ID mismatch in GET response")
        return f"id={param_id}"

    runner.run_case("1", "GET /api/admin/parameters/{id}", case_get_parameter)

    def case_revert_parameter() -> str:
        revert_id = state.get("revert_id")
        if not revert_id:
            raise AssertionError("No parameter id available for revert")
        _, payload = runner.request_json("POST", f"/api/admin/parameters/{revert_id}/revert", expected_status=200)
        require_keys(payload, ["ok", "message"], "parameter revert")
        if payload.get("ok") is not True:
            raise AssertionError("Revert endpoint did not return ok=true")
        return f"id={revert_id}"

    runner.run_case("1", "POST /api/admin/parameters/{id}/revert", case_revert_parameter)

    def case_parameter_history() -> str:
        _, payload = runner.request_json(
            "GET",
            "/api/admin/parameter-history",
            expected_status=200,
            params={"parameter_name": parameter_name, "limit": 20},
        )
        if not isinstance(payload, list):
            raise AssertionError("/api/admin/parameter-history should return a list")
        return f"rows={len(payload)}"

    runner.run_case("1", "GET /api/admin/parameter-history", case_parameter_history)


def run_group_2(runner: APITestRunner, ctx: Dict[str, Any]) -> None:
    machine_id = str(ctx["machine_id"])
    model_id = str(ctx["model_id"])

    def case_get_model_metrics() -> str:
        _, payload = runner.request_json(
            "GET",
            f"/api/ai/model-metrics/{model_id}",
            expected_status=200,
            params={"machine_id": machine_id},
        )
        require_keys(payload, ["model_id"], "model metrics")
        metrics = payload.get("metrics")
        if metrics is not None:
            require_keys(metrics, ["accuracy", "precision", "recall", "f1_score", "samples_count"], "model metrics payload")
        return "metrics endpoint reachable"

    runner.run_case("2", "GET /api/ai/model-metrics/{model_id}", case_get_model_metrics)

    def case_get_metrics_history() -> str:
        _, payload = runner.request_json(
            "GET",
            f"/api/ai/metrics-history/{model_id}",
            expected_status=200,
            params={"machine_id": machine_id, "hours": 24},
        )
        require_keys(payload, ["count", "data"], "metrics history")
        if not isinstance(payload.get("data"), list):
            raise AssertionError("metrics history data should be a list")
        return f"rows={payload.get('count')}"

    runner.run_case("2", "GET /api/ai/metrics-history/{model_id}", case_get_metrics_history)

    def case_model_comparison() -> str:
        _, payload = runner.request_json(
            "GET",
            "/api/ai/model-comparison",
            expected_status=200,
            params={"model_ids": "lightgbm_v1,lstm_attention_dual", "machine_id": machine_id},
        )
        require_keys(payload, ["models"], "model comparison")
        models_map = payload.get("models")
        if not isinstance(models_map, dict):
            raise AssertionError("model comparison 'models' should be an object")
        if "lightgbm_v1" not in models_map:
            raise AssertionError("model comparison missing lightgbm_v1 result")
        return f"models={len(models_map)}"

    runner.run_case("2", "GET /api/ai/model-comparison", case_model_comparison)

    def case_metrics_dashboard() -> str:
        _, payload = runner.request_json(
            "GET",
            "/api/ai/metrics-dashboard",
            expected_status=200,
            params={"hours": 24},
        )
        require_keys(payload, ["fleet_metrics", "per_machine"], "metrics dashboard")
        return "dashboard payload validated"

    runner.run_case("2", "GET /api/ai/metrics-dashboard", case_metrics_dashboard)

    def case_compute_metrics() -> str:
        _, payload = runner.request_json(
            "POST",
            "/api/ai/compute-metrics",
            expected_status=200,
            params={"machine_id": machine_id, "window_hours": 24},
        )
        require_keys(payload, ["status"], "compute metrics response")
        if payload.get("status") not in {"success", "no_data"}:
            raise AssertionError(f"Unexpected compute-metrics status: {payload.get('status')}")
        return f"status={payload.get('status')}"

    runner.run_case("2", "POST /api/ai/compute-metrics", case_compute_metrics)


def run_group_3(runner: APITestRunner, ctx: Dict[str, Any]) -> None:
    machine_id = str(ctx["machine_id"])
    state: Dict[str, Any] = {}

    def case_list_validation_rules() -> str:
        _, payload = runner.request_json("GET", "/api/admin/validation-rules", expected_status=200)
        if not isinstance(payload, list):
            raise AssertionError("/api/admin/validation-rules should return a list")
        return f"rows={len(payload)}"

    runner.run_case("3", "GET /api/admin/validation-rules", case_list_validation_rules)

    def case_create_validation_rule() -> str:
        body = {
            "sensor_name": "Cushion",
            "machine_id": machine_id,
            "rule_type": "RANGE",
            "min_value": 3.0,
            "max_value": 4.2,
            "severity": "WARNING",
        }
        _, payload = runner.request_json("POST", "/api/admin/validation-rules", expected_status=200, json=body)
        require_keys(payload, ["id", "sensor_name", "rule_type", "enabled"], "validation rule create")
        state["rule_id"] = payload["id"]
        return f"id={payload['id']}"

    runner.run_case("3", "POST /api/admin/validation-rules", case_create_validation_rule)

    def case_delete_validation_rule() -> str:
        rule_id = state.get("rule_id")
        if not rule_id:
            raise AssertionError("No validation rule id available for deletion")
        _, payload = runner.request_json("DELETE", f"/api/admin/validation-rules/{rule_id}", expected_status=200)
        require_keys(payload, ["ok", "message"], "validation rule delete")
        if payload.get("ok") is not True:
            raise AssertionError("Delete endpoint did not return ok=true")
        return f"id={rule_id}"

    runner.run_case("3", "DELETE /api/admin/validation-rules/{id}", case_delete_validation_rule)

    def case_delete_validation_rule_invalid() -> str:
        _, payload = runner.request_json(
            "DELETE",
            "/api/admin/validation-rules/99999999",
            expected_status=404,
        )
        if not isinstance(payload, dict):
            raise AssertionError("validation rule invalid delete should return JSON object")
        if "detail" not in payload and "error" not in payload:
            raise AssertionError("validation rule invalid delete missing error message field")
        return "404 verified"

    runner.run_case("3", "DELETE /api/admin/validation-rules/{invalid_id}", case_delete_validation_rule_invalid)


def run_group_4(runner: APITestRunner, ctx: Dict[str, Any]) -> None:
    machine_id = str(ctx["machine_id"])

    def case_data_quality_default() -> str:
        _, payload = runner.request_json(
            "GET",
            f"/api/machines/{machine_id}/data-quality",
            expected_status=200,
            params={"hours": 24},
        )
        require_keys(payload, ["summary", "violations"], "data quality payload")
        if not isinstance(payload.get("violations"), list):
            raise AssertionError("data-quality violations should be a list")
        return f"rows={len(payload.get('violations', []))}"

    runner.run_case("4", "GET /api/machines/{machine_id}/data-quality", case_data_quality_default)

    def case_data_quality_filtered() -> str:
        _, payload = runner.request_json(
            "GET",
            f"/api/machines/{machine_id}/data-quality",
            expected_status=200,
            params={"hours": 24, "severity": "CRITICAL"},
        )
        require_keys(payload, ["summary", "violations"], "filtered data quality payload")
        return "severity filter validated"

    runner.run_case("4", "GET /api/machines/{machine_id}/data-quality?severity=CRITICAL", case_data_quality_filtered)

    def case_data_quality_unknown_machine() -> str:
        # Current implementation returns 200 even for unknown machine IDs.
        _, payload = runner.request_json(
            "GET",
            "/api/machines/UNKNOWN-MACHINE-ID/data-quality",
            expected_status=200,
            params={"hours": 24},
        )
        require_keys(payload, ["summary", "violations"], "unknown-machine data quality payload")
        return "current handling (200) verified"

    runner.run_case("4", "GET /api/machines/{invalid_machine_id}/data-quality", case_data_quality_unknown_machine)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grouped API tests for FastAPI backend")
    parser.add_argument(
        "--group",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Run one group or all groups",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero exit code when any test fails",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Write machine-readable JSON report to this path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_groups = ["1", "2", "3", "4"] if args.group == "all" else [args.group]

    runner = APITestRunner(base_url=args.base_url, strict=args.strict)

    try:
        print("Preparing baseline data and connectivity checks...")
        runner.context.update(ensure_baseline_data(runner))
    except Exception as exc:
        runner.results.append(
            TestResult(
                group="preflight",
                name="baseline_data_preparation",
                passed=False,
                status_code=None,
                duration_ms=0,
                message=str(exc),
            )
        )
        print(f"[FAIL] [preflight] baseline_data_preparation - {exc}")
        return runner.finalize(args.json_report, selected_groups)

    group_map = {
        "1": run_group_1,
        "2": run_group_2,
        "3": run_group_3,
        "4": run_group_4,
    }

    for group in selected_groups:
        print(f"\nRunning Group {group} tests...")
        group_map[group](runner, runner.context)

    return runner.finalize(args.json_report, selected_groups)


if __name__ == "__main__":
    sys.exit(main())
