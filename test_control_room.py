import urllib.request
import json

try:
    url = "http://127.0.0.1:8001/api/machines/M231-11/control-room?horizon_minutes=60"
    data = json.loads(urllib.request.urlopen(url).read())

    lstm = data.get("lstm_preview", {})
    print("--- LSTM Preview ---")
    print(f"Enabled: {lstm.get('enabled')}")
    print(f"Scrap Probability: {lstm.get('scrap_probability')}")
    print(f"Risk Level: {lstm.get('risk_level')}")
    print(f"Unavailable Reason: {lstm.get('unavailable_reason')}")
    
    if lstm.get("attention_attributions"):
        print(f"Top Attributions: {lstm.get('attention_attributions')[:2]}")

except Exception as e:
    print(f"Error testing control room: {e}")
