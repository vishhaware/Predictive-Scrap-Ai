"""Patch data_access.py RAW_TO_FRONTEND_SENSOR_MAP to add new variables"""
fpath = r"c:\new project\New folder\backend_fastapi\data_access.py"
with open(fpath, "r", encoding="utf-8") as f:
    src = f.read()

old = '''\
RAW_TO_FRONTEND_SENSOR_MAP: Dict[str, str] = {
    "Cushion": "cushion",
    "Injection_time": "injection_time",
    "Dosage_time": "dosage_time",
    "Injection_pressure": "injection_pressure",
    "Switch_pressure": "switch_pressure",
    "Cycle_time": "cycle_time",
    "Cyl_tmp_z1": "temp_z1",
    "Cyl_tmp_z2": "temp_z2",
    "Cyl_tmp_z3": "temp_z3",
    "Cyl_tmp_z4": "temp_z4",
    "Cyl_tmp_z5": "temp_z5",
    "Extruder_start_position": "extruder_start_position",
    "Extruder_torque": "extruder_torque",
    "Peak_pressure_time": "peak_pressure_time",
    "Peak_pressure_position": "peak_pressure_position",
    "Switch_position": "switch_position",
    "Machine_status": "machine_status",
    "Scrap_counter": "scrap_counter",
    "Shot_counter": "shot_counter",
}'''

new = '''\
# === CSV Audit: all 25 variables found in M231-11.csv ===
# New high-correlation variables added: Shot_size (0.9999), Ejector_fix_deviation_torque (0.990)
# Flatline/dead sensors (std==0): Cyl_tmp_z2, Cyl_tmp_z6, Cyl_tmp_z7, Extruder_torque (still mapped for telemetry)
RAW_TO_FRONTEND_SENSOR_MAP: Dict[str, str] = {
    "Cushion": "cushion",
    "Injection_time": "injection_time",
    "Dosage_time": "dosage_time",
    "Injection_pressure": "injection_pressure",
    "Switch_pressure": "switch_pressure",
    "Cycle_time": "cycle_time",
    "Cyl_tmp_z1": "temp_z1",
    "Cyl_tmp_z2": "temp_z2",
    "Cyl_tmp_z3": "temp_z3",
    "Cyl_tmp_z4": "temp_z4",
    "Cyl_tmp_z5": "temp_z5",
    # NEW: CSV Audit high-correlation variables
    "Shot_size": "shot_size",                           # corr=0.9999 with Scrap_counter!
    "Ejector_fix_deviation_torque": "ejector_torque",  # corr=0.990  with Scrap_counter
    "Cyl_tmp_z8": "temp_z8",                           # active zone 50-60C, corr=0.9999
    "Cyl_tmp_z6": "temp_z6",                           # flatline (0) - pass-through
    "Cyl_tmp_z7": "temp_z7",                           # flatline (0) - pass-through
    # Existing pass-through mappings
    "Extruder_start_position": "extruder_start_position",
    "Extruder_torque": "extruder_torque",
    "Peak_pressure_time": "peak_pressure_time",
    "Peak_pressure_position": "peak_pressure_position",
    "Switch_position": "switch_position",
    "Machine_status": "machine_status",
    "Scrap_counter": "scrap_counter",
    "Shot_counter": "shot_counter",
    # Note: Time_on_machine is HH:MM:SS string - not mapped (not numeric)
}'''

# Normalize line endings
src_n = src.replace('\r\n', '\n').replace('\r', '\n')
old_n = old.replace('\r\n', '\n')

if old_n in src_n:
    src_n = src_n.replace(old_n, new, 1)
    print("Patched RAW_TO_FRONTEND_SENSOR_MAP OK")
else:
    print("NOT FOUND")

with open(fpath, "w", encoding="utf-8", newline="\n") as f:
    f.write(src_n)
print("Done")
