"""
Patch engine.py in-place to add new high-correlation variables discovered by CSV audit:
- Shot_size (corr=0.9999 with Scrap_counter)
- Ejector_fix_deviation_torque (corr=0.990)
- Cyl_tmp_z8 (active temp zone 50-60 deg C)
"""
import re

fpath = r"c:\new project\New folder\backend_fastapi\engine.py"
with open(fpath, "r", encoding="utf-8") as f:
    src = f.read()

# ── Patch 1: THRESHOLDS ─────────────────────────────────────────────────────
old_thresholds = '''\
# --- Thresholds from Technical specification document ---
THRESHOLDS = {
    "Cushion": {"tolerance": 0.5, "unit": "mm", "weight": 0.40, "critical": True},
    "Injection_time": {"tolerance": 0.03, "unit": "s", "weight": 0.15, "critical": True},
    "Dosage_time": {"tolerance": 1.0, "unit": "s", "weight": 0.20, "critical": True},
    "Injection_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.10, "critical": False},
    "Switch_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.10, "critical": False},
    "Switch_position": {"tolerance": 0.05, "unit": "mm", "weight": 0.15, "critical": True},
    "Cycle_time": {"tolerance": 2.0, "unit": "s", "weight": 0.05, "critical": False},
    "Cyl_tmp_z1": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.02, "critical": False},
    "Cyl_tmp_z2": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.02, "critical": False},
    "Cyl_tmp_z3": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.02, "critical": False},
    "Cyl_tmp_z4": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    "Cyl_tmp_z5": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
}'''

new_thresholds = '''\
# --- Thresholds from Technical specification + CSV Data Audit ---
# Weights updated: Shot_size and Ejector_torque added as critical high-corr features
# (correlation with Scrap_counter: Shot_size=0.9999, Ejector_fix=0.990)
THRESHOLDS = {
    "Cushion": {"tolerance": 0.5, "unit": "mm", "weight": 0.32, "critical": True},
    "Injection_time": {"tolerance": 0.03, "unit": "s", "weight": 0.12, "critical": True},
    "Dosage_time": {"tolerance": 1.0, "unit": "s", "weight": 0.15, "critical": True},
    "Injection_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.08, "critical": False},
    "Switch_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.08, "critical": False},
    "Switch_position": {"tolerance": 0.05, "unit": "mm", "weight": 0.12, "critical": True},
    "Cycle_time": {"tolerance": 2.0, "unit": "s", "weight": 0.04, "critical": False},
    "Cyl_tmp_z1": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    "Cyl_tmp_z2": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    "Cyl_tmp_z3": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    "Cyl_tmp_z4": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    "Cyl_tmp_z5": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},
    # === NEW: CSV Audit discoveries (high correlation with Scrap_counter) ===
    "Shot_size": {"tolerance": 3.0, "unit": "mm", "weight": 0.20, "critical": True},             # corr=0.9999 CRITICAL
    "Ejector_fix_deviation_torque": {"tolerance": 2.0, "unit": "Nm", "weight": 0.15, "critical": True},  # corr=0.990
    "Cyl_tmp_z8": {"tolerance": 5, "unit": "\\u00b0C", "weight": 0.01, "critical": False},       # active 50-60C zone
}'''

# ── Patch 2: DEPENDENCIES ───────────────────────────────────────────────────
old_deps = '''\
# Industry Domain Logic: Variable Dependency Map
# Based on "AI_cup_parameter_info.xlsx"
DEPENDENCIES = {
    "Dosage_time": ["Cushion", "Cycle_time", "Injection_pressure", "Injection_time"],
    "Switch_position": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Extruder_start_position": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z1": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z2": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z3": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z4": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z5": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"]
}'''

new_deps = '''\
# Industry Domain Logic: Variable Dependency Map
# Based on "AI_cup_parameter_info.xlsx" + CSV correlation audit
DEPENDENCIES = {
    "Dosage_time": ["Cushion", "Cycle_time", "Injection_pressure", "Injection_time", "Shot_size"],
    "Switch_position": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure", "Shot_size"],
    "Extruder_start_position": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z1": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z2": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z3": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z4": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    "Cyl_tmp_z5": ["Cushion", "Injection_time", "Dosage_time", "Injection_pressure", "Switch_pressure"],
    # Shot_size controls material volume -> directly affects cushion/dosage/switch position
    "Shot_size": ["Cushion", "Dosage_time", "Injection_pressure", "Switch_position"],
    # Ejector torque deviation -> signals mould release problems -> links to cycle/cushion
    "Ejector_fix_deviation_torque": ["Cushion", "Cycle_time", "Switch_position"],
    "Cyl_tmp_z8": ["Cyl_tmp_z1", "Cyl_tmp_z3", "Cyl_tmp_z5"],
}'''

# ── Patch 3: VAR_KEY_MAP ────────────────────────────────────────────────────
old_vkm = '''\
VAR_KEY_MAP = {
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

new_vkm = '''\
VAR_KEY_MAP = {
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
    # === NEW: CSV Audit discoveries ===
    "Shot_size": "shot_size",                           # corr=0.9999 with Scrap_counter (CRITICAL)
    "Ejector_fix_deviation_torque": "ejector_torque",  # corr=0.990  with Scrap_counter (CRITICAL)
    "Cyl_tmp_z8": "temp_z8",                           # active temp zone 50-60C
    # Pass-through (flatline/dead sensors if std==0, kept for telemetry display)
    "Cyl_tmp_z6": "temp_z6",
    "Cyl_tmp_z7": "temp_z7",
    "Extruder_start_position": "extruder_start_position",
    "Extruder_torque": "extruder_torque",
    "Peak_pressure_time": "peak_pressure_time",
    "Peak_pressure_position": "peak_pressure_position",
    "Switch_position": "switch_position",
    "Machine_status": "machine_status",
    "Scrap_counter": "scrap_counter",
    "Shot_counter": "shot_counter",
    # Time_on_machine is HH:MM:SS string - not numeric, intentionally excluded
}'''

# Apply patches (strip \r before searching, to handle mixed line-endings)
src_clean = src.replace('\r\n', '\n').replace('\r', '\n')

patches = [
    (old_thresholds, new_thresholds),
    (old_deps, new_deps),
    (old_vkm, new_vkm),
]

result = src_clean
for old, new in patches:
    old_clean = old.replace('\r\n', '\n').replace('\r', '\n')
    if old_clean in result:
        result = result.replace(old_clean, new, 1)
        print(f"  Patched: {old_clean[:60].strip()!r}...")
    else:
        print(f"  WARNING: Could not find:\n    {old_clean[:80].strip()!r}")

with open(fpath, "w", encoding="utf-8", newline="\n") as f:
    f.write(result)

print("\nengine.py patch complete!")
