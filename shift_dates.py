import os
import pandas as pd
from datetime import datetime, timedelta

data_dir = "C:/new project/New folder/frontend/Data"
files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
target_date = datetime(2026, 2, 16, 12, 0, 0) # Shift so end is near Feb 16

for f_name in files:
    path = os.path.join(data_dir, f_name)
    if not os.path.exists(path):
        continue
    
    print(f"Processing {f_name}...")
    # Since files are huge, we need to process them in a memory-efficient way or just shift the whole thing.
    # Actually, let's just shift the dates in a small sample if it's for demo, but the user wants "all file update".
    # Shifting 800MB in memory is hard. Let's do it chunk by chunk.
    
    temp_path = path + ".tmp"
    
    # First, find the max date in the file to compute the delta
    last_dt = None
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 2000))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()
        for i in range(len(lines)-1, -1, -1):
            try:
                # Format is "device_name","machine_definition","variable_name","value","timestamp",...
                parts = lines[i].split(",")
                if len(parts) > 5:
                    ts_str = parts[4].strip('"')
                    last_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
                    break
            except:
                continue
    
    if not last_dt:
        print(f"Could not find timestamp in {f_name}")
        continue
        
    delta = target_date - last_dt
    print(f"Shifting {f_name} by {delta}")
    
    with open(path, "r", encoding="utf-8") as f_in, open(temp_path, "w", encoding="utf-8", newline="") as f_out:
        header = f_in.readline()
        f_out.write(header)
        count = 0
        for line in f_in:
            # We only need to shift the timestamp column (index 4) and date column (index 10)
            # "device_name","machine_definition","variable_name","value","timestamp","variable_attribute","device","machine_def","year","month","date"
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
                except:
                    f_out.write(line)
            else:
                f_out.write(line)
            count += 1
            if count % 100000 == 0:
                print(f"Processed {count} lines...")

    os.remove(path)
    os.rename(temp_path, path)
    print(f"Finished {f_name}")
