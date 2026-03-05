# Stabilize and Ship Checklist (Cleaned Data v2)

## 1) Generate cleaned artifacts
```bash
python transform_data_pipeline.py
```

Expected output folder: `cleaned_data_output/`

## 2) Backend readiness checks
```bash
python -m py_compile transform_data_pipeline.py backend_fastapi/main.py
python test_chart_data_v2.py
```

## 3) Frontend readiness checks
```bash
node --test frontend/src/store/useTelemetryStore.test.js
```

## 4) Start services and validate manually
1. Restart backend.
2. Open dashboard.
3. Switch machine.
4. Select part number.
5. Confirm chart loads and updates correctly.

## 5) Rollout monitoring (first 24h)
```bash
python monitor_chart_rollout.py --base-url http://127.0.0.1:8000
```

Default alert thresholds:
- fallback rate > `0.20`
- HTTP 5xx > `0`
- empty past payloads > `50`

## 6) Rollback
Immediate rollback path is already in place:
- frontend `loadChartData` uses v2 first, then falls back to legacy endpoint.

If needed, force legacy-only by changing `frontend/src/store/useTelemetryStore.js` to call only `/chart-data`.
