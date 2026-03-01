import sys
sys.path.insert(0, r'c:\new project\New folder\backend_fastapi')
import engine

print('=== THRESHOLDS ===')
for k, v in engine.THRESHOLDS.items():
    print(f"  {k}: weight={v['weight']}  critical={v['critical']}  tolerance={v['tolerance']}")

print()
print('=== VAR_KEY_MAP ===')
for k, v in engine.VAR_KEY_MAP.items():
    print(f"  {k} -> {v}")

print()
total_weight = sum(v['weight'] for v in engine.THRESHOLDS.values())
print(f'Total weight sum: {total_weight:.2f} (should be close to 1.0)')

new_threshold_vars = [k for k in engine.THRESHOLDS if k in ('Shot_size', 'Ejector_fix_deviation_torque', 'Cyl_tmp_z8')]
new_map_vars = [k for k in engine.VAR_KEY_MAP if k in ('Shot_size', 'Ejector_fix_deviation_torque', 'Cyl_tmp_z8', 'Cyl_tmp_z6', 'Cyl_tmp_z7')]
print(f'NEW VARS IN THRESHOLDS: {new_threshold_vars}')
print(f'NEW VARS IN VAR_KEY_MAP: {new_map_vars}')
print()
print('=== DEPENDENCIES (new entries) ===')
for k in ('Shot_size', 'Ejector_fix_deviation_torque', 'Cyl_tmp_z8'):
    if k in engine.DEPENDENCIES:
        print(f"  {k}: {engine.DEPENDENCIES[k]}")
print("Validation PASSED" if len(new_threshold_vars) == 3 and len(new_map_vars) == 5 else "Validation FAILED")
