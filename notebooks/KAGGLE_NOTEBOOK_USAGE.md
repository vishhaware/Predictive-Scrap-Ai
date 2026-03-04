# Kaggle Notebook Usage

Two templates are available:

1. `notebooks/kaggle_horizon_training_template.ipynb`
2. `notebooks/kaggle_registry_bundle_training_template.ipynb`

## 1) Horizon artifacts notebook

Use `kaggle_horizon_training_template.ipynb` to produce files fully compatible with this backend loader (`backend_fastapi/data_access.py`):

- `scrap_30m_model.joblib`
- `scrap_30m_scaler.joblib`
- `scrap_30m_feature_list.joblib`
- `scrap_30m_metadata.json`
- `scrap_240m_model.joblib`
- `scrap_240m_scaler.joblib`
- `scrap_240m_feature_list.joblib`
- `scrap_240m_metadata.json`
- `scrap_1440m_model.joblib`
- `scrap_1440m_scaler.joblib`
- `scrap_1440m_feature_list.joblib`
- `scrap_1440m_metadata.json`

### Import into local project (horizon)

1. Download generated zip from Kaggle outputs.
2. Extract and copy `horizon/*` into:
   - `backend_fastapi/models/horizon/`
3. Restart backend.
4. Validate:
   - `GET /api/health`
   - `GET /api/machines/M231-11/chart-data?horizon_minutes=60`
   - `GET /api/fleet/chart-data?horizon_minutes=60`

## 2) Registry bundle notebook

Use `kaggle_registry_bundle_training_template.ipynb` to export a registry bundle artifact (`<MODEL_ID>.pkl`) for `scrap_classifier`.

The artifact payload includes:

- `model`
- `scaler`
- `feature_cols`
- `feature_spec`
- `feature_spec_hash`
- `family`
- `task`
- `decision_threshold`
- `metrics`

### Import + promote locally (registry bundle)

Preferred flow (from `C:\new project\New folder\backend_fastapi`):

```powershell
# 1) Ensure local artifact folder exists
New-Item -ItemType Directory -Force .\downloaded | Out-Null

# 2) Stage latest real Kaggle artifact from Downloads (zip or pkl)
.\stage-kaggle-artifact.ps1

# If artifact is not in Downloads, pass exact path directly:
# .\stage-kaggle-artifact.ps1 -ArtifactPath "D:\somewhere\sfb_registry_bundle_export.zip"

# Note: stage script auto-checks browser download directories from Edge/Chrome
# preferences (for example custom folders on E:/F: drives), not only %USERPROFILE%\Downloads.
# If you see a `.crdownload` file, the download is incomplete; wait for completion or re-download.

# 3) One-shot guarded import + verification
.\recover-kaggle-import.ps1 -Task scrap_classifier -Promote
```

Equivalent command from repo root:

```powershell
.\recover-kaggle-import.ps1 -Task scrap_classifier -Promote
```

Manual flow (explicit bundle path):

```powershell
python backend_fastapi/import_registry_bundle.py `
  --bundle-joblib ".\downloaded\<MODEL_ID>.pkl" `
  --model-id "<MODEL_ID>" `
  --task scrap_classifier `
  --promote
```

Shortcut wrapper (repo root):

```powershell
.\import-kaggle-model.ps1 -BundleJoblib ".\downloaded\<MODEL_ID>.pkl" -Promote
```

Fail-safe bundle discovery snippet (prevents null `$pkl` import call):

```powershell
$pkl = Get-ChildItem .\downloaded -Recurse -File -Filter *.pkl |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

if (-not $pkl) {
  Write-Host "No .pkl found under .\downloaded" -ForegroundColor Yellow
  Get-ChildItem .\downloaded -Recurse -Force
  return
}

.\import-kaggle-model.ps1 -BundleJoblib $pkl.FullName -Task scrap_classifier -Promote
```

Machine-scoped promotion example:

```powershell
.\import-kaggle-model.ps1 `
  -BundleJoblib ".\downloaded\<MODEL_ID>.pkl" `
  -ModelId "<MODEL_ID>" `
  -Task scrap_classifier `
  -MachineId "M231-11" `
  -Promote
```

Then validate:

- `GET /api/admin/models`
- `GET /api/health`
- dashboard future risk behavior

## Kaggle input requirements

1. A dataset with this project files (must contain `backend_fastapi/train_models_from_csv.py`).
2. A dataset folder containing machine CSV files matching `M*.csv`.
3. Optional MES workbook file used by the trainer for context features.

The trainer expects machine CSVs in long format and requires columns:

- `device_name`
- `machine_definition`
- `variable_name`
- `value`
- `timestamp`
- `variable_attribute`
- `device`
- `machine_def`
- `year`
- `month`
- `date`

These requirements apply to both notebooks.
