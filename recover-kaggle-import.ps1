param(
    [string]$DownloadedDir = ".\backend_fastapi\downloaded",
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

$scriptRoot = Split-Path -Parent $PSCommandPath
$backendScript = Join-Path $scriptRoot "backend_fastapi\recover-kaggle-import.ps1"
if (-not (Test-Path $backendScript)) {
    throw "Missing script: $backendScript"
}

if (-not $PSBoundParameters.ContainsKey("DownloadedDir")) {
    $PSBoundParameters["DownloadedDir"] = $DownloadedDir
}

& $backendScript @PSBoundParameters
