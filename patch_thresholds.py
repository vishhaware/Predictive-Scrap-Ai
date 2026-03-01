"""Patch THRESHOLDS in engine.py - handles the exact line ending format"""
fpath = r"c:\new project\New folder\backend_fastapi\engine.py"
with open(fpath, "r", encoding="utf-8") as f:
    src = f.read()

old = '# --- Thresholds from Technical specification document ---\nTHRESHOLDS = {\n    "Cushion": {"tolerance": 0.5, "unit": "mm", "weight": 0.40, "critical": True},\n    "Injection_time": {"tolerance": 0.03, "unit": "s", "weight": 0.15, "critical": True},\n    "Dosage_time": {"tolerance": 1.0, "unit": "s", "weight": 0.20, "critical": True},\n    "Injection_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.10, "critical": False},\n    "Switch_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.10, "critical": False},\n    "Switch_position": {"tolerance": 0.05, "unit": "mm", "weight": 0.15, "critical": True},\n    "Cycle_time": {"tolerance": 2.0, "unit": "s", "weight": 0.05, "critical": False},\n    "Cyl_tmp_z1": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.02, "critical": False},\n    "Cyl_tmp_z2": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.02, "critical": False},\n    "Cyl_tmp_z3": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.02, "critical": False},\n    "Cyl_tmp_z4": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    "Cyl_tmp_z5": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n}'

new = '# --- Thresholds from Technical specification + CSV Data Audit ---\n# CSV Audit corr with Scrap_counter: Shot_size=0.9999, Ejector_fix=0.990, Cyl_tmp_z8 active\nTHRESHOLDS = {\n    "Cushion": {"tolerance": 0.5, "unit": "mm", "weight": 0.32, "critical": True},\n    "Injection_time": {"tolerance": 0.03, "unit": "s", "weight": 0.12, "critical": True},\n    "Dosage_time": {"tolerance": 1.0, "unit": "s", "weight": 0.15, "critical": True},\n    "Injection_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.08, "critical": False},\n    "Switch_pressure": {"tolerance": 100, "unit": "bar", "weight": 0.08, "critical": False},\n    "Switch_position": {"tolerance": 0.05, "unit": "mm", "weight": 0.12, "critical": True},\n    "Cycle_time": {"tolerance": 2.0, "unit": "s", "weight": 0.04, "critical": False},\n    "Cyl_tmp_z1": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    "Cyl_tmp_z2": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    "Cyl_tmp_z3": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    "Cyl_tmp_z4": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    "Cyl_tmp_z5": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n    # === NEW from CSV Audit: high correlation with Scrap_counter ===\n    "Shot_size": {"tolerance": 3.0, "unit": "mm", "weight": 0.20, "critical": True},\n    "Ejector_fix_deviation_torque": {"tolerance": 2.0, "unit": "Nm", "weight": 0.15, "critical": True},\n    "Cyl_tmp_z8": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},\n}'

if old in src:
    src = src.replace(old, new, 1)
    print("Patched THRESHOLDS OK")
else:
    print("NOT FOUND - trying unicode escape version...")
    old2 = old.replace('\u00b0', '\\u00b0')
    if old2 in src:
        src = src.replace(old2, new, 1)
        print("Patched with escape OK")
    else:
        # Show what we have near THRESHOLDS
        idx = src.find('THRESHOLDS = {')
        end = src.find('}', idx)
        print("FOUND BLOCK:", repr(src[idx:end+2]))

with open(fpath, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("Done")
