import os
import pandas as pd
from datetime import datetime, timedelta

data_dir = "C:/new project/New folder/frontend/Data"
csv_files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
excel_file = "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"
current_target = datetime(2026, 2, 28, 0, 0, 0)
TAIL_LINES = 100000

# 1. Excel (Already good)
print("Checking Excel...")

# 2. Ultra Fast CSV
for f_name in csv_files:
    path = os.path.join(data_dir, f_name)
    if not os.path.exists(path): continue
    
    print(f"Ultra-fast processing {f_name}...")
    
    with open(path, "rb") as f:
        # Read header
        header = f.readline().decode("utf-8", errors="ignore")
        # Go to end and read back 20MB (approx 200k lines)
        f.seek(0, 2)
        size = f.tell()
        read_size = 20 * 1024 * 1024
        f.seek(max(0, size - read_size))
        raw_tail = f.read().decode("utf-8", errors="ignore")
        lines = raw_tail.splitlines()
        # The first line might be partial
        data_lines = lines[1:] if len(lines) > 1 else lines
        tail_data = data_lines[-TAIL_LINES:]
    
    if not tail_data: continue
    
    # Find last timestamp
    last_dt = None
    for i in range(len(tail_data)-1, -1, -1):
        try:
            parts = tail_data[i].split(",")
            last_dt = datetime.strptime(parts[4].strip('"'), "%Y-%m-%d %H:%M:%S.%f")
            break
        except: continue
        
    if not last_dt: continue
        
    delta = current_target - last_dt
    print(f"Shifting {f_name} by {delta}")
    
    temp_path = path + ".ultra.tmp"
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
            
    os.replace(temp_path, path)
    print(f"Shifted {f_name}")

print("Ultra-fast shift completed.")
