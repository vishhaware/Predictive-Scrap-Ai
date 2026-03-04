param(
    [string]$DownloadedDir = ".\downloaded",
    [ValidateSet("scrap_classifier", "sensor_forecaster")][string]$Task = "scrap_classifier",
    [string]$ModelId,
    [string]$Family,
    [string]$MachineId,
    [string]$PartNumber,
    [string]$SegmentId,
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$Promote,
    [switch]$SkipVerify
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-LocalPath {
    param([string]$PathValue)

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return Join-Path (Get-Location).Path $PathValue
}

function Show-DirectoryTree {
    param([string]$PathValue)

    if (-not (Test-Path $PathValue)) {
        Write-Host "Directory does not exist: $PathValue" -ForegroundColor DarkGray
        return
    }

    $entries = @(Get-ChildItem -Path $PathValue -Recurse -Force -ErrorAction SilentlyContinue)
    if ($entries.Count -eq 0) {
        Write-Host "Directory is empty: $PathValue" -ForegroundColor DarkGray
        return
    }

    $entries |
        Sort-Object FullName |
        Select-Object -First 25 FullName, Length, LastWriteTime |
        Format-Table -AutoSize
}

function Get-BrowserDownloadDirs {
    $prefs = @(
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Preferences",
        "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Preferences"
    )
    $dirs = @()
    foreach ($pref in $prefs) {
        if (-not (Test-Path $pref)) { continue }
        try {
            $json = Get-Content -Raw $pref | ConvertFrom-Json
            $d = [string]$json.download.default_directory
            if ($d) { $dirs += $d }
        }
        catch {
            continue
        }
    }
    return $dirs | Where-Object { $_ } | Select-Object -Unique
}

function Show-RecentDownloads {
    $candidateDirs = @(
        (Join-Path $env:USERPROFILE "Downloads")
    ) + (Get-BrowserDownloadDirs)

    $candidateDirs = $candidateDirs | Where-Object { Test-Path $_ } | Select-Object -Unique
    if ($candidateDirs.Count -eq 0) { return }

    $recent = @()
    $partial = @()
    foreach ($dir in $candidateDirs) {
        $recent += Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @(".zip", ".pkl") }
        $partial += Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @(".crdownload", ".part") }
    }

    $recent = @($recent | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name, FullName, Length, LastWriteTime)
    $partial = @($partial | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name, FullName, Length, LastWriteTime)

    if ($recent.Count -eq 0) {
        Write-Host "No .zip/.pkl files found in checked download folders:" -ForegroundColor DarkGray
        $candidateDirs | ForEach-Object { Write-Host " - $_" -ForegroundColor DarkGray }
    }
    else {
        Write-Host "Recent .zip/.pkl files in checked download folders:" -ForegroundColor DarkGray
        $recent | Format-Table -AutoSize
    }

    if ($partial.Count -gt 0) {
        Write-Host "Detected incomplete downloads (finish/resume these first):" -ForegroundColor Yellow
        $partial | Format-Table -AutoSize
    }
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$importScript = Join-Path $scriptRoot "import-kaggle-model.ps1"
if (-not (Test-Path $importScript)) {
    throw "Missing script: $importScript"
}

$downloadedFullPath = Resolve-LocalPath -PathValue $DownloadedDir
$downloadedFullPathCanonical = [System.IO.Path]::GetFullPath($downloadedFullPath)
if (-not (Test-Path $downloadedFullPath)) {
    New-Item -ItemType Directory -Path $downloadedFullPath -Force | Out-Null
}

$nestedDownloadedHint = Join-Path (Get-Location).Path "backend_fastapi\downloaded"
if (Test-Path $nestedDownloadedHint) {
    $nestedDownloadedHintCanonical = [System.IO.Path]::GetFullPath($nestedDownloadedHint)
    $nestedHasContent = @(Get-ChildItem -Path $nestedDownloadedHint -Recurse -File -ErrorAction SilentlyContinue).Count -gt 0
    if (($nestedDownloadedHintCanonical -ne $downloadedFullPathCanonical) -and $nestedHasContent) {
        Write-Warning "Detected nested folder: $nestedDownloadedHintCanonical"
        Write-Warning "From backend_fastapi, use .\downloaded (not .\backend_fastapi\downloaded)."
    }
}

$bundle = Get-ChildItem -Path $downloadedFullPath -Recurse -File -Filter *.pkl -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $bundle) {
    Write-Host ""
    Write-Host "No bundle .pkl found under: $downloadedFullPath" -ForegroundColor Yellow
    Write-Host "Place/extract Kaggle notebook output in this folder, then rerun." -ForegroundColor Yellow
    Write-Host ""
    Show-DirectoryTree -PathValue $downloadedFullPath
    Show-RecentDownloads
    throw "No .pkl artifact available under '$downloadedFullPath'."
}

$importArgs = @(
    "-BundleJoblib", $bundle.FullName,
    "-Task", $Task
)
if ($ModelId) { $importArgs += @("-ModelId", $ModelId) }
if ($Family) { $importArgs += @("-Family", $Family) }
if ($MachineId) { $importArgs += @("-MachineId", $MachineId) }
if ($PartNumber) { $importArgs += @("-PartNumber", $PartNumber) }
if ($SegmentId) { $importArgs += @("-SegmentId", $SegmentId) }
if ($Promote) { $importArgs += "-Promote" }

Write-Host "Using bundle: $($bundle.FullName)" -ForegroundColor Cyan
& $importScript @importArgs
if ($LASTEXITCODE -ne 0) {
    throw "Import wrapper failed with exit code $LASTEXITCODE."
}

if ($SkipVerify) {
    exit 0
}

try {
    $models = Invoke-RestMethod -Uri "$BaseUrl/api/admin/models" -Method Get -TimeoutSec 15
    $health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -Method Get -TimeoutSec 15

    $resolvedModelId = if ($ModelId) { $ModelId } else { [System.IO.Path]::GetFileNameWithoutExtension($bundle.Name) }
    $modelExists = $false
    if ($models.models -and $models.models.PSObject.Properties.Name -contains $resolvedModelId) {
        $modelExists = $true
    }

    Write-Host ""
    Write-Host "Verification:" -ForegroundColor Green
    Write-Host " - /api/health ok: $($health.ok)" -ForegroundColor DarkGray
    Write-Host " - model '$resolvedModelId' registered: $modelExists" -ForegroundColor DarkGray
}
catch {
    Write-Warning "Import completed, but verification endpoints are unavailable at $BaseUrl. Start backend and run:"
    Write-Warning "  curl.exe -sS $BaseUrl/api/admin/models"
    Write-Warning "  curl.exe -sS $BaseUrl/api/health"
}
