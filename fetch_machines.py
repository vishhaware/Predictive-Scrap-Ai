import requests, json
try:
    r = requests.get("http://127.0.0.1:8000/api/machines", timeout=5)
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
