import urllib.request
import json

# Check cycles endpoint to see raw prediction data
data = json.loads(
    urllib.request.urlopen(
        "http://127.0.0.1:8000/api/machines/M231-11/cycles?limit=5"
    ).read()
)

for i, cycle in enumerate(data[:3]):
    print(f"\n=== Cycle {i} ===")
    print(f"cycle_id: {cycle.get('cycle_id')}")
    print(f"timestamp: {cycle.get('timestamp')}")
    pred = cycle.get("predictions", {})
    print(f"predictions.scrap_probability: {pred.get('scrap_probability')}")
    print(f"predictions.confidence: {pred.get('confidence')}")
    print(f"predictions.risk_level: {pred.get('risk_level')}")
    print(f"predictions.model_name: {pred.get('model_name')}")
    
    tele = cycle.get("telemetry", {})
    # Print a few key telemetry values
    for key in ["cushion", "injection_time", "scrap_counter", "shot_counter"]:
        val = tele.get(key, {})
        if isinstance(val, dict):
            print(f"  {key}: value={val.get('value')}, safe_min={val.get('safe_min')}, safe_max={val.get('safe_max')}")
        else:
            print(f"  {key}: {val}")

# Now check control-room to see future_timeline generation
print("\n\n=== Control Room - Future Timeline ===")
try:
    cr_data = json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:8000/api/machines/M231-11/control-room?horizon_minutes=60&history_window=240"
        ).read()
    )
    ft = cr_data.get("future_timeline", [])
    print(f"future_timeline length: {len(ft)}")
    if ft:
        print(f"First: {json.dumps(ft[0], indent=2, default=str)[:500]}")
        print(f"Last: {json.dumps(ft[-1], indent=2, default=str)[:500]}")
    
    lstm = cr_data.get("lstm_preview", {})
    print(f"\nLSTM preview enabled: {lstm.get('enabled')}")
    print(f"LSTM scrap_probability: {lstm.get('scrap_probability')}")
    print(f"LSTM unavailable_reason: {lstm.get('unavailable_reason')}")
    print(f"LSTM sequence_length: {lstm.get('sequence_length')}")
    print(f"LSTM model_name: {lstm.get('model_name')}")
except Exception as e:
    print(f"Control room error: {e}")
