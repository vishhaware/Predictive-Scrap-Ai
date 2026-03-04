import os
from typing import Any, Dict, Optional, Tuple

import pytest
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_MACHINE_ID = "M231-11"
DEFAULT_MODEL_ID = "lightgbm_v1"


def request_json(
    session: requests.Session,
    method: str,
    path: str,
    expected_status: Optional[Any] = None,
    **kwargs: Any,
) -> Tuple[requests.Response, Any]:
    resp = session.request(method=method, url=f"{BASE_URL}{path}", timeout=12, **kwargs)
    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if expected_status is not None:
        if isinstance(expected_status, (tuple, list, set)):
            allowed = [int(v) for v in expected_status]
        else:
            allowed = [int(expected_status)]
        assert resp.status_code in allowed, (
            f"{method} {path} expected {allowed}, got {resp.status_code}. "
            f"Body: {resp.text[:400]}"
        )

    return resp, payload


def require_keys(obj: Any, keys: list[str], label: str) -> None:
    assert isinstance(obj, dict), f"{label} should be an object"
    missing = [k for k in keys if k not in obj]
    assert not missing, f"{label} missing keys: {missing}"


def ensure_baseline_data(session: requests.Session) -> Dict[str, Any]:
    _, health = request_json(session, "GET", "/api/health", expected_status=200)
    require_keys(health, ["ok"], "health payload")

    _, machines = request_json(session, "GET", "/api/machines", expected_status=200)
    assert isinstance(machines, list), "/api/machines should return a list"
    assert machines, "Baseline data missing: no machine records found"

    machine_ids = [m.get("id") for m in machines if isinstance(m, dict) and m.get("id")]
    machine_id = DEFAULT_MACHINE_ID if DEFAULT_MACHINE_ID in machine_ids else machine_ids[0]

    _, cycles = request_json(
        session,
        "GET",
        f"/api/machines/{machine_id}/cycles",
        expected_status=200,
        params={"limit": 1},
    )
    assert isinstance(cycles, list), "/api/machines/{machine_id}/cycles should return a list"
    assert cycles, f"Baseline data missing: no cycles found for {machine_id}"

    _, metrics_payload = request_json(
        session,
        "GET",
        f"/api/ai/model-metrics/{DEFAULT_MODEL_ID}",
        expected_status=200,
        params={"machine_id": machine_id},
    )
    if isinstance(metrics_payload, dict) and metrics_payload.get("metrics") is None:
        _, compute_payload = request_json(
            session,
            "POST",
            "/api/ai/compute-metrics",
            expected_status=200,
            params={"machine_id": machine_id, "window_hours": 24},
        )
        require_keys(compute_payload, ["status"], "compute metrics payload")
        assert compute_payload.get("status") in {"success", "no_data"}, (
            f"Unexpected compute status: {compute_payload.get('status')}"
        )

    return {"machine_id": machine_id, "model_id": DEFAULT_MODEL_ID}


@pytest.fixture(scope="session")
def session_client() -> requests.Session:
    session = requests.Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def baseline_context(session_client: requests.Session) -> Dict[str, Any]:
    return ensure_baseline_data(session_client)


@pytest.fixture()
def parameter_config(session_client: requests.Session, baseline_context: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "parameter_name": "API_TEST_CUSHION",
        "machine_id": baseline_context["machine_id"],
        "part_number": None,
        "tolerance_plus": 0.55,
        "tolerance_minus": -0.45,
        "default_set_value": 3.5,
        "reason": "pytest group1 upsert",
    }
    _, body = request_json(
        session_client,
        "POST",
        "/api/admin/parameters",
        expected_status=200,
        json=payload,
    )
    require_keys(body, ["id", "parameter_name", "source"], "parameter config upsert")
    return body


