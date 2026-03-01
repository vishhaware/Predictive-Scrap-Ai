import pandas as pd
import numpy as np
import joblib
import os
import re
from sklearn.multioutput import MultiOutputRegressor
from lightgbm import LGBMRegressor, LGBMClassifier

def clean_csv():
    """Generates the cleaned AI_cup_parameter_info_cleaned.csv with tolerance_plus and tolerance_minus."""
    input_path = '../frontend/Data/AI_cup_parameter_info.xlsx'
    output_path = 'AI_cup_parameter_info_cleaned.csv'
    
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return
        
    df = pd.read_excel(input_path)
    cleaned_rows = []
    
    for _, row in df.iterrows():
        var_name = str(row.get('variable_name', ''))
        threshold = str(row.get('Standard threshold', ''))
        
        tol_plus, tol_minus = np.nan, np.nan
        
        if pd.notna(threshold) and '+/-' in threshold:
            # Extract number from string like "+/- 0,5 mm", "+/- 5°C"
            num_str = re.search(r'\+/-\s*([\d,]+)', threshold)
            if num_str:
                val = float(num_str.group(1).replace(',', '.'))
                tol_plus, tol_minus = val, -val
        
        # Handle the generic temperature zone case Cyl_tmp_z(1-x)
        if var_name == 'Cyl_tmp_z(1-x)':
            for i in range(1, 6):
                cleaned_rows.append({
                    "variable_name": f"Cyl_tmp_z{i}",
                    "tolerance_plus": tol_plus,
                    "tolerance_minus": tol_minus
                })
        else:
            cleaned_rows.append({
                "variable_name": var_name,
                "tolerance_plus": tol_plus,
                "tolerance_minus": tol_minus
            })
            
    pd.DataFrame(cleaned_rows).to_csv(output_path, index=False)
    print(f"Successfully generated {output_path}")

def generate_dummy_models():
    """Generates the required .pkl pipeline models."""
    models_dir = "models"
    os.makedirs(models_dir, exist_ok=True)
    
    sensors = ['Cushion', 'Injection_time', 'Dosage_time', 'Injection_pressure', 
               'Switch_pressure', 'Switch_position', 'Cycle_time', 'Cyl_tmp_z1', 
               'Cyl_tmp_z2', 'Cyl_tmp_z3', 'Cyl_tmp_z4', 'Cyl_tmp_z5']
               
    # 1. Sensor Forecaster
    print("Training dummy sensor forecaster...")
    num_lags = 3
    input_features = sensors.copy()
    for lag in range(1, num_lags + 1):
        for s in sensors:
            input_features.append(f"{s}_lag_{lag}")
            
    # Dummy data
    X_train_reg = np.random.randn(100, len(input_features))
    Y_train_reg = np.random.randn(100, len(sensors))
    
    base_lgbm = LGBMRegressor(n_estimators=5, random_state=42)
    multi_reg = MultiOutputRegressor(base_lgbm)
    multi_reg.fit(X_train_reg, Y_train_reg)
    
    forecaster_dict = {
        "model": multi_reg,
        "sensor_columns": sensors,
        "input_features": input_features,
        "num_lags": num_lags
    }
    
    joblib.dump(forecaster_dict, os.path.join(models_dir, "sensor_forecaster_lagged.pkl"))
    print("Saved models/sensor_forecaster_lagged.pkl")
    
    # 2. Scrap Risk Predictor
    print("Training dummy scrap risk model...")
    lgbm_classifier = LGBMClassifier(n_estimators=5, random_state=42)
    X_train_clf = np.random.randn(100, len(input_features))
    Y_train_clf = np.random.randint(0, 2, 100)
    
    lgbm_classifier.fit(X_train_clf, Y_train_clf)
    joblib.dump(lgbm_classifier, os.path.join(models_dir, "lightgbm_scrap_risk_wide.pkl"))
    print("Saved models/lightgbm_scrap_risk_wide.pkl")

if __name__ == "__main__":
    clean_csv()
    generate_dummy_models()
