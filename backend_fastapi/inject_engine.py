import os

engine_file = r"c:\new project\New folder\backend_fastapi\engine.py"

with open(engine_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Part 1: Imports
for i in range(len(lines)):
    if "from datetime import datetime" in lines[i]:
        lines.insert(i + 1, "from inference_engine import PredictiveInferenceEngine\n")
        break

# Part 2: analyze_shot_sequence start
start_idx = -1
for i in range(len(lines)):
    if "def analyze_shot_sequence(" in lines[i]:
        start_idx = i
        break

if start_idx != -1:
    body_idx = -1
    for i in range(start_idx, len(lines)):
        if "results = []" in lines[i]:
            body_idx = i
            break
            
    if body_idx != -1:
        injection = """
    # Initialize and train the Inference Engine
    inference_engine = None
    target_sensors = [k for k in THRESHOLDS.keys() if THRESHOLDS.get(k, {}).get("critical", False) or True]  # use all sensors
    
    if len(shots) >= 20: 
        # Only train if we have enough historical data
        try:
            inference_engine = PredictiveInferenceEngine(target_sensors=target_sensors)
            history_df = pd.DataFrame(shots)
            # Train model
            success = inference_engine.train(history_df)
            if not success:
                inference_engine = None
        except Exception as e:
            print(f"Warning: Could not train inference engine: {e}")
            inference_engine = None

"""
        lines.insert(body_idx, injection)

# Part 3: prediction loop logic
for i in range(len(lines) - 1, -1, -1):
    if "results.append({" in lines[i]:
        injection2 = """
        # Calculate future predictions if the engine is ready
        future_predictions = None
        if inference_engine and i == len(shots) - 1:
            try:
                # Prepare current state
                current_state = {sensor: shot.get(sensor, 0.0) for sensor in target_sensors}
                # Predict 10 steps ahead (as per spec)
                future_trajectory = inference_engine.predict_future(current_state, steps=10)
                
                # Format for frontend 
                future_predictions = {
                    "steps": 10,
                    "trajectory": []
                }
                
                for step_idx, step_pred in enumerate(future_trajectory):
                    step_data = {}
                    for sensor, val in step_pred.items():
                        frontend_key = VAR_KEY_MAP.get(sensor, sensor)
                        step_data[frontend_key] = float(round(val, 3))
                    future_predictions["trajectory"].append(step_data)
                    
            except Exception as e:
                print(f"Warning: Inference prediction failed: {e}")
                future_predictions = None

"""
        lines.insert(i, injection2)
        
        # Now update the dict literal
        # find where dict literal closes
        close_idx = -1
        for j in range(i + 1, len(lines)): # The +1 is needed because of insert
            if "        })" in lines[j] or "    })" in lines[j]:
                close_idx = j
                break
                
        if close_idx != -1:
            for j in range(close_idx - 1, i, -1):
                if "physics_violations" in lines[j]:
                    lines[j] = lines[j].replace("\\n", "").rstrip()
                    if not lines[j].endswith(","):
                        lines[j] = lines[j] + ",\n"
                    # insert new line
                    lines.insert(j + 1, '            "future_forecast": future_predictions\n')
                    break
        break

with open(engine_file, "w", encoding="utf-8") as f:
    f.writelines(lines)
    
print("engine.py successfully updated via python script!")
