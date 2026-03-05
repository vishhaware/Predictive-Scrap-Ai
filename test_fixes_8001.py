import urllib.request
import json

try:
    data = json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:8001/api/machines/M231-11/chart-data?horizon_minutes=60"
        ).read()
    )

    past = data.get("past", [])
    future = data.get("future", [])
    meta = data.get("meta", {})

    print(f"seam_ok: {meta.get('seam_ok')}")
    print(f"past_last_ts: {meta.get('past_last_ts')}")
    print(f"future_first_ts: {meta.get('future_first_ts')}")
    print(f"no_data_reason: {meta.get('no_data_reason')}")

    if past:
        past_probs = [r["scrap_pct"] for r in past]
        print(f"Past scrap_pct range: {min(past_probs):.2f} - {max(past_probs):.2f}")
        print(f"Past scrap_pct unique values: {len(set(past_probs))}")
        
    if future:
        future_probs = [r["scrap_pct"] for r in future]
        print(f"Future scrap_pct range: {min(future_probs):.2f} - {max(future_probs):.2f}")
        print(f"Future timestamps: first={future[0]['timestamp']}, last={future[-1]['timestamp']}")

    # Check observed scrap events
    observed_events = sum(r.get("observed_scrap_event", 0) for r in past)
    print(f"Observed scrap events in past: {observed_events}")

except Exception as e:
    print(f"Error testing chart data: {e}")