@pytest.fixture()
def created_validation_rule(
    session_client: requests.Session,
    baseline_context: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {
        "sensor_name": "Cushion",
        "machine_id": baseline_context["machine_id"],
        "rule_type": "RANGE",
        "min_value": 3.0,
        "max_value": 4.2,
        "severity": "WARNING",
    }
    _, created = request_json(
        session_client,
        "POST",
        "/api/admin/validation-rules",
        expected_status=200,
        json=payload,
    )
    require_keys(created, ["id", "sensor_name", "rule_type"], "validation rule create")

    try:
        yield created
    finally:
        rule_id = created.get("id")
        if rule_id is not None:
            request_json(
                session_client,
                "DELETE",
                f"/api/admin/validation-rules/{rule_id}",
                expected_status=(200, 404),
            )


@pytest.mark.group1
def test_group1_list_parameters(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(session_client, "GET", "/api/admin/parameters", expected_status=200)
    assert isinstance(payload, list)


@pytest.mark.group1
def test_group1_create_or_update_parameter(parameter_config: Dict[str, Any]) -> None:
    assert parameter_config["parameter_name"] == "API_TEST_CUSHION"
    assert "id" in parameter_config


@pytest.mark.group1
def test_group1_get_parameter(session_client: requests.Session, parameter_config: Dict[str, Any]) -> None:
    param_id = parameter_config["id"]
    _, payload = request_json(
        session_client,
        "GET",
        f"/api/admin/parameters/{param_id}",
        expected_status=200,
    )
    require_keys(payload, ["id", "parameter_name", "tolerance_plus", "tolerance_minus"], "parameter get payload")
    assert int(payload["id"]) == int(param_id)


@pytest.mark.group1
def test_group1_revert_parameter(session_client: requests.Session, parameter_config: Dict[str, Any]) -> None:
    param_id = parameter_config["id"]
    _, payload = request_json(
        session_client,
        "POST",
        f"/api/admin/parameters/{param_id}/revert",
        expected_status=200,
    )
    require_keys(payload, ["ok", "message"], "parameter revert payload")
    assert payload["ok"] is True


@pytest.mark.group1
def test_group1_parameter_history(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        "/api/admin/parameter-history",
        expected_status=200,
        params={"parameter_name": "API_TEST_CUSHION", "limit": 20},
    )
    assert isinstance(payload, list)


@pytest.mark.group2
def test_group2_get_model_metrics(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        f"/api/ai/model-metrics/{baseline_context['model_id']}",
        expected_status=200,
        params={"machine_id": baseline_context["machine_id"]},
    )
    require_keys(payload, ["model_id"], "model metrics payload")
    metrics = payload.get("metrics")
    if metrics is not None:
        require_keys(metrics, ["accuracy", "precision", "recall", "f1_score", "samples_count"], "metrics object")


@pytest.mark.group2
def test_group2_get_metrics_history(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        f"/api/ai/metrics-history/{baseline_context['model_id']}",
        expected_status=200,
        params={"machine_id": baseline_context["machine_id"], "hours": 24},
    )
    require_keys(payload, ["count", "data"], "metrics history payload")
    assert isinstance(payload["data"], list)


@pytest.mark.group2
def test_group2_model_comparison(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        "/api/ai/model-comparison",
        expected_status=200,
        params={"model_ids": "lightgbm_v1,lstm_attention_dual", "machine_id": baseline_context["machine_id"]},
    )
    require_keys(payload, ["models"], "model comparison payload")
    assert isinstance(payload["models"], dict)
    assert "lightgbm_v1" in payload["models"]


@pytest.mark.group2
def test_group2_metrics_dashboard(session_client: requests.Session) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        "/api/ai/metrics-dashboard",
        expected_status=200,
        params={"hours": 24},
    )
    require_keys(payload, ["fleet_metrics", "per_machine"], "metrics dashboard payload")


@pytest.mark.group2
def test_group2_compute_metrics(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "POST",
        "/api/ai/compute-metrics",
        expected_status=200,
        params={"machine_id": baseline_context["machine_id"], "window_hours": 24},
    )
    require_keys(payload, ["status"], "compute metrics payload")
    assert payload["status"] in {"success", "no_data"}


@pytest.mark.group3
def test_group3_list_validation_rules(session_client: requests.Session) -> None:
    _, payload = request_json(session_client, "GET", "/api/admin/validation-rules", expected_status=200)
    assert isinstance(payload, list)


@pytest.mark.group3
def test_group3_create_validation_rule(created_validation_rule: Dict[str, Any]) -> None:
    assert created_validation_rule["rule_type"] == "RANGE"
    assert created_validation_rule["id"] is not None


@pytest.mark.group3
def test_group3_delete_validation_rule(
    session_client: requests.Session,
    created_validation_rule: Dict[str, Any],
) -> None:
    rule_id = created_validation_rule["id"]
    _, payload = request_json(
        session_client,
        "DELETE",
        f"/api/admin/validation-rules/{rule_id}",
        expected_status=200,
    )
    require_keys(payload, ["ok", "message"], "validation rule delete payload")
    assert payload["ok"] is True


@pytest.mark.group3
def test_group3_delete_invalid_rule(session_client: requests.Session) -> None:
    _, payload = request_json(
        session_client,
        "DELETE",
        "/api/admin/validation-rules/99999999",
        expected_status=404,
    )
    assert isinstance(payload, dict), "invalid delete payload should be an object"
    assert ("detail" in payload) or ("error" in payload), "invalid delete payload missing error field"


@pytest.mark.group4
def test_group4_data_quality_default(session_client: requests.Session, baseline_context: Dict[str, Any]) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        f"/api/machines/{baseline_context['machine_id']}/data-quality",
        expected_status=200,
        params={"hours": 24},
    )
    require_keys(payload, ["summary", "violations"], "data quality payload")
    assert isinstance(payload["violations"], list)


@pytest.mark.group4
def test_group4_data_quality_severity_filter(
    session_client: requests.Session,
    baseline_context: Dict[str, Any],
) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        f"/api/machines/{baseline_context['machine_id']}/data-quality",
        expected_status=200,
        params={"hours": 24, "severity": "CRITICAL"},
    )
    require_keys(payload, ["summary", "violations"], "severity-filtered data quality payload")


@pytest.mark.group4
def test_group4_data_quality_unknown_machine_current_behavior(session_client: requests.Session) -> None:
    _, payload = request_json(
        session_client,
        "GET",
        "/api/machines/UNKNOWN-MACHINE-ID/data-quality",
        expected_status=200,
        params={"hours": 24},
    )
    require_keys(payload, ["summary", "violations"], "unknown-machine data quality payload")
