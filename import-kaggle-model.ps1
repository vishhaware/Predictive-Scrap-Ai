param(
    [string]$BundleJoblib,
    [string]$BundlePath,
    [string]$ModelId,
    [ValidateSet("scrap_classifier", "sensor_forecaster")][string]$Task = "scrap_classifier",
    [string]$Family,
    [string]$MachineId,
    [string]$PartNumber,
    [string]$SegmentId,
    [switch]$Promote,
    [string]$PythonExe,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonExe {
    param(
        [string]$Preferred,
        [string]$RepoRoot
    )
    if ($Preferred) {
        return $Preferred
    }

    $venvPython = Join-Path $RepoRoot "backend_fastapi\venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

$repoRoot = Split-Path -Parent $PSCommandPath
$importScript = Join-Path $repoRoot "backend_fastapi\import_registry_bundle.py"
if (-not (Test-Path $importScript)) {
    throw "Missing importer script: $importScript"
}

$bundleInput = if ($BundleJoblib) { $BundleJoblib } elseif ($BundlePath) { $BundlePath } else { $null }
if (-not $bundleInput) {
    throw "Provide one of: -BundleJoblib or -BundlePath"
}

$bundlePathResolved = Resolve-Path -LiteralPath $bundleInput -ErrorAction Stop
$bundlePath = [string]$bundlePathResolved

if (-not $ModelId) {
    $ModelId = [System.IO.Path]::GetFileNameWithoutExtension($bundlePath)
}

$python = Resolve-PythonExe -Preferred $PythonExe -RepoRoot $repoRoot

$argList = @(
    $importScript,
    "--bundle-joblib", $bundlePath,
    "--model-id", $ModelId,
    "--task", $Task
)
if ($Family) { $argList += @("--family", $Family) }
if ($MachineId) { $argList += @("--machine-id", $MachineId) }
if ($PartNumber) { $argList += @("--part-number", $PartNumber) }
if ($SegmentId) { $argList += @("--segment-id", $SegmentId) }
if ($Promote) { $argList += "--promote" }

Write-Host "Importing Kaggle bundle into registry..." -ForegroundColor Cyan
Write-Host "Bundle : $bundlePath" -ForegroundColor DarkGray
Write-Host "Model  : $ModelId" -ForegroundColor DarkGray
Write-Host "Task   : $Task" -ForegroundColor DarkGray
if ($Family) { Write-Host "Family : $Family" -ForegroundColor DarkGray }
if ($MachineId) { Write-Host "Machine: $MachineId" -ForegroundColor DarkGray }
if ($PartNumber) { Write-Host "Part   : $PartNumber" -ForegroundColor DarkGray }
if ($SegmentId) { Write-Host "Segment: $SegmentId" -ForegroundColor DarkGray }
Write-Host "Promote: $Promote" -ForegroundColor DarkGray
Write-Host "Python : $python" -ForegroundColor DarkGray

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run command preview:" -ForegroundColor Yellow
    Write-Host "$python $($argList -join ' ')" -ForegroundColor Yellow
    exit 0
}

& $python @argList
if ($LASTEXITCODE -ne 0) {
    throw "Import failed (exit code $LASTEXITCODE)."
}

Write-Host ""
Write-Host "Done. Validate with: GET /api/admin/models" -ForegroundColor Green

