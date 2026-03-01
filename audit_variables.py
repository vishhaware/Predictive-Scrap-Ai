"""
Deep variable analysis:
- CSV variables vs what backend maps/uses
- MES columns that could improve model
- Scrap_counter correlation
"""
import pandas as pd
import numpy as np
import re

# ── 1. Read a bigger CSV sample ──────────────────────────────────────────────
print("="*70)
print("DETAILED CSV VARIABLE ANALYSIS (M231-11, 200k rows)")
print("="*70)

df = pd.read_csv(
    r"c:\new project\New folder\frontend\Data\M231-11.csv",
    nrows=200_000,
    low_memory=False,
)

# Pivot: group by timestamp → wide format
print(f"Raw shape: {df.shape}")
print(f"Variable column: 'variable_name'")
print(f"Value column: 'value'")
print()

# Stats per variable
print("-- Per-Variable Stats --")
for var in sorted(df["variable_name"].unique()):
    vals = pd.to_numeric(df[df["variable_name"]==var]["value"], errors="coerce").dropna()
    if len(vals) == 0:
        print(f"  {var}: ALL NON-NUMERIC - sample={df[df['variable_name']==var]['value'].iloc[0]}")
    else:
        print(f"  {var}: count={len(vals)}  min={vals.min():.3f}  max={vals.max():.3f}  mean={vals.mean():.3f}  std={vals.std():.3f}  nulls={df[df['variable_name']==var]['value'].isna().sum()}")

# ── 2. Pivot sample to wide format and check correlations ────────────────────
print()
print("="*70)
print("WIDE FORMAT (pivot) — correlation with Scrap_counter")
print("="*70)

# Use a chunk to pivot
df_chunk = df.head(50000).copy()
df_chunk["timestamp"] = pd.to_datetime(df_chunk["timestamp"], errors="coerce")
df_chunk["value_num"] = pd.to_numeric(df_chunk["value"], errors="coerce")

pivot = df_chunk.pivot_table(
    index="timestamp",
    columns="variable_name",
    values="value_num",
    aggfunc="first",
)
pivot = pivot.sort_index().ffill().fillna(0)
print(f"Pivot shape: {pivot.shape}")
print(f"Columns: {list(pivot.columns)}")

if "Scrap_counter" in pivot.columns and len(pivot) > 10:
    print()
    print("-- Correlation with Scrap_counter --")
    corr = pivot.corr()["Scrap_counter"].drop("Scrap_counter").sort_values(key=abs, ascending=False)
    print(corr.to_string())

# ── 3. Check Shot_size and new variables ─────────────────────────────────────
print()
print("="*70)
print("VARIABLES FOUND IN CSV but MISSING from backend VAR_KEY_MAP")
print("="*70)
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
}
all_csv_vars = sorted(df["variable_name"].unique())
mapped = set(VAR_KEY_MAP.keys())
missing = [v for v in all_csv_vars if v not in mapped]
print(f"Total CSV vars: {len(all_csv_vars)}")
print(f"Mapped in backend: {len(mapped)}")
print(f"MISSING: {missing}")

# ── 4. MES join opportunity ──────────────────────────────────────────────────
print()
print("="*70)
print("MES JOIN OPPORTUNITY — scrap/yield by machine+date")
print("="*70)

mes = pd.read_excel(
    r"c:\new project\New folder\frontend\Data\MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx",
    sheet_name="Data",
)
mes["plant_shift_date"] = pd.to_datetime(mes["plant_shift_date"], errors="coerce")
mes["machine_id_norm"] = mes["machine_id"]  # already M-231 format

# Show M-231 scrap data
m231_mes = mes[mes["machine_id"]=="M-231"].copy()
print(f"\nM-231 MES rows: {len(m231_mes)}")
print(f"Date range: {m231_mes['plant_shift_date'].min().date()} to {m231_mes['plant_shift_date'].max().date()}")
print("\nScrap by date (last 10):")
scrap_by_date = m231_mes.groupby("plant_shift_date")[["scrap_quantity","yield_quantity","strokes_yield_quantity"]].sum()
print(scrap_by_date.tail(10).to_string())

print()
print("Part number -> scrap for M-231:")
part_scrap = m231_mes.groupby("part_number")[["scrap_quantity","yield_quantity"]].sum()
part_scrap["scrap_rate_%"] = (part_scrap["scrap_quantity"] / (part_scrap["yield_quantity"]+part_scrap["scrap_quantity"]) * 100).round(2)
print(part_scrap.sort_values("scrap_rate_%", ascending=False).to_string())

print()
print("ANALYSIS COMPLETE")
