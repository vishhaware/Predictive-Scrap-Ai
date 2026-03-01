import pandas as pd
import csv

def audit_csv(path, num_lines=15):
    print(f"--- DETAILED AUDIT OF {path} ---")
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"HEADER COLUMNS: {header}")
        print("-" * 50)
        for i, row in enumerate(reader):
            if i >= num_lines:
                break
            print(f"LINE {i+1}: {row}")
            # Detail each column for the first row
            if i == 0:
                print("   [FIELD EXPLANATION]")
                for idx, val in enumerate(row):
                    print(f"   -> {header[idx]}: {val}")
        print("-" * 50)

def audit_excel(path):
    print(f"--- DETAILED AUDIT OF {path} ---")
    df = pd.read_excel(path)
    print(f"SHEET COLUMNS: {df.columns.tolist()}")
    for i, row in df.head(10).iterrows():
        print(f"ROW {i+1}: {row.to_dict()}")

if __name__ == "__main__":
    audit_csv('frontend/Data/M231-11.csv', 10)
    print("\n\n")
    audit_excel('frontend/Data/AI_cup_parameter_info.xlsx')
