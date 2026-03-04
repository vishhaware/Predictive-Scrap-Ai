import pandas as pd
import lightgbm as lgb
from sklearn.multioutput import MultiOutputRegressor
from typing import List, Dict, Any, Optional

class PredictiveInferenceEngine:
    """
    Phase 2: LightGBM Inference Engine
    Uses Recursive Multi-Step Forecasting to predict future trajectories of industrial parameters.
    """
    def __init__(self, target_sensors: List[str]):
        """
        Initializes the inference engine.
        
        Args:
            target_sensors: List of the 14 operational parameters (e.g., Cushion, Dosage_time, etc.)
                            to forecast.
        """
        self.target_sensors = target_sensors
        
        # We wrap LightGBM in MultiOutputRegressor to predict all sensors simultaneously.
        # lightgbm is optimized for the 16GB RAM constraint via histogram bucketing.
        base_estimator = lgb.LGBMRegressor(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=5,
            min_data_in_bin=1,
            min_split_gain=0.0,
            verbose=-1,
            verbosity=-1,
            n_jobs=-1,      # Use all available CPU cores
            random_state=42
        )
        self.model = MultiOutputRegressor(base_estimator)
        self.is_trained = False
        self.feature_sensors = list(target_sensors)

    def train(self, history_df: pd.DataFrame) -> bool:
        """
        Trains the recursive forecasting model.
        
        Args:
            history_df: DataFrame containing historical cycles (must contain self.target_sensors columns).
            
        Returns:
            bool: True if training was successful.
        """
        # Ensure all required columns are present
        missing_cols = [col for col in self.target_sensors if col not in history_df.columns]
        if missing_cols:
            raise ValueError(f"Training data is missing required sensors: {missing_cols}")
        
        # Prepare the dataset
        # We want to use the current state (X_t) to predict the next state (y_{t+1})
        df = history_df[self.target_sensors].copy()
        df = df.apply(pd.to_numeric, errors="coerce")
        
        # Drop rows with NaNs to ensure clean training data
        df = df.dropna()
        
        if len(df) < 20: 
            # Require at least 20 historical points to train a meaningful model
            return False
            
        # Keep only informative input features. LightGBM cannot learn from
        # all-constant/all-missing columns and emits noisy warnings.
        self.feature_sensors = [
            col for col in self.target_sensors
            if df[col].nunique(dropna=True) > 1 and float(df[col].std() or 0.0) > 1e-9
        ]
        if len(self.feature_sensors) < 2:
            self.is_trained = False
            return False

        # X: Current State ($t$)
        # y: Next State ($t+1$)
        X = df[self.feature_sensors].iloc[:-1]
        y = df[self.target_sensors].shift(-1).dropna()
        if len(X) == 0 or len(y) == 0:
            self.is_trained = False
            return False
        
        # Fit the MultiOutputRegressor
        self.model.fit(X, y)
        self.is_trained = True
        return True

    def predict_future(self, current_state: Dict[str, float], steps: int = 10) -> List[Dict[str, float]]:
        """
        Runs recursive multi-step forecasting to predict the next `steps` cycles.
        
        Args:
            current_state: Dictionary of the latest sensor readings.
            steps: Number of forward cycles to predict.
            
        Returns:
            List of dictionaries, where index i represents the prediction for cycle t + i + 1.
        """
        if not self.is_trained:
            raise RuntimeError("Model must be trained before calling predict_future()")
            
        # Validate current state
        missing_cols = [col for col in self.feature_sensors if col not in current_state]
        if missing_cols:
            raise ValueError(f"Current state is missing required sensors: {missing_cols}")
            
        # Convert state to a 1-row frame in the trained feature order.
        current_x = pd.DataFrame([{
            sensor: float(current_state[sensor]) for sensor in self.feature_sensors
        }])
        
        predictions = []
        
        # Recursive Forecasting Loop
        for _ in range(steps):
            # 1. Ask model to predict exactly 1 step ahead (outputs shape (1, num_sensors))
            next_step_pred = self.model.predict(current_x)
            
            # 2. Store the prediction in a dictionary format
            pred_dict = {sensor: float(next_step_pred[0][i]) for i, sensor in enumerate(self.target_sensors)}
            predictions.append(pred_dict)
            
            # 3. Recursive magic: Feed the prediction back in as the "current input"
            # for the next iteration of the loop.
            current_x = pd.DataFrame([{
                sensor: float(pred_dict[sensor]) for sensor in self.feature_sensors
            }])
            
        return predictions
