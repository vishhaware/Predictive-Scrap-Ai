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

function Show-BundleDiscoveryHints {
    param(
        [string[]]$CandidateDirs
    )

    Write-Host ""
    Write-Host "No bundle path was provided." -ForegroundColor Yellow
    Write-Host "Checked candidate directories for *.pkl files:" -ForegroundColor Yellow

    foreach ($dir in ($CandidateDirs | Select-Object -Unique)) {
        Write-Host " - $dir" -ForegroundColor DarkGray
        if (-not (Test-Path $dir)) {
            Write-Host "   directory does not exist" -ForegroundColor DarkGray
            continue
        }

        $pkls = @(Get-ChildItem -Path $dir -Recurse -File -Filter *.pkl -ErrorAction SilentlyContinue)
        if ($pkls.Count -eq 0) {
            Write-Host "   no .pkl files found" -ForegroundColor DarkGray
            continue
        }

        $latest = $pkls | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        Write-Host "   found $($pkls.Count) .pkl file(s); latest: $($latest.FullName)" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "Next step: download Kaggle output and place/extract it into .\downloaded, then rerun this script." -ForegroundColor Yellow
}

function Resolve-PythonExe {
    param(
        [string]$Preferred,
        [string]$PythonHome
    )
    if ($Preferred) {
        return $Preferred
    }

    $venvPython = Join-Path $PythonHome "venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$candidateImportScripts = @(
    (Join-Path $scriptRoot "backend_fastapi\import_registry_bundle.py"),
    (Join-Path $scriptRoot "import_registry_bundle.py")
)
$importScript = $candidateImportScripts | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $importScript) {
    throw "Missing importer script. Checked: $($candidateImportScripts -join ', ')"
}
$pythonHome = Split-Path -Parent $importScript

$bundleInput = if ($BundleJoblib) { $BundleJoblib } elseif ($BundlePath) { $BundlePath } else { $null }
if (-not $bundleInput) {
    $candidateBundleDirs = @(
        (Join-Path (Get-Location).Path "downloaded"),
        (Join-Path $scriptRoot "downloaded"),
        (Join-Path $scriptRoot "backend_fastapi\downloaded"),
        (Join-Path $pythonHome "downloaded")
    )
    Show-BundleDiscoveryHints -CandidateDirs $candidateBundleDirs
    throw "Provide one of: -BundleJoblib or -BundlePath"
}

$bundlePathResolved = $null
try {
    $bundlePathResolved = Resolve-Path -LiteralPath $bundleInput -ErrorAction Stop
}
catch {
    $candidateBundleDirs = @(
        (Join-Path (Get-Location).Path "downloaded"),
        (Join-Path $scriptRoot "downloaded"),
        (Join-Path $scriptRoot "backend_fastapi\downloaded"),
        (Join-Path $pythonHome "downloaded")
    )
    Write-Host ""
    Write-Host "Bundle path could not be resolved: $bundleInput" -ForegroundColor Yellow
    Show-BundleDiscoveryHints -CandidateDirs $candidateBundleDirs
    throw
}
$bundlePath = [string]$bundlePathResolved

if (-not $ModelId) {
    $ModelId = [System.IO.Path]::GetFileNameWithoutExtension($bundlePath)
}

$python = Resolve-PythonExe -Preferred $PythonExe -PythonHome $pythonHome

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
