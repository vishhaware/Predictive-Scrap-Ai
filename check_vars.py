import pandas as pd
import json

def process():
    # Read a chunk to see names
    df = pd.read_csv('frontend/Data/M231-11.csv', nrows=10000)
    print("Unique variables in first 10k rows:")
    print(df['variable_name'].unique())

if __name__ == "__main__":
    process()
