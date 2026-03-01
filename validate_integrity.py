import os
import pandas as pd
from datetime import datetime

data_dir = "C:/new project/New folder/frontend/Data"
csv_files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
excel_file = "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"

excel_path = os.path.join(data_dir, excel_file)
if not os.path.exists(excel_path):
    print("Excel missing")
    exit()

print("Reading MES Excel...")
df_mes = pd.read_excel(excel_path, sheet_name="Data")
# Map MES machines to our internal IDs
def get_numeric(m):
    import re
    match = re.search(r"\d+", str(m))
    return match.group(0) if match else None

for csv in csv_files:
    num = get_numeric(csv)
    path = os.path.join(data_dir, csv)
    if not os.path.exists(path): continue
    
    print(f"\nChecking {csv} (Machine {num})")
    mes_for_m = df_mes[df_mes['machine_id'].astype(str).str.contains(num if num else "___")]
    if mes_for_m.empty:
        print("  - No entries in MES for this machine.")
        continue
    
    mes_min = pd.to_datetime(mes_for_m['machine_event_create_date']).min()
    mes_max = pd.to_datetime(mes_for_m['machine_event_end_date']).max()
    print(f"  - MES Timeline: {mes_min} to {mes_max}")
    
    # Read last line of CSV for timestamp
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2000))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
        csv_last = None
        for i in range(len(lines)-1, -1, -1):
            try:
                parts = lines[i].split(",")
                csv_last = pd.to_datetime(parts[4].strip('"'))
                break
            except: continue
        print(f"  - CSV Ends At: {csv_last}")
        
        if csv_last and (csv_last < mes_min or csv_last > mes_max):
            print("  - WARNING: CSV data is OUTSIDE MES timeline!")
        else:
            print("  - OK: CSV data overlaps with MES timeline.")
