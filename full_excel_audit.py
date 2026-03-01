import pandas as pd

def audit_excel_full(path):
    print(f"--- FULL DETAIL AUDIT OF {path} ---")
    # Read the excel file
    df = pd.read_excel(path)
    
    # Fill NaN to avoid 'nan' strings
    df = df.fillna('')
    
    # Iterate through all rows and print in a structured way
    for i, row in df.iterrows():
        print(f"\n[PARAMETER {i+1}]")
        for col in df.columns:
            print(f"  {col}: {row[col]}")
    print("\n--- END OF AUDIT ---")

if __name__ == "__main__":
    audit_excel_full('frontend/Data/AI_cup_parameter_info.xlsx')
