import csv
import json
import os
from collections import defaultdict

def process_machine_csv(input_path, machine_id):
    cycles = defaultdict(lambda: {"telemetry": {}})
    
    if not os.path.exists(input_path):
        print(f"Skipping {input_path}, file not found.")
        return
    
    print(f"Processing {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        # We take a slightly larger chunk to ensure we get enough complete cycles
        for row in reader:
            count += 1
            if count > 100000: # Increase limit for better quality
                break
            
            ts = row['timestamp']
            var = row['variable_name']
            try:
                val = float(row['value'])
            except:
                continue
                
            cycles[ts]["timestamp"] = ts
            
            key_map = {
                'Cushion': 'cushion',
                'Injection_pressure': 'injection_pressure',
                'Switch_pressure': 'switch_pressure',
                'Injection_time': 'injection_time',
                'Dosage_time': 'dosage_time',
                'Cyl_tmp_z2': 'temp_z2',
            }
            
            if var in key_map:
                ui_key = key_map[var]
                cycles[ts]["telemetry"][ui_key] = {
                    "value": val,
                    "safe_min": None,
                    "safe_max": None,
                    "setpoint": None
                }

    processed = []
    sorted_times = sorted(cycles.keys())
    
    for i, ts in enumerate(sorted_times):
        c = cycles[ts]
        if len(c["telemetry"]) >= 3:
            c["cycle_id"] = f"{machine_id}-{1000 + i}"
            c["predictions"] = {
                "scrap_probability": 0.05,
                "confidence": 0.95,
                "primary_defect_risk": "None"
            }
            c["shap_attributions"] = [] 
            processed.append(c)

    # Output directory
    os.makedirs('frontend/public/data', exist_ok=True)
    output_path = f'frontend/public/data/{machine_id}.json'
    with open(output_path, 'w') as f:
        json.dump(processed[-800:], f, indent=2)
    print(f"Saved {len(processed[-800:])} cycles to {output_path}")

if __name__ == "__main__":
    machines = [
        ('M231-11', 'frontend/Data/M231-11.csv'),
        ('M356-57', 'frontend/Data/M356-57.csv'),
        ('M471-23', 'frontend/Data/M471-23.csv'),
        ('M607-30', 'frontend/Data/M607-30.csv'),
        ('M612-33', 'frontend/Data/M612-33.csv'),
    ]
    
    for mid, path in machines:
        process_machine_csv(path, mid)
