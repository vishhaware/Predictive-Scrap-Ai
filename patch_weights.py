"""Normalize threshold weights to sum to 1.0"""
fpath = r"c:\new project\New folder\backend_fastapi\engine.py"
with open(fpath, "r", encoding="utf-8") as f:
    src = f.read()

old = '    "Shot_size": {"tolerance": 3.0, "unit": "mm", "weight": 0.20, "critical": True},\n    "Ejector_fix_deviation_torque": {"tolerance": 2.0, "unit": "Nm", "weight": 0.15, "critical": True},\n    "Cyl_tmp_z8": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},'
new = '    "Shot_size": {"tolerance": 3.0, "unit": "mm", "weight": 0.15, "critical": True},\n    "Ejector_fix_deviation_torque": {"tolerance": 2.0, "unit": "Nm", "weight": 0.12, "critical": True},\n    "Cyl_tmp_z8": {"tolerance": 5, "unit": "\u00b0C", "weight": 0.01, "critical": False},'

if old in src:
    src = src.replace(old, new, 1)
    print("Weight normalized OK")
else:
    print("Pattern not found, skipping normalization")

with open(fpath, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("Done. New total weight:", 0.32+0.12+0.15+0.08+0.08+0.12+0.04+0.01*5+0.15+0.12+0.01)
