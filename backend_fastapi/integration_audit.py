import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import joblib

import data_access as da
import database
import engine as eng
from main import (
    MACHINE_IDS,
    _csv_connectivity_snapshot,
    _load_part_catalog,
    app,
    get_machine_control_room,
    get_machine_cycles,
)


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
MODELS_DIR = BASE_DIR / "models"
FRONTEND_SRC_DIR = PROJECT_ROOT / "frontend" / "src"
FRONTEND_STORE = PROJECT_ROOT / "frontend" / "src" / "store" / "useTelemetryStore.js"
FRONTEND_OPERATOR = PROJECT_ROOT / "frontend" / "src" / "views" / "OperatorView.jsx"
FRONTEND_ENGINEER = PROJECT_ROOT / "frontend" / "src" / "views" / "EngineerView.jsx"
FRONTEND_HEADER = PROJECT_ROOT / "frontend" / "src" / "components" / "Header.jsx"
FRONTEND_VITE_CONFIG = PROJECT_ROOT / "frontend" / "vite.config.js"


def _ok(value: bool, detail: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": bool(value), "detail": detail}


def _safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _collect_frontend_sources() -> Dict[str, str]:
    files: Dict[str, str] = {}
    if not FRONTEND_SRC_DIR.exists():
        return files

    for pattern in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for path in FRONTEND_SRC_DIR.rglob(pattern):
            content = _safe_read_text(path)
            if content:
                files[str(path.relative_to(PROJECT_ROOT))] = content
    return files


def _check_backend_routes() -> Dict[str, Any]:
    required_routes = [
        "/api/health",
        "/api/ai/metrics",
        "/api/machines",
        "/api/machines/{machine_id}/cycles",
        "/api/machines/{machine_id}/parts",
        "/api/machines/{machine_id}/control-room",
        "/ws",
    ]
    actual_routes = {route.path for route in app.routes if hasattr(route, "path")}
    missing = [route for route in required_routes if route not in actual_routes]
    return _ok(len(missing) == 0, {"required": required_routes, "missing": missing})


def _check_model_artifacts() -> Dict[str, Any]:
    risk_path = MODELS_DIR / "lightgbm_scrap_risk_wide.pkl"
    forecaster_path = MODELS_DIR / "sensor_forecaster_lagged.pkl"
    detail: Dict[str, Any] = {
        "risk_exists": risk_path.exists(),
        "forecaster_exists": forecaster_path.exists(),
        "risk_size_bytes": risk_path.stat().st_size if risk_path.exists() else 0,
        "forecaster_size_bytes": forecaster_path.stat().st_size if forecaster_path.exists() else 0,
    }

    if not (risk_path.exists() and forecaster_path.exists()):
        return _ok(False, detail)

    risk_obj = joblib.load(risk_path)
    fore_obj = joblib.load(forecaster_path)

    risk_dict = risk_obj if isinstance(risk_obj, dict) else {"model": risk_obj}
    fore_dict = fore_obj if isinstance(fore_obj, dict) else {}

    risk_features = list(risk_dict.get("model_features", []) or [])
    input_features = list(fore_dict.get("input_features", []) or [])
    risk_column_style = all(re.fullmatch(r"Column_\d+", str(x)) for x in risk_features) if risk_features else False
    missing_from_forecaster = []
    if risk_features and input_features and not risk_column_style:
        missing_from_forecaster = [f for f in risk_features if f not in set(input_features)]

    detail.update(
        {
            "risk_model_type": type(risk_dict.get("model")).__name__ if risk_dict.get("model") is not None else None,
            "forecaster_model_type": type(fore_dict.get("model")).__name__ if fore_dict.get("model") is not None else None,
            "risk_feature_count": len(risk_features),
            "forecaster_feature_count": len(input_features),
            "forecaster_sensor_count": len(fore_dict.get("sensor_columns", []) or []),
            "forecaster_num_lags": fore_dict.get("num_lags"),
            "risk_features_missing_from_forecaster": missing_from_forecaster[:30],
            "risk_features_missing_count": len(missing_from_forecaster),
            "risk_column_style_detected": risk_column_style,
        }
    )

    is_ok = (
        risk_dict.get("model") is not None
        and fore_dict.get("model") is not None
        and len(risk_features) > 0
        and len(input_features) > 0
        and (risk_column_style or len(missing_from_forecaster) == 0)
    )
    return _ok(is_ok, detail)


def _check_sensor_mapping_consistency() -> Dict[str, Any]:
    raw_map = da.RAW_TO_FRONTEND_SENSOR_MAP
    eng_map = eng.VAR_KEY_MAP

    missing_engine_raw = [key for key in eng_map if key not in raw_map]
    mismatched_front_keys = [key for key in eng_map if key in raw_map and raw_map[key] != eng_map[key]]
    missing_in_engine = [key for key in raw_map if key not in eng_map]

    detail = {
        "data_access_map_count": len(raw_map),
        "engine_map_count": len(eng_map),
        "missing_engine_raw_in_data_access": missing_engine_raw,
        "frontend_name_mismatch_for_shared_raw": mismatched_front_keys,
        "data_access_raw_missing_in_engine": missing_in_engine,
    }
    return _ok(
        len(missing_engine_raw) == 0 and len(mismatched_front_keys) == 0 and len(missing_in_engine) == 0,
        detail,
    )


def _extract_frontend_keys(source_path: Path) -> List[str]:
    content = _safe_read_text(source_path)
    if not content:
        return []
    return sorted(set(re.findall(r"key:\s*'([a-z0-9_]+)'", content)))


def _check_frontend_param_keys() -> Dict[str, Any]:
    known_frontend_keys = set(da.RAW_TO_FRONTEND_SENSOR_MAP.values())
    operator_keys = _extract_frontend_keys(FRONTEND_OPERATOR)
    engineer_keys = _extract_frontend_keys(FRONTEND_ENGINEER)
    used_keys = sorted(set(operator_keys + engineer_keys))
    unknown = [key for key in used_keys if key not in known_frontend_keys]

    detail = {
        "operator_key_count": len(operator_keys),
        "engineer_key_count": len(engineer_keys),
        "used_keys": used_keys,
        "unknown_keys": unknown,
    }
    return _ok(len(unknown) == 0, detail)


def _check_frontend_endpoint_strings() -> Dict[str, Any]:
    frontend_sources = _collect_frontend_sources()
    if not frontend_sources:
        return _ok(False, {"error": f"Missing or unreadable frontend src directory: {FRONTEND_SRC_DIR}"})

    combined = "\n".join(frontend_sources.values())
    api_base_defined = bool(re.search(r"API_BASE\s*=\s*['\"]/?api['\"]", combined))
    required_suffixes = ["/health", "/machines", "/cycles", "/parts", "/control-room"]
    missing_suffixes = [frag for frag in required_suffixes if frag not in combined]

    suffix_found_in_files: Dict[str, List[str]] = {}
    for fragment in required_suffixes:
        suffix_found_in_files[fragment] = sorted(
            file for file, content in frontend_sources.items() if fragment in content
        )

    return _ok(
        api_base_defined and len(missing_suffixes) == 0,
        {
            "api_base_defined": api_base_defined,
            "required_suffixes": required_suffixes,
            "missing_suffixes": missing_suffixes,
            "suffix_found_in_files": suffix_found_in_files,
        },
    )


def _check_frontend_machine_part_flow() -> Dict[str, Any]:
    store_content = _safe_read_text(FRONTEND_STORE)
    operator_content = _safe_read_text(FRONTEND_OPERATOR)
    header_content = _safe_read_text(FRONTEND_HEADER)

    checks = {
        "store_has_part_loader": "loadMachineParts(" in store_content,
        "store_has_control_room_loader": "loadControlRoom(" in store_content,
        "store_switch_machine_updates_part_then_control": (
            "loadMachineParts(machineId).then" in store_content
            and "loadControlRoom(machineId, get().partNumber)" in store_content
        ),
        "operator_has_part_selector": "partOptions.length > 0" in operator_content,
        "operator_part_change_triggers_refresh": (
            "setPartNumber(nextPart)" in operator_content
            and "loadControlRoom(currentMachine, nextPart)" in operator_content
        ),
        "header_machine_selector_calls_switch_machine": "switchMachine(e.target.value)" in header_content,
    }

    return _ok(
        all(checks.values()),
        {
            "checks": checks,
            "files": {
                "store": str(FRONTEND_STORE.relative_to(PROJECT_ROOT)),
                "operator": str(FRONTEND_OPERATOR.relative_to(PROJECT_ROOT)),
                "header": str(FRONTEND_HEADER.relative_to(PROJECT_ROOT)),
            },
        },
    )


def _check_vite_proxy_contract() -> Dict[str, Any]:
    content = _safe_read_text(FRONTEND_VITE_CONFIG)
    if not content:
        return _ok(False, {"error": f"Missing or unreadable file: {FRONTEND_VITE_CONFIG}"})

    checks = {
        "proxy_api_route_present": bool(re.search(r"['\"]\/api['\"]\s*:\s*\{", content)),
        "proxy_ws_route_present": bool(re.search(r"['\"]\/ws['\"]\s*:\s*\{", content)),
        "proxy_ws_enabled": bool(re.search(r"\bws\s*:\s*true\b", content)),
        "backend_target_configurable": "VITE_BACKEND_URL" in content,
        "backend_ws_target_configurable": "VITE_BACKEND_WS_URL" in content,
    }
    return _ok(all(checks.values()), {"checks": checks})


async def _check_runtime_contracts() -> Dict[str, Any]:
    connectivity = _csv_connectivity_snapshot()
    parts_catalog = _load_part_catalog(force_reload=True)

    db = database.SessionLocal()
    control_summary: Dict[str, Any] = {}
    cycle_summary: Dict[str, Any] = {}
    try:
        for machine in MACHINE_IDS:
            control_ok = True
            control_error = None
            payload = None
            machine_parts = parts_catalog.get(machine, []) if isinstance(parts_catalog, dict) else []
            requested_part = (
                machine_parts[0].get("part_number")
                if machine_parts and isinstance(machine_parts[0], dict)
                else None
            )
            try:
                payload = await get_machine_control_room(machine, part_number=requested_part, db=db)
            except Exception as exc:
                control_ok = False
                control_error = str(exc)

            if control_ok and isinstance(payload, dict):
                timeline = payload.get("future_timeline") or []
                risks = [float(item.get("scrap_probability", 0.0)) for item in timeline]
                first_timeline = timeline[0] if timeline else {}
                first_telemetry = first_timeline.get("telemetry", {}) if isinstance(first_timeline, dict) else {}
                timeline_has_prob = all(
                    isinstance(item, dict) and isinstance(item.get("scrap_probability"), (int, float))
                    for item in timeline[: min(5, len(timeline))]
                )
                control_summary[machine] = {
                    "ok": True,
                    "requested_part": requested_part,
                    "resolved_part": payload.get("part_number"),
                    "part_known": bool(payload.get("part_number_known_for_machine")),
                    "part_options": len(payload.get("part_options") or []),
                    "future_points": len(timeline),
                    "future_first_telemetry_sensors": len(first_telemetry),
                    "future_contains_scrap_probability": timeline_has_prob,
                    "safe_limits": len(payload.get("safe_limits") or {}),
                    "risk_min": min(risks) if risks else None,
                    "risk_max": max(risks) if risks else None,
                }
            else:
                control_summary[machine] = {"ok": False, "error": control_error}

            cycles = await get_machine_cycles(machine, limit=120, offset=0, db=db)
            conf_vals = [
                row.get("predictions", {}).get("confidence")
                for row in cycles
                if isinstance(row.get("predictions", {}).get("confidence"), (int, float))
            ]
            cycle_summary[machine] = {
                "rows": len(cycles),
                "confidence_min": min(conf_vals) if conf_vals else None,
                "confidence_max": max(conf_vals) if conf_vals else None,
                "confidence_mean": (sum(conf_vals) / len(conf_vals)) if conf_vals else None,
            }
    finally:
        db.close()

    detail = {
        "connectivity": connectivity,
        "parts_per_machine": {m: len(parts_catalog.get(m, [])) for m in MACHINE_IDS},
        "control_room": control_summary,
        "cycles_confidence": cycle_summary,
    }
    is_ok = (
        bool(connectivity.get("exists"))
        and connectivity.get("csv_found") == connectivity.get("expected")
        and all(item.get("ok") for item in control_summary.values())
        and all(item.get("part_known") for item in control_summary.values())
        and all(item.get("future_points", 0) > 0 for item in control_summary.values())
        and all(item.get("future_contains_scrap_probability") for item in control_summary.values())
        and all((detail["parts_per_machine"].get(m, 0) > 0) for m in MACHINE_IDS)
    )
    return _ok(is_ok, detail)


async def run_audit() -> Dict[str, Any]:
    checks = {
        "backend_routes": _check_backend_routes(),
        "model_artifacts": _check_model_artifacts(),
        "sensor_mapping": _check_sensor_mapping_consistency(),
        "frontend_param_keys": _check_frontend_param_keys(),
        "frontend_endpoint_contract": _check_frontend_endpoint_strings(),
        "frontend_machine_part_flow": _check_frontend_machine_part_flow(),
        "vite_proxy_contract": _check_vite_proxy_contract(),
        "runtime_contracts": await _check_runtime_contracts(),
    }
    summary_ok = all(check.get("ok") for check in checks.values())
    return {"ok": summary_ok, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full integration audit across frontend, backend, and model artifacts.")
    parser.add_argument("--output", default="", help="Optional output JSON file path.")
    parser.add_argument("--strict", action="store_true", help="Exit with non-zero status if any check fails.")
    args = parser.parse_args()

    report = asyncio.run(run_audit())
    rendered = json.dumps(report, indent=2, default=str)
    print(rendered)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"[saved] {out_path}")

    if args.strict and not bool(report.get("ok")):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
