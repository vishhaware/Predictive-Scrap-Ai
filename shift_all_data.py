import os
import pandas as pd
from datetime import datetime, timedelta

data_dir = "C:/new project/New folder/frontend/Data"
csv_files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
excel_file = "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"
# We want the data to end exactly at "now"
current_target = datetime(2026, 2, 27, 23, 0, 0)

# 1. Shift Excel
excel_path = os.path.join(data_dir, excel_file)
if os.path.exists(excel_path):
    print("Shifting Excel dates...")
    df_excel = pd.read_excel(excel_path, sheet_name="Data")
    # Finding the latest date in Excel
    date_cols = ['machine_event_end_date', 'machine_event_create_date', 'plant_shift_date']
    latest_excel = None
    for col in date_cols:
        if col in df_excel.columns:
            ts = pd.to_datetime(df_excel[col]).max()
            if latest_excel is None or ts > latest_excel:
                latest_excel = ts
    
    if latest_excel:
        excel_delta = current_target - latest_excel.to_pydatetime()
        print(f"Excel latest was {latest_excel}, shifting by {excel_delta}")
        for col in df_excel.columns:
            if 'date' in col.lower() or 'time' in col.lower() or 'timestamp' in col.lower():
                try:
                    is_time_only = df_excel[col].dtype == 'object' and df_excel[col].str.contains(':').any()
                    if not is_time_only:
                        df_excel[col] = pd.to_datetime(df_excel[col]) + excel_delta
                except:
                    pass
        df_excel.to_excel(excel_path, index=False, sheet_name="Data")
        print("Excel shifted.")

# 2. Shift CSVs
for f_name in csv_files:
    path = os.path.join(data_dir, f_name)
    if not os.path.exists(path):
        continue
    
    print(f"Processing {f_name}...")
    temp_path = path + ".tmp"
    
    last_dt = None
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 5000))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
        for i in range(len(lines)-1, -1, -1):
            try:
                parts = lines[i].split(",")
                if len(parts) > 5:
                    ts_str = parts[4].strip('"')
                    last_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    break
            except: continue
    
    if not last_dt:
        print(f"Skip {f_name}: No timestamp")
        continue
        
    delta = current_target - last_dt
    print(f"Shifting {f_name} by {delta}")
    
    with open(path, "r", encoding="utf-8") as f_in, open(temp_path, "w", encoding="utf-8", newline="") as f_out:
        header = f_in.readline()
        f_out.write(header)
        for line in f_in:
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
                except: f_out.write(line)
            else: f_out.write(line)

    import os
    os.replace(temp_path, path)
    print(f"Finished {f_name}")
