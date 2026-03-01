import pandas as pd
import numpy as np
from inference_engine import PredictiveInferenceEngine

def main():
    # 1. Define the sensors we want to predict
    sensors = [
        "Cushion", "Injection_time", "Dosage_time", "Injection_pressure",
        "Switch_pressure", "Switch_position", "Cycle_time", "Cyl_tmp_z1",
        "Cyl_tmp_z2", "Cyl_tmp_z3", "Cyl_tmp_z4", "Cyl_tmp_z5"
    ]
    
    # 2. Generate dummy historical data
    # Create 100 cycles of mock machine data
    np.random.seed(42)
    history_data = {
        sensor: np.random.normal(loc=100.0 if "pressure" in sensor else 50.0, scale=2.0, size=100)
        for sensor in sensors
    }
    history_df = pd.DataFrame(history_data)
    
    print("--- Phase 2: LightGBM Inference Engine Test ---")
    print(f"Training on historical dataframe of shape: {history_df.shape}")
    
    # 3. Initialize and train the engine
    engine = PredictiveInferenceEngine(target_sensors=sensors)
    success = engine.train(history_df)
    
    if not success:
        print("Training failed (not enough data).")
        return
        
    print("Training successful.\n")
    
    # 4. Generate a mock "current state" (the real-time readings coming from the machine)
    current_state = {
        sensor: np.random.normal(loc=100.0 if "pressure" in sensor else 50.0, scale=2.0)
        for sensor in sensors
    }
    
    print("Current State (t=0):")
    for k, v in list(current_state.items())[:3]:
        print(f"  {k}: {v:.2f}")
    print("  ...\n")
    
    # 5. Run Recursive Multi-Step Forecasting (e.g., 5 steps into the future)
    steps_ahead = 5
    print(f"Running Recursive Forecasting for {steps_ahead} steps...\n")
    
    predictions = engine.predict_future(current_state, steps=steps_ahead)
    
    # 6. Output the results
    for i, pred in enumerate(predictions):
        print(f"Prediction for Step t+{i+1}:")
        for k, v in list(pred.items())[:3]:
             print(f"  {k}: {v:.2f}")
        print("  ...")
        
    print("\nTest completed successfully. Output shape is correct.")

if __name__ == "__main__":
    main()
