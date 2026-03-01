import pandas as pd
import numpy as np

SEP = "=" * 70

# ─── AUDIT 1: MES Excel ───────────────────────────────────────────────────────
print(SEP)
print("AUDIT 1: MES_Manufacturing Excel (MES data)")
print(SEP)

mes = pd.read_excel(
    r"c:\new project\New folder\frontend\Data\MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx",
    sheet_name="Data",
)
print(f"Shape: {mes.shape[0]} rows x {mes.shape[1]} cols")
print()

print("-- Columns & Dtypes --")
for c in mes.columns:
    nulls = int(mes[c].isna().sum())
    notnull = mes[c].dropna()
    sample = str(notnull.iloc[0]) if len(notnull) > 0 else "ALL NULL"
    print(f"  [{c}]  dtype={mes[c].dtype}  nulls={nulls}/{len(mes)}  sample={sample!r}")

print()
print("-- Machine IDs --")
print(mes["machine_id"].value_counts().to_string())

print()
print("-- Part Numbers (top 20) --")
pn = mes["part_number"].dropna()
pn_valid = pn[pn.astype(str).str.strip().str.lower().isin(["nan","none","null","n/a","","ad"]) == False]
print(f"Total rows: {len(pn)}, Valid parts: {len(pn_valid)}, Unique: {pn_valid.nunique()}")
print(pn_valid.value_counts().head(20).to_string())

print()
print("-- Machine x Part cross-table (top combos) --")
mes_clean = mes.copy()
mes_clean["part_number"] = mes_clean["part_number"].astype(str).str.strip()
mes_clean = mes_clean[mes_clean["part_number"].str.lower().isin(["nan","none","null","n/a","","ad"]) == False]
cross = mes_clean.groupby(["machine_id","part_number"]).size().reset_index(name="count")
cross = cross.sort_values(["machine_id","count"], ascending=[True,False])
print(cross.to_string(index=False))

print()
print("-- Date Range --")
date_col = "plant_shift_date" if "plant_shift_date" in mes.columns else "machine_event_create_date"
if date_col in mes.columns:
    dates = pd.to_datetime(mes[date_col], errors="coerce").dropna()
    print(f"  min={dates.min().date()}  max={dates.max().date()}  total_dates={len(dates)}")

print()
key_num_cols = [
    "yield_quantity","scrap_quantity","machine_production_time_seconds_quantity",
    "strokes_yield_quantity","strokes_total_quantity"
]
print("-- Numeric Columns Summary --")
for col in key_num_cols:
    if col in mes.columns:
        s = mes[col].dropna()
        print(f"  {col}: min={s.min():.0f}  max={s.max():.0f}  mean={s.mean():.1f}  nulls={int(mes[col].isna().sum())}")

# ─── AUDIT 2: CSV Sensor Files ─────────────────────────────────────────────────
print()
print(SEP)
print("AUDIT 2: CSV Sensor Files")
print(SEP)

import os, csv as csv_mod
DATA_DIR = r"c:\new project\New folder\frontend\Data"
machines = ["M231-11","M356-57","M471-23","M607-30","M612-33"]

for mid in machines:
    fpath = os.path.join(DATA_DIR, f"{mid}.csv")
    if not os.path.exists(fpath):
        print(f"  {mid}: FILE NOT FOUND")
        continue

    size_mb = os.path.getsize(fpath) / 1024 / 1024
    # Read first 50_000 rows fast
    df_sample = pd.read_csv(fpath, nrows=50000, low_memory=False)
    row_est = int(size_mb / (os.path.getsize(fpath) / 1024 / 1024) * len(df_sample))  # rough

    print(f"\n  [{mid}] size={size_mb:.0f}MB  cols={list(df_sample.columns)}")
    print(f"    Sample rows(50k): {len(df_sample)}")

    ts_col = None
    for c in ["timestamp","Timestamp","time","Time"]:
        if c in df_sample.columns:
            ts_col = c
            break
    if ts_col:
        ts = pd.to_datetime(df_sample[ts_col], errors="coerce").dropna()
        print(f"    Timestamps: min={ts.min()}  max={ts.max()}")

    # Variable names
    var_col = None
    for c in ["variable_name","variable","VariableName"]:
        if c in df_sample.columns:
            var_col = c
            break
    if var_col:
        vars_found = df_sample[var_col].dropna().unique()
        print(f"    Variables ({len(vars_found)}): {sorted(vars_found)}")

    val_col = "value" if "value" in df_sample.columns else None
    if val_col:
        val = pd.to_numeric(df_sample[val_col], errors="coerce").dropna()
        print(f"    Value range: min={val.min():.4f}  max={val.max():.4f}")

    # Check machine_definition column
    mdef_col = "machine_definition" if "machine_definition" in df_sample.columns else None
    if mdef_col:
        print(f"    machine_definition values: {df_sample[mdef_col].unique()}")

    # Cross: what part_number info is in CSV?
    part_col = "part_number" if "part_number" in df_sample.columns else None
    if part_col:
        print(f"    part_number in CSV: {df_sample[part_col].dropna().unique()[:10]}")
    else:
        print(f"    part_number in CSV: NOT FOUND (normal - part info only in MES xlsx)")

print()
print(SEP)
print("AUDIT 3: CSV <-> MES Machine ID Mapping")
print(SEP)
print("CSV files use: M231-11, M356-57 etc.")
print("MES Excel uses: M-231, M-356 etc.")
print("Backend mapping: extracts 3-digit code from either format")
for mid in machines:
    import re
    code = re.search(r"(\d{3})", mid)
    mes_id = f"M-{code.group(1)}" if code else "UNKNOWN"
    mes_machines = mes["machine_id"].unique()
    match = mes_id in mes_machines
    parts = mes[mes["machine_id"]==mes_id]["part_number"].dropna()
    parts_valid = parts[parts.astype(str).str.strip().str.lower().isin(["nan","none","null","n/a","","ad"])==False]
    print(f"  CSV {mid} -> MES {mes_id} -> match={match} -> unique_parts={parts_valid.nunique()}")

print()
print("AUDIT COMPLETE")
