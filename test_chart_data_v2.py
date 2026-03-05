import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi.testclient import TestClient

import backend_fastapi.main as main_module
from backend_fastapi.main import app


MACHINES = ["M231-11", "M356-57", "M471-23", "M607-30", "M612-33"]
DEFAULT_CLEANED_DIR = Path("cleaned_data_output")


def top_part_for_machine(cleaned_dir: Path, machine_id: str) -> Optional[str]:
    path = cleaned_dir / f"{machine_id}_cleaned.csv"
    if not path.exists():
        return None
    counter = Counter()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            part = str(row.get("part_number") or "").strip().upper()
            if not part or part == "UNKNOWN":
                continue
            counter[part] += 1
    return counter.most_common(1)[0][0] if counter else None


def validate_payload(payload: Dict, require_rows: bool = True) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    for key in ("machine_id", "past", "future", "meta"):
        if key not in payload:
            errors.append(f"missing key '{key}'")

    past = payload.get("past")
    future = payload.get("future")
    meta = payload.get("meta") or {}
    if not isinstance(past, list):
        errors.append("past is not a list")
    if not isinstance(future, list):
        errors.append("future is not a list")
    if not isinstance(meta, dict):
        errors.append("meta is not an object")

    if require_rows and isinstance(past, list) and len(past) == 0:
        errors.append("past is empty")
    if require_rows and isinstance(future, list) and len(future) == 0:
        errors.append("future is empty")

    source = meta.get("source")
    if source not in {"cleaned_data_v2", "legacy"}:
        errors.append(f"unexpected meta.source={source!r}")

    past_last = meta.get("past_last_ts")
    future_first = meta.get("future_first_ts")
    seam_ok = meta.get("seam_ok")
    if past_last and future_first and seam_ok is False:
        errors.append("seam check failed (past_last_ts >= future_first_ts)")

    return (len(errors) == 0), errors


def run_tests(cleaned_dir: Path, history_limit: int, horizon_minutes: int) -> int:
    client = TestClient(app)
    try:
        failures = 0
        report_rows: List[Dict[str, str]] = []

        for machine_id in MACHINES:
            # Base request
            r = client.get(
                f"/api/machines/{machine_id}/chart-data-v2",
                params={"history_limit": history_limit, "horizon_minutes": horizon_minutes, "shift_hours": 24},
            )
            status_ok = r.status_code == 200
            payload = r.json() if status_ok else {}
            ok, errors = validate_payload(payload, require_rows=True) if status_ok else (False, [f"http_{r.status_code}"])
            if not ok:
                failures += 1
            report_rows.append(
                {
                    "machine": machine_id,
                    "scenario": "base",
                    "status": "PASS" if ok else "FAIL",
                    "past_len": str(len(payload.get("past") or [])) if status_ok else "0",
                    "future_len": str(len(payload.get("future") or [])) if status_ok else "0",
                    "message": "; ".join(errors) if errors else "ok",
                }
            )

            # Part + shift request (best available part from cleaned file)
            part = top_part_for_machine(cleaned_dir, machine_id)
            if part:
                r2 = client.get(
                    f"/api/machines/{machine_id}/chart-data-v2",
                    params={
                        "part_number": part,
                        "shift": "MORNING",
                        "history_limit": history_limit,
                        "horizon_minutes": horizon_minutes,
                        "shift_hours": 24,
                    },
                )
                status_ok2 = r2.status_code == 200
                payload2 = r2.json() if status_ok2 else {}
                # part+shift can be empty for some combinations; do not enforce rows
                ok2, errors2 = validate_payload(payload2, require_rows=False) if status_ok2 else (False, [f"http_{r2.status_code}"])
                if not ok2:
                    failures += 1
                report_rows.append(
                    {
                        "machine": machine_id,
                        "scenario": f"part_shift(part={part},shift=MORNING)",
                        "status": "PASS" if ok2 else "FAIL",
                        "past_len": str(len(payload2.get("past") or [])) if status_ok2 else "0",
                        "future_len": str(len(payload2.get("future") or [])) if status_ok2 else "0",
                        "message": "; ".join(errors2) if errors2 else (payload2.get("part_filter_message") or "ok"),
                    }
                )

        # Missing artifact scenario: point backend to an empty directory and expect 404.
        original_dir = main_module.CLEANED_DATA_OUTPUT_DIR
        try:
            main_module.CLEANED_DATA_OUTPUT_DIR = str((cleaned_dir / "__missing__").resolve())
            if hasattr(main_module, "cleaned_machine_cache") and isinstance(main_module.cleaned_machine_cache, dict):
                main_module.cleaned_machine_cache.clear()
            r_missing = client.get(
                "/api/machines/M231-11/chart-data-v2",
                params={"history_limit": history_limit, "horizon_minutes": horizon_minutes},
            )
            scenario_ok = True
            detail = ""
            if r_missing.status_code != 404:
                failures += 1
                scenario_ok = False
                detail = f"expected 404, got {r_missing.status_code}"
            else:
                payload_missing = r_missing.json()
                detail = str(payload_missing.get("detail") or payload_missing.get("error") or "")
                if "Run transform_data_pipeline.py first" not in detail:
                    failures += 1
                    scenario_ok = False
                    detail = f"missing actionable 404 detail: {detail}"
            report_rows.append(
                {
                    "machine": "M231-11",
                    "scenario": "missing_cleaned_artifact",
                    "status": "PASS" if scenario_ok else "FAIL",
                    "past_len": "0",
                    "future_len": "0",
                    "message": detail or "ok",
                }
            )
        finally:
            main_module.CLEANED_DATA_OUTPUT_DIR = original_dir
            if hasattr(main_module, "cleaned_machine_cache") and isinstance(main_module.cleaned_machine_cache, dict):
                main_module.cleaned_machine_cache.clear()

        print("\nchart-data-v2 verification")
        print("=" * 96)
        print(f"{'machine':<10} {'scenario':<42} {'status':<6} {'past':>6} {'future':>6}  message")
        print("-" * 96)
        for row in report_rows:
            print(
                f"{row['machine']:<10} {row['scenario']:<42} {row['status']:<6} "
                f"{row['past_len']:>6} {row['future_len']:>6}  {row['message']}"
            )
        print("-" * 96)
        print(f"total checks: {len(report_rows)} | failures: {failures}")
        return failures
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test /api/machines/{machine_id}/chart-data-v2.")
    parser.add_argument("--cleaned-dir", default=str(DEFAULT_CLEANED_DIR), help="Directory with *_cleaned.csv files")
    parser.add_argument("--history-limit", type=int, default=200)
    parser.add_argument("--horizon-minutes", type=int, default=60)
    args = parser.parse_args()

    failures = run_tests(
        cleaned_dir=Path(args.cleaned_dir),
        history_limit=args.history_limit,
        horizon_minutes=args.horizon_minutes,
    )
    if failures > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
