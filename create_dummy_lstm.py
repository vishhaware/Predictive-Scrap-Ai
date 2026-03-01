import os
import tensorflow as tf
import numpy as np

model_path = "C:/new project/New folder/backend_fastapi/models/lstm_scrap_risk.h5"

# Define a simple LSTM model
model = tf.keras.Sequential([
    tf.keras.layers.Input(shape=(30, 15)),
    tf.keras.layers.LSTM(16, return_sequences=True),
    tf.keras.layers.LSTM(8),
    tf.keras.layers.Dense(1, activation='sigmoid')
])

model.save(model_path)
print(f"Dummy LSTM model saved to {model_path}")
