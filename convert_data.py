import csv
import json
from collections import defaultdict

def process_csv(input_path, output_path, max_rows=50000):
    cycles = defaultdict(lambda: {"telemetry": {}})
    
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            count += 1
            if count > max_rows:
                break
            
            ts = row['timestamp']
            var = row['variable_name']
            try:
                val = float(row['value'])
            except:
                continue
                
            # Use timestamp as a temporary grouping key
            # In real production, we'd use Shot_counter or a state machine to group cycles
            cycles[ts]["timestamp"] = ts
            
            # Map variable names to UI keys
            key_map = {
                'Cushion': 'cushion',
                'Injection_pressure': 'injection_pressure',
                'Switch_pressure': 'switch_pressure',
                'Injection_time': 'injection_time',
                'Dosage_time': 'dosage_time',
                'Cyl_tmp_z1': 'temp_z1',
                'Cyl_tmp_z2': 'temp_z2',
                'Cyl_tmp_z3': 'temp_z3',
                'Extruder_torque': 'extruder_torque',
                'Shot_counter': 'shot_counter'
            }
            
            if var in key_map:
                ui_key = key_map[var]
                # Match the UI telemetry schema
                # We'll need to define setpoints/bounds based on user's Excel
                cycles[ts]["telemetry"][ui_key] = {
                    "value": val,
                    "safe_min": None,
                    "safe_max": None,
                    "setpoint": None
                }

    # Post-process: Convert dict to list, filter incomplete cycles, add metadata
    processed = []
    sorted_times = sorted(cycles.keys())
    
    for i, ts in enumerate(sorted_times):
        c = cycles[ts]
        # Only keep cycles with enough data
        if len(c["telemetry"]) > 3:
            c["cycle_id"] = str(84000 + i)
            # Add dummy predictions since these aren't in the CSV (AI part)
            c["predictions"] = {
                "scrap_probability": 0.05,
                "confidence": 0.94,
                "primary_defect_risk": "None"
            }
            # Adding SHAP attributions (placeholder for real AI output)
            c["shap_attributions"] = [] 
            processed.append(c)

    # Limit to last 500 for history
    with open(output_path, 'w') as f:
        json.dump(processed[-500:], f, indent=2)

if __name__ == "__main__":
    process_csv('frontend/Data/M231-11.csv', 'frontend/public/live_data.json')
    print("Processed and saved to frontend/public/live_data.json")
