param(
    [string]$DownloadsDir = "$env:USERPROFILE\Downloads",
    [string]$TargetDir = ".\downloaded",
    [string]$NamePattern = "registry|bundle|kaggle|sfb",
    [string]$ArtifactPath,
    [switch]$PreferPkl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
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
    return $dirs
}

function Get-PartialDownloads {
    param(
        [string[]]$Dirs
    )
    $partial = @()
    foreach ($dir in $Dirs) {
        if (-not (Test-Path $dir)) { continue }
        $partial += Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @(".crdownload", ".part") }
    }
    return @($partial | Sort-Object LastWriteTime -Descending)
}

function Stage-ArtifactFile {
    param(
        [string]$Path,
        [string]$Destination
    )
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    $file = Get-Item -LiteralPath $resolved

    if ($file.Extension -ieq ".zip") {
        Expand-Archive -Path $file.FullName -DestinationPath $Destination -Force
        Write-Host "Extracted zip: $($file.FullName) -> $Destination" -ForegroundColor Green
        return
    }
    if ($file.Extension -ieq ".pkl") {
        Copy-Item -Path $file.FullName -Destination $Destination -Force
        Write-Host "Copied .pkl: $($file.FullName) -> $Destination" -ForegroundColor Green
        return
    }
    throw "Unsupported artifact extension '$($file.Extension)'. Use .zip or .pkl."
}

if ($ArtifactPath) {
    Stage-ArtifactFile -Path $ArtifactPath -Destination $TargetDir
}
else {
    $candidateDirs = @(
        $DownloadsDir,
        "$env:USERPROFILE\Downloads"
    ) + (Get-BrowserDownloadDirs)

    $candidateDirs = $candidateDirs | Where-Object { $_ } | Select-Object -Unique
    $existingCandidateDirs = @($candidateDirs | Where-Object { Test-Path $_ })

    if ($existingCandidateDirs.Count -eq 0) {
        throw "No accessible download directories found. Checked: $($candidateDirs -join ', ')"
    }

    $allZipCandidates = @()
    $zipCandidates = @()
    $pklCandidates = @()
    foreach ($dir in $existingCandidateDirs) {
        $allZipCandidates += Get-ChildItem -Path $dir -File -Filter *.zip -ErrorAction SilentlyContinue
        $pklCandidates += Get-ChildItem -Path $dir -File -Filter *.pkl -ErrorAction SilentlyContinue
    }
    $allZipCandidates = @($allZipCandidates | Sort-Object LastWriteTime -Descending)
    $zipCandidates = @($allZipCandidates | Where-Object { $_.Name -match $NamePattern })
    $pklCandidates = @($pklCandidates | Sort-Object LastWriteTime -Descending)

    if ($PreferPkl -and $pklCandidates.Count -gt 0) {
        Stage-ArtifactFile -Path $pklCandidates[0].FullName -Destination $TargetDir
    }
    elseif ($zipCandidates.Count -gt 0) {
        Stage-ArtifactFile -Path $zipCandidates[0].FullName -Destination $TargetDir
    }
    elseif ($allZipCandidates.Count -gt 0) {
        Write-Warning "No zip matched NamePattern '$NamePattern'. Falling back to latest zip in Downloads."
        Stage-ArtifactFile -Path $allZipCandidates[0].FullName -Destination $TargetDir
    }
    elseif ($pklCandidates.Count -gt 0) {
        Stage-ArtifactFile -Path $pklCandidates[0].FullName -Destination $TargetDir
    }
    else {
        Write-Host "No matching Kaggle artifact found." -ForegroundColor Yellow
        Write-Host "Checked directories:" -ForegroundColor DarkGray
        $existingCandidateDirs | ForEach-Object { Write-Host " - $_" -ForegroundColor DarkGray }

        $partialDownloads = @(Get-PartialDownloads -Dirs $existingCandidateDirs)
        if ($partialDownloads.Count -gt 0) {
            Write-Host "Detected incomplete downloads (finish/resume these first):" -ForegroundColor Yellow
            $partialDownloads | Select-Object -First 10 Name, FullName, Length, LastWriteTime | Format-Table -AutoSize
        }

        Write-Host "Recent files across checked folders (top 20):" -ForegroundColor DarkGray
        $recent = @()
        foreach ($dir in $existingCandidateDirs) {
            $recent += Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue
        }
        $recent | Sort-Object LastWriteTime -Descending |
            Select-Object -First 20 Name, FullName, Extension, Length, LastWriteTime |
            Format-Table -AutoSize
        throw "Missing artifact: download sfb_registry_bundle_export.zip or <MODEL_ID>.pkl from Kaggle first."
    }
}

$stagedPkls = @(Get-ChildItem -Path $TargetDir -Recurse -File -Filter *.pkl -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending)

if ($stagedPkls.Count -eq 0) {
    Write-Host "Target directory contents:" -ForegroundColor Yellow
    Get-ChildItem -Path $TargetDir -Recurse -Force -ErrorAction SilentlyContinue |
        Select-Object FullName, Length, LastWriteTime |
        Format-Table -AutoSize
    throw "Artifact staging completed, but no .pkl found under $TargetDir."
}

Write-Host ""
Write-Host "Ready for import. First discovered bundle:" -ForegroundColor Cyan
Write-Host $stagedPkls[0].FullName -ForegroundColor DarkGray
