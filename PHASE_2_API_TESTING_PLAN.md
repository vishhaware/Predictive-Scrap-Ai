# Phase 2 API Integration Testing Plan (Groups 1-4)

## Objective
Run deterministic live API verification for Groups 1-4 against local FastAPI (`127.0.0.1:8000`) using:
- grouped script runner (`api_testing_guide.py`)
- pytest live integration suite (`backend_fastapi/test_api_groups_live.py`)

This plan assumes existing SQLite data is preserved and only minimal/idempotent test seeding is performed.

## Source-of-Truth API Contracts
Use `backend_fastapi/main.py` as authoritative behavior.

Important contract notes currently implemented:
1. `POST /api/admin/parameters/{config_id}/revert` returns `200` with `{ "ok": true, "message": "..." }`.
2. `DELETE /api/admin/validation-rules/{rule_id}` returns `200` with `{ "ok": true, "message": "..." }`.
3. `POST /api/ai/compute-metrics` takes query params (`machine_id`, `window_hours`), not JSON body.

## Prerequisites
1. Python virtual environment exists at `backend_fastapi/venv`.
2. Dependencies installed (includes `pytest`).
3. Local SQLite DB exists with baseline `cycles` and `machine_stats` data.

## Execution Sequence

### 1) Install backend dependencies
```powershell
cd backend_fastapi
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2) Start FastAPI server on localhost:8000
```powershell
cd backend_fastapi
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### 3) Run grouped script checks
From repo root:
```powershell
python api_testing_guide.py --group 1 --strict
python api_testing_guide.py --group 2 --strict
python api_testing_guide.py --group 3 --strict
python api_testing_guide.py --group 4 --strict
python api_testing_guide.py --group all --strict --json-report .runtime\api-test-report.json
```

### 4) Run pytest live integration checks
From `backend_fastapi`:
```powershell
.\venv\Scripts\python.exe -m pytest test_api_groups_live.py -m group1 -v
.\venv\Scripts\python.exe -m pytest test_api_groups_live.py -m group2 -v
.\venv\Scripts\python.exe -m pytest test_api_groups_live.py -m group3 -v
.\venv\Scripts\python.exe -m pytest test_api_groups_live.py -m group4 -v
.\venv\Scripts\python.exe -m pytest test_api_groups_live.py -v
```

## Built-in Data Preparation Behavior
Both the script and pytest suite perform the same minimal prep before endpoint assertions:
1. Verify server reachability (`GET /api/health`).
2. Verify baseline dataset via live endpoints:
   - `GET /api/machines` must return at least one machine.
   - `GET /api/machines/{machine_id}/cycles?limit=1` must return at least one cycle.
3. If model metrics are missing for `lightgbm_v1` + machine, trigger:
   - `POST /api/ai/compute-metrics?machine_id=M231-11&window_hours=24`

The prep is idempotent and does not reset/delete production-like data.

## Group Test Matrix

### Group 1: Parameter Management
1. `GET /api/admin/parameters` -> `200`, list response.
2. `POST /api/admin/parameters` -> `200`, upsert response with required keys.
3. `GET /api/admin/parameters/{id}` -> `200`, correct record payload.
4. `POST /api/admin/parameters/{id}/revert` -> `200`, `{ok, message}`.
5. `GET /api/admin/parameter-history` -> `200`, list response.

### Group 2: Model Performance Metrics
1. `GET /api/ai/model-metrics/{model_id}` -> `200`, object with `model_id` and optional `metrics`.
2. `GET /api/ai/metrics-history/{model_id}` -> `200`, object containing `count` and `data[]`.
3. `GET /api/ai/model-comparison` -> `200`, object containing `models` map.
4. `GET /api/ai/metrics-dashboard` -> `200`, object containing `fleet_metrics` and `per_machine`.
5. `POST /api/ai/compute-metrics?machine_id=...&window_hours=...` -> `200`, status in `{success, no_data}`.

### Group 3: Validation Rules
1. `GET /api/admin/validation-rules` -> `200`, list response.
2. `POST /api/admin/validation-rules` -> `200`, created rule with `id`.
3. `DELETE /api/admin/validation-rules/{id}` -> `200`, `{ok, message}`.
4. `DELETE /api/admin/validation-rules/{invalid_id}` -> `404`.

### Group 4: Data Quality
1. `GET /api/machines/{machine_id}/data-quality?hours=24` -> `200`, `{summary, violations[]}`.
2. `GET /api/machines/{machine_id}/data-quality?hours=24&severity=CRITICAL` -> `200`, same shape.
3. `GET /api/machines/{invalid_machine_id}/data-quality` -> currently `200` (current implementation behavior), shape still validated.

## Expected Non-Fatal Conditions
1. Group 2 compute endpoint may return `status=no_data`; this is valid and should not fail checks.
2. Data quality violations list can be empty and still be a passing result.

## Success Criteria
1. Backend starts cleanly on `127.0.0.1:8000`.
2. Script runner can execute Group 1-4 with strict mode and machine-readable report output.
3. Pytest suite executes Group 1-4 by marker and all-groups run with deterministic pass/fail signaling.
4. No DB reset is required; existing baseline data remains intact.
