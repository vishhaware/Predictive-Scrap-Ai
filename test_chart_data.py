import urllib.request
import json

data = json.loads(
    urllib.request.urlopen(
        "http://127.0.0.1:8000/api/machines/M231-11/chart-data?horizon_minutes=60"
    ).read()
)

past = data.get("past", [])
future = data.get("future", [])
meta = data.get("meta", {})

print(f"seam_ok: {meta.get('seam_ok')}")
print(f"past_last_ts: {meta.get('past_last_ts')}")
print(f"future_first_ts: {meta.get('future_first_ts')}")
print(f"no_data_reason: {meta.get('no_data_reason')}")

past_probs = [r["scrap_pct"] for r in past]
print(f"Past scrap_pct range: {min(past_probs):.2f} - {max(past_probs):.2f}")
print(f"Past scrap_pct unique values: {len(set(past_probs))}")

future_probs = [r["scrap_pct"] for r in future]
print(f"Future scrap_pct range: {min(future_probs):.2f} - {max(future_probs):.2f}")

future_ts = [r["timestamp"] for r in future]
print(f"Future timestamps: first={future_ts[0]}, last={future_ts[-1]}")

# Check observed scrap events
observed_events = sum(r.get("observed_scrap_event", 0) for r in past)
print(f"Observed scrap events in past: {observed_events}")
observed_pcts = [r.get("observed_scrap_pct", 0) for r in past]
print(f"Observed scrap_pct range: {min(observed_pcts):.2f} - {max(observed_pcts):.2f}")
