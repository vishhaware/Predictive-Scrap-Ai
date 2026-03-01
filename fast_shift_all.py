import os
import pandas as pd
from datetime import datetime, timedelta

data_dir = "C:/new project/New folder/frontend/Data"
csv_files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
excel_file = "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"
current_target = datetime(2026, 3, 1, 10, 0, 0) # Align with current local time approx
TAIL_LINES = 100000

# 1. Shift Excel (Fast, already done but good to be safe)
excel_path = os.path.join(data_dir, excel_file)
if os.path.exists(excel_path):
    print("Shifting Excel dates...")
    df_excel = pd.read_excel(excel_path, sheet_name="Data")
    date_cols = ['machine_event_end_date', 'machine_event_create_date', 'plant_shift_date']
    latest_excel = None
    for col in date_cols:
        if col in df_excel.columns:
            ts = pd.to_datetime(df_excel[col]).max()
            if latest_excel is None or ts > latest_excel: latest_excel = ts
    
    if latest_excel:
        excel_delta = current_target - latest_excel.to_pydatetime()
        if abs(excel_delta.total_seconds()) > 3600:
            print(f"Excel latest was {latest_excel}, shifting by {excel_delta}")
            for col in df_excel.columns:
                if any(x in col.lower() for x in ['date', 'time', 'timestamp']):
                    try:
                        is_time_only = df_excel[col].dtype == 'object' and df_excel[col].str.contains(':').any()
                        if not is_time_only:
                            df_excel[col] = pd.to_datetime(df_excel[col]) + excel_delta
                    except: pass
            df_excel.to_excel(excel_path, index=False, sheet_name="Data")
    print("Excel check done.")

# 2. Fast Shift CSVs
for f_name in csv_files:
    path = os.path.join(data_dir, f_name)
    if not os.path.exists(path): continue
    
    print(f"Fast processing {f_name}...")
    
    # Read header
    with open(path, "r", encoding="utf-8") as f:
        header = f.readline()
        
    # Read tail efficiently
    import subprocess
    try:
        # Use powershell to get tail quickly
        cmd = f'powershell -Command "Get-Content \'{path}\' -Tail {TAIL_LINES}"'
        tail_data = subprocess.check_output(cmd, shell=True).decode("utf-8", errors="ignore").splitlines()
    except:
        print(f"Failed to tail {f_name}, skipping.")
        continue
        
    if not tail_data: continue
    
    # Find last timestamp to compute delta
    last_dt = None
    for i in range(len(tail_data)-1, -1, -1):
        try:
            parts = tail_data[i].split(",")
            last_dt = datetime.strptime(parts[4].strip('"'), "%Y-%m-%d %H:%M:%S.%f")
            break
        except: continue
        
    if not last_dt: 
        print(f"No timestamp found in tail of {f_name}")
        continue
        
    delta = current_target - last_dt
    print(f"Shifting {f_name} by {delta} (Lines: {len(tail_data)})")
    
    temp_path = path + ".fast.tmp"
    with open(temp_path, "w", encoding="utf-8", newline="") as f_out:
        f_out.write(header)
        for line in tail_data:
            parts = line.strip().split(",")
            if len(parts) >= 11:
                try:
                    ts_str = parts[4].strip('"')
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    new_dt = dt + delta
                    parts[4] = f'"{new_dt.strftime("%Y-%m-%d %H:%M:%S.%f")}"'
                    parts[8] = f'"{new_dt.year}"'
                    parts[9] = f'"{new_dt.month:02d}"'
                    parts[10] = f'"{new_dt.strftime("%Y-%m-%d")}"'
                    f_out.write(",".join(parts) + "\n")
                except: f_out.write(line + "\n")
            else: f_out.write(line + "\n")
            
    # Swap
    try:
        os.replace(temp_path, path)
        print(f"Successfully truncated and shifted {f_name}")
    except Exception as e:
        print(f"Error swapping {f_name}: {e}")

print("Fast shift completed.")
