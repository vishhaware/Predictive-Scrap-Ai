param(
    [ValidateRange(1, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1, 65535)][int]$FrontendPort = 5173,
    [switch]$RunAudit,
    [switch]$RunExtendedChecks,
    [switch]$InstallDeps,
    [switch]$NoPortCleanup,
    [switch]$OpenBrowser,
    [switch]$BootstrapVenv,
    [switch]$ResetIngestionCursor
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )
    Write-Host $Message -ForegroundColor $Color
}

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not available in PATH."
    }
}

function Get-ListeningPids {
    param([int[]]$Ports)
    $allPids = @()
    foreach ($port in ($Ports | Select-Object -Unique)) {
        try {
            $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique
            $allPids += $pids
        }
        catch {
            # Fallback for environments where Get-NetTCPConnection is unavailable.
            $raw = netstat -ano | Select-String -Pattern "LISTENING\s+(\d+)$"
            foreach ($line in $raw) {
                $text = $line.ToString()
                if ($text -match "[:\.]$port\s+") {
                    $candidate = ($text -split '\s+')[-1]
                    if ($candidate -match '^\d+$') {
                        $allPids += [int]$candidate
                    }
                }
            }
        }
    }
    return @($allPids | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

function Test-PortListening {
    param([int]$Port)
    $Port = [int](@($Port) | Select-Object -First 1)
    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        if ($listener) { return $true }
    }
    catch {}

    try {
        $match = netstat -ano | Select-String -Pattern "[:\.]$Port\s+.*LISTENING"
        return $null -ne $match
    }
    catch {}
    return $false
}

function Resolve-FrontendPort {
    param([int]$PreferredPort)
    $basePort = [int](@($PreferredPort) | Select-Object -First 1)

    if (-not (Test-PortListening -Port $basePort)) {
        return $basePort
    }

    $fallbacks = @(
        ($basePort + 1),
        5174,
        5175,
        3000,
        3001,
        4173
    ) | Select-Object -Unique
    foreach ($candidate in $fallbacks) {
        $candidatePort = [int](@($candidate) | Select-Object -First 1)
        if ($candidatePort -le 0 -or $candidatePort -gt 65535) { continue }
        if (-not (Test-PortListening -Port $candidatePort)) {
            return $candidatePort
        }
    }

    throw "Unable to find an available frontend port near $basePort."
}

function Resolve-BackendPort {
    param([int]$PreferredPort)
    $basePort = [int](@($PreferredPort) | Select-Object -First 1)

    if (-not (Test-PortListening -Port $basePort)) {
        return $basePort
    }

    $fallbacks = @(
        ($basePort + 1),
        ($basePort + 2),
        8001,
        8002,
        18010,
        18011
    ) | Select-Object -Unique
    foreach ($candidate in $fallbacks) {
        $candidatePort = [int](@($candidate) | Select-Object -First 1)
        if ($candidatePort -le 0 -or $candidatePort -gt 65535) { continue }
        if (-not (Test-PortListening -Port $candidatePort)) {
            return $candidatePort
        }
    }

    throw "Unable to find an available backend port near $basePort."
}

function Wait-HttpReady {
    param(
        [string]$Url,
        [int]$Attempts = 40,
        [int]$DelaySeconds = 2,
        [switch]$AllowAny2xx,
        [System.Diagnostics.Process]$AbortIfProcessExited
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        if ($AbortIfProcessExited) {
            try {
                $AbortIfProcessExited.Refresh()
                if ($AbortIfProcessExited.HasExited) {
                    return $false
                }
            }
            catch {}
        }
        try {
            if ($AllowAny2xx) {
                $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                    return $true
                }
            }
            else {
                $payload = $null
                try {
                    $payload = Invoke-RestMethod -Uri $Url -TimeoutSec 3 -ErrorAction Stop
                }
                catch {
                    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
                    try { $payload = $response.Content | ConvertFrom-Json } catch {}
                }
                if ($payload -and $payload.ok -eq $true) { return $true }
            }
        }
        catch {}
        if ($AbortIfProcessExited) {
            try {
                $AbortIfProcessExited.Refresh()
                if ($AbortIfProcessExited.HasExited) {
                    return $false
                }
            }
            catch {}
        }
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Invoke-JsonGet {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 8
    )
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec -ErrorAction Stop
    }
    catch {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
            if ($resp -and $resp.Content) {
                return ($resp.Content | ConvertFrom-Json)
            }
        }
        catch {}
        throw
    }
}

function Invoke-JsonGetWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$Attempts = 3,
        [int]$TimeoutSec = 8,
        [int]$DelaySeconds = 2
    )
    $lastError = $null
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            return Invoke-JsonGet -Url $Url -TimeoutSec $TimeoutSec
        }
        catch {
            $lastError = $_
            if ($i -lt $Attempts) {
                Start-Sleep -Seconds $DelaySeconds
            }
        }
    }
    if ($lastError) { throw $lastError }
    throw "Failed to fetch $Url"
}

function Show-LogTail {
    param(
        [string]$Path,
        [int]$Lines = 40,
        [string]$Label = "process log"
    )
    if (-not (Test-Path $Path)) { return }
    Write-Host ""
    Write-Host "$Label ($Path)" -ForegroundColor DarkGray
    try {
        Get-Content -Path $Path -Tail $Lines -ErrorAction Stop | ForEach-Object {
            Write-Host "  $_" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Step "[WARN] Could not read $Label at ${Path}: $($_.Exception.Message)" Yellow
    }
}

function Start-ShellCommandProcess {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDir,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$StdOutPath,
        [Parameter(Mandatory = $true)][string]$StdErrPath
    )
    New-Item -ItemType File -Force -Path $StdOutPath | Out-Null
    New-Item -ItemType File -Force -Path $StdErrPath | Out-Null
    $wrapped = @"
Set-Location -LiteralPath '$WorkingDir'
$Command
"@
    return Start-Process -FilePath "powershell" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $wrapped) -RedirectStandardOutput $StdOutPath -RedirectStandardError $StdErrPath -PassThru
}

function Get-ProcessExitCodeText {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process) { return "unknown" }
    try { $Process.Refresh() } catch {}
    $code = $null
    try { $code = $Process.ExitCode } catch {}
    if ($null -eq $code) { return "unknown" }
    $text = [string]$code
    if ([string]::IsNullOrWhiteSpace($text)) { return "unknown" }
    return $text
}

function Stop-ProcessSafe {
    param([int[]]$ProcessIds)
    foreach ($processId in ($ProcessIds | Select-Object -Unique)) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Step "Stopped PID $processId" Yellow
        }
        catch {
            Write-Step "[WARN] Could not stop PID $processId ($($_.Exception.Message))" Yellow
        }
    }
}

function Stop-NodeProcessesInPath {
    param([string]$PathHint)
    $killed = @()
    try {
        $escaped = [Regex]::Escape($PathHint)
        $procs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $cmd = [string]$p.CommandLine
            if ($cmd -match $escaped) {
                try {
                    Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction Stop
                    $killed += [int]$p.ProcessId
                }
                catch {}
            }
        }
    }
    catch {}
    return @($killed | Select-Object -Unique)
}

function Install-FrontendDepsRobust {
    param([string]$FrontendDir)
    $esbuildExe = Join-Path $FrontendDir "node_modules\@esbuild\win32-x64\esbuild.exe"
    $maxAttempts = 3
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Write-Step "[Deps] Frontend install attempt $attempt/$maxAttempts..."
        Push-Location $FrontendDir
        try {
            if (Test-Path (Join-Path $FrontendDir "package-lock.json")) {
                npm ci
            }
            else {
                npm install
            }
            return
        }
        catch {
            $msg = $_.Exception.Message
            Write-Step "[WARN] npm install attempt failed: $msg" Yellow
            if ($attempt -ge $maxAttempts) { throw }

            # Common Windows lock case: esbuild.exe in use.
            $killed = Stop-NodeProcessesInPath -PathHint $FrontendDir
            if ($killed.Count -gt 0) {
                Write-Step "Stopped node lock-holder PID(s): $($killed -join ', ')" Yellow
            }
            if (Test-Path $esbuildExe) {
                try { attrib -R $esbuildExe 2>$null | Out-Null } catch {}
                try { Remove-Item -Path $esbuildExe -Force -ErrorAction SilentlyContinue } catch {}
            }
            Start-Sleep -Seconds 2
        }
        finally {
            Pop-Location
        }
    }
}

function Assert-DataLayout {
    param(
        [string]$DataDir,
        [string[]]$MachineIds,
        [string]$MesWorkbookPath
    )

    if (-not (Test-Path $DataDir)) {
        throw "Missing data directory: $DataDir"
    }

    $missingCsv = @()
    foreach ($machineId in $MachineIds) {
        $csvPath = Join-Path $DataDir "$machineId.csv"
        if (-not (Test-Path $csvPath)) {
            $missingCsv += $machineId
        }
    }
    if ($missingCsv.Count -gt 0) {
        throw "Missing machine CSV file(s) in ${DataDir}: $($missingCsv -join ', ')"
    }

    if (-not (Test-Path $MesWorkbookPath)) {
        Write-Step "[WARN] MES workbook not found: $MesWorkbookPath" Yellow
    }
}

function Reset-IngestionCursor {
    param(
        [string]$PythonExe,
        [string]$BackendDbPath,
        [string]$RuntimeDir
    )

    if (-not (Test-Path $BackendDbPath)) {
        Write-Step "[WARN] Skipping cursor reset; DB file not found: $BackendDbPath" Yellow
        return
    }

    $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
    $backupPath = Join-Path $RuntimeDir "factory_brain_fastapi.$stamp.db.bak"
    Copy-Item -Path $BackendDbPath -Destination $backupPath -Force
    Write-Step "[Preflight] Backed up DB to $backupPath" DarkGray

    $resetScript = @'
import os
import sqlite3

db_path = os.environ.get("SFB_DB_PATH")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("UPDATE machine_stats SET last_loaded_timestamp = NULL")
updated = cur.rowcount
conn.commit()
conn.close()
print(updated)
'@
    $env:SFB_DB_PATH = $BackendDbPath
    try {
        $updatedRows = $resetScript | & $PythonExe - 2>$null
    }
    finally {
        Remove-Item Env:SFB_DB_PATH -ErrorAction SilentlyContinue
    }
    Write-Step "[Preflight] Reset ingestion cursor for $updatedRows machine stats row(s)." Yellow
}

function Show-IngestionLagHint {
    param(
        [string]$PythonExe,
        [string]$BackendDbPath,
        [string]$DataDir,
        [string[]]$MachineIds
    )

    if (-not (Test-Path $BackendDbPath)) { return }
    if (-not (Test-Path $DataDir)) { return }

    $hintScript = @'
import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

def parse_dt(text):
    if not text:
        return None
    text = str(text).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None

def csv_last_ts(path):
    if not path.exists():
        return None
    data = b""
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        while pos > 0 and data.count(b"\n") < 260:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = [ln for ln in data.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
    if not lines:
        return None
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        header = f.readline().strip()
    last_text = None
    for row in csv.DictReader([header] + lines[-220:]):
        ts = row.get("timestamp") or row.get("Timestamp")
        if ts:
            last_text = ts
    return last_text

db_path = Path(os.environ["SFB_DB_PATH"])
data_dir = Path(os.environ["SFB_DATA_DIR"])
machines = [m for m in os.environ.get("SFB_MACHINE_IDS", "").split(",") if m]

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cursor_map = {row[0]: row[1] for row in cur.execute("SELECT machine_id, last_loaded_timestamp FROM machine_stats")}
conn.close()

report = []
for machine in machines:
    csv_ts = csv_last_ts(data_dir / f"{machine}.csv")
    db_ts = cursor_map.get(machine)
    csv_dt = parse_dt(csv_ts)
    db_dt = parse_dt(db_ts)
    ahead = bool(csv_dt and db_dt and db_dt > csv_dt)
    report.append(
        {
            "machine_id": machine,
            "csv_last": csv_ts,
            "db_cursor": db_ts,
            "cursor_ahead_of_csv": ahead,
        }
    )
print(json.dumps(report))
'@

    $env:SFB_DB_PATH = $BackendDbPath
    $env:SFB_DATA_DIR = $DataDir
    $env:SFB_MACHINE_IDS = ($MachineIds -join ",")
    try {
        $raw = $hintScript | & $PythonExe - 2>$null
    }
    finally {
        Remove-Item Env:SFB_DB_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:SFB_DATA_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:SFB_MACHINE_IDS -ErrorAction SilentlyContinue
    }

    if (-not $raw) { return }
    $report = $raw | ConvertFrom-Json
    $aheadRows = @($report | Where-Object { $_.cursor_ahead_of_csv -eq $true })
    if ($aheadRows.Count -eq 0) { return }

    Write-Step "[INFO] Ingestion cursors are ahead of CSV data for $($aheadRows.Count) machine(s); next ingestion can show 0 new cycles." Yellow
    foreach ($row in $aheadRows) {
        Write-Host "  $($row.machine_id): csv_last=$($row.csv_last) | db_cursor=$($row.db_cursor)" -ForegroundColor DarkGray
    }
    Write-Host "  Tip: run .\start-all.ps1 -ResetIngestionCursor to replay CSV rows from current files." -ForegroundColor DarkGray
}

function Show-BackendDataSnapshot {
    param(
        [string]$BackendUrl
    )
    try {
        $machines = Invoke-JsonGet -Url "$BackendUrl/api/machines" -TimeoutSec 8
        if (-not $machines) { return }
        $rows = @($machines)
        if ($rows.Count -eq 0) { return }
        $totalCycles = ($rows | Measure-Object -Property cycles -Sum).Sum
        Write-Host ("Machines loaded: {0}, total cycles in stats: {1}" -f $rows.Count, $totalCycles) -ForegroundColor DarkGray
        if ([int]$totalCycles -le 0) {
            Write-Step "[WARN] All machine cycle counters are zero. UI can appear empty until ingestion replays rows." Yellow
            Write-Host "  Tip: run .\start-all.ps1 -ResetIngestionCursor" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Step "[WARN] Could not fetch machine snapshot from backend." Yellow
    }
}

$repoRoot = Split-Path -Parent $PSCommandPath
$backendDir = Join-Path $repoRoot "backend_fastapi"
$frontendDir = Join-Path $repoRoot "frontend"
$pythonExe = Join-Path $backendDir "venv\Scripts\python.exe"
$backendHost = "127.0.0.1"
$frontendHost = "127.0.0.1"
$runtimeDir = Join-Path $repoRoot ".runtime"
$stackStatePath = Join-Path $runtimeDir "stack-state.json"
$backendDbPath = Join-Path $backendDir "factory_brain_fastapi.db"
$dataDir = Join-Path $frontendDir "Data"
$mesWorkbookPath = Join-Path $dataDir "MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx"
$machineIds = @("M231-11", "M356-57", "M471-23", "M607-30", "M612-33")

$resolvedBackendPort = $BackendPort
$backendUrl = "http://$backendHost`:$resolvedBackendPort"
$backendWsUrl = "ws://$backendHost`:$resolvedBackendPort"
$resolvedFrontendPort = $FrontendPort
$dashboardUrl = "http://$frontendHost`:$resolvedFrontendPort"
$backendStdOutLog = Join-Path $runtimeDir "backend.stdout.log"
$backendStdErrLog = Join-Path $runtimeDir "backend.stderr.log"
$frontendStdOutLog = Join-Path $runtimeDir "frontend.stdout.log"
$frontendStdErrLog = Join-Path $runtimeDir "frontend.stderr.log"

$backendProc = $null
$frontendProc = $null

try {
    Write-Step "`n[Smart Factory Brain] Starting local stack...`n"

    if (-not (Test-Path $backendDir)) { throw "Missing folder: $backendDir" }
    if (-not (Test-Path $frontendDir)) { throw "Missing folder: $frontendDir" }
    if (-not (Test-Path (Join-Path $backendDir "main.py"))) { throw "Missing backend entrypoint: $backendDir\main.py" }
    if (-not (Test-Path (Join-Path $backendDir "requirements.txt"))) { throw "Missing backend requirements: $backendDir\requirements.txt" }
    if (-not (Test-Path (Join-Path $frontendDir "package.json"))) { throw "Missing frontend package.json: $frontendDir\package.json" }
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Assert-DataLayout -DataDir $dataDir -MachineIds $machineIds -MesWorkbookPath $mesWorkbookPath

    Assert-Command -Name npm
    Assert-Command -Name powershell

    if (-not (Test-Path $pythonExe)) {
        if ($BootstrapVenv) {
            Write-Step "[Preflight] Creating backend venv..."
            Assert-Command -Name python
            Push-Location $backendDir
            try {
                python -m venv venv
            }
            finally {
                Pop-Location
            }
        }
        if (-not (Test-Path $pythonExe)) {
            throw "Missing Python venv at $pythonExe. Use -BootstrapVenv or create it manually."
        }
    }

    Write-Step "[Preflight] Validating runtime versions..."
    $pyVersion = & $pythonExe --version 2>&1
    $npmVersion = npm --version
    Write-Host "Python : $pyVersion" -ForegroundColor DarkGray
    Write-Host "npm    : $npmVersion" -ForegroundColor DarkGray
    Write-Host "DATA_DIR: $dataDir" -ForegroundColor DarkGray

    if ($ResetIngestionCursor) {
        Reset-IngestionCursor -PythonExe $pythonExe -BackendDbPath $backendDbPath -RuntimeDir $runtimeDir
    }

    if ($InstallDeps) {
        Write-Step "[Preflight] Installing/updating dependencies..."
        Push-Location $backendDir
        try {
            & $pythonExe -m pip install -U pip setuptools wheel
            & $pythonExe -m pip install -r requirements.txt
        }
        finally {
            Pop-Location
        }

        Install-FrontendDepsRobust -FrontendDir $frontendDir
    }
    else {
        if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
            Write-Step "[WARN] frontend/node_modules missing. Run with -InstallDeps or run npm install in frontend." Yellow
        }
    }

    if (-not $NoPortCleanup) {
        $portsToClean = @($BackendPort, $FrontendPort, 8000, 8001, 8002, 5174, 3000, 3001, 4173) | Select-Object -Unique
        Write-Step "[1/5] Releasing ports: $($portsToClean -join ', ')..."
        $stalePids = @(Get-ListeningPids -Ports $portsToClean)
        if ($stalePids.Count -gt 0) {
            Write-Step "Stopping stale listener process(es): $($stalePids -join ', ')" Yellow
            Stop-ProcessSafe -ProcessIds $stalePids
            Start-Sleep -Seconds 1
        }
        else {
            Write-Step "No stale listeners found." Green
        }

    }
    else {
        Write-Step "[1/5] Port cleanup skipped (-NoPortCleanup)." Yellow
    }

    $resolvedBackendPort = Resolve-BackendPort -PreferredPort $BackendPort
    if ($resolvedBackendPort -ne $BackendPort) {
        Write-Step "[INFO] Backend port $BackendPort is busy. Using $resolvedBackendPort instead." Yellow
    }
    $backendUrl = "http://$backendHost`:$resolvedBackendPort"
    $backendWsUrl = "ws://$backendHost`:$resolvedBackendPort"

    Write-Step "`n[2/5] Starting FastAPI backend..."
$backendCommand = @"
`$env:PYTHONUNBUFFERED='1'
`$env:DATA_DIR='$dataDir'
`$env:MES_WORKBOOK_PATH='$mesWorkbookPath'
& '$pythonExe' -m uvicorn main:app --host $backendHost --port $resolvedBackendPort
"@
    $backendProc = Start-ShellCommandProcess -WorkingDir $backendDir -Command $backendCommand -StdOutPath $backendStdOutLog -StdErrPath $backendStdErrLog
    Start-Sleep -Milliseconds 500
    if ($backendProc.HasExited) {
        $backendExit = Get-ProcessExitCodeText -Process $backendProc
        Show-LogTail -Path $backendStdErrLog -Label "Backend stderr"
        Show-LogTail -Path $backendStdOutLog -Label "Backend stdout"
        throw "Backend process exited immediately with code $backendExit."
    }

    Write-Step "[3/5] Waiting for backend health ($backendUrl/api/health)..."
    $backendReady = Wait-HttpReady -Url "$backendUrl/api/health" -Attempts 50 -DelaySeconds 2 -AbortIfProcessExited $backendProc
    if (-not $backendReady) {
        $backendProc.Refresh()
        if ($backendProc.HasExited) {
            $backendExit = Get-ProcessExitCodeText -Process $backendProc
            Show-LogTail -Path $backendStdErrLog -Label "Backend stderr"
            Show-LogTail -Path $backendStdOutLog -Label "Backend stdout"
            throw "Backend process exited during startup with code $backendExit."
        }
        Show-LogTail -Path $backendStdErrLog -Label "Backend stderr"
        Show-LogTail -Path $backendStdOutLog -Label "Backend stdout"
        throw "Backend health check timed out. Check backend terminal logs."
    }
    Write-Step "Backend is healthy." Green
    try {
        $healthPayload = Invoke-JsonGet -Url "$backendUrl/api/health" -TimeoutSec 5
        if ($healthPayload.details -and $healthPayload.details.data_connectivity) {
            $dc = $healthPayload.details.data_connectivity
            Write-Host ("Data: csv_found={0}/{1}, dir={2}" -f $dc.csv_found, $dc.expected, $dc.data_dir) -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Step "[WARN] Could not fetch backend health details for summary." Yellow
    }
    Show-IngestionLagHint -PythonExe $pythonExe -BackendDbPath $backendDbPath -DataDir $dataDir -MachineIds $machineIds
    Show-BackendDataSnapshot -BackendUrl $backendUrl

    Write-Step "[3.2/5] Backend endpoint smoke checks (non-blocking)..."
    $coreChecksOk = $true
    try {
        $null = Invoke-JsonGetWithRetry -Url "$backendUrl/api/machines" -Attempts 2 -TimeoutSec 6 -DelaySeconds 2
    }
    catch {
        $coreChecksOk = $false
        Write-Step "[WARN] /api/machines is not ready yet. Continuing startup." Yellow
        Write-Host "  Last error: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
    try {
        $null = Invoke-JsonGetWithRetry -Url "$backendUrl/api/machines/M231-11/cycles?limit=1" -Attempts 2 -TimeoutSec 6 -DelaySeconds 2
    }
    catch {
        $coreChecksOk = $false
        Write-Step "[WARN] /api/machines/M231-11/cycles is not ready yet. Continuing startup." Yellow
        Write-Host "  Last error: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
    if ($coreChecksOk) {
        Write-Step "Core backend smoke checks passed." Green
    }
    else {
        Write-Step "[WARN] Backend endpoint smoke checks are warming up; startup will continue." Yellow
    }

    if ($RunAudit) {
        Write-Step "[3.5/5] Running backend integration audit..."
        & $pythonExe "$backendDir\integration_audit.py" --strict --output "$backendDir\result.json"
        if ($LASTEXITCODE -ne 0) {
            throw "Integration audit failed. See $backendDir\result.json"
        }
        Write-Step "Integration audit passed." Green
    }

    Write-Step "`n[4/5] Starting frontend (Vite) with backend bindings..."
    $resolvedFrontendPort = Resolve-FrontendPort -PreferredPort $FrontendPort
    $dashboardUrl = "http://$frontendHost`:$resolvedFrontendPort"
    if ($resolvedFrontendPort -ne $FrontendPort) {
        Write-Step "[INFO] Frontend port $FrontendPort is busy. Using $resolvedFrontendPort instead." Yellow
    }
    $frontendCommand = @"
`$env:VITE_BACKEND_URL='$backendUrl'
`$env:VITE_BACKEND_WS_URL='$backendWsUrl'
`$env:VITE_ENABLE_WS_PROXY='true'
npm run dev -- --host $frontendHost --port $resolvedFrontendPort --strictPort
"@
    $frontendProc = Start-ShellCommandProcess -WorkingDir $frontendDir -Command $frontendCommand -StdOutPath $frontendStdOutLog -StdErrPath $frontendStdErrLog
    Start-Sleep -Milliseconds 500
    if ($frontendProc.HasExited) {
        $frontendExit = Get-ProcessExitCodeText -Process $frontendProc
        Show-LogTail -Path $frontendStdErrLog -Label "Frontend stderr"
        Show-LogTail -Path $frontendStdOutLog -Label "Frontend stdout"
        throw "Frontend process exited immediately with code $frontendExit."
    }

    Write-Step "[5/5] Waiting for frontend readiness ($dashboardUrl)..."
    $frontendReady = Wait-HttpReady -Url $dashboardUrl -Attempts 40 -DelaySeconds 1 -AllowAny2xx -AbortIfProcessExited $frontendProc
    $frontendProc.Refresh()
    if ($frontendProc.HasExited) {
        $frontendExit = Get-ProcessExitCodeText -Process $frontendProc
        Show-LogTail -Path $frontendStdErrLog -Label "Frontend stderr"
        Show-LogTail -Path $frontendStdOutLog -Label "Frontend stdout"
        throw "Frontend process exited before readiness probe completed (code $frontendExit). Check frontend terminal output."
    }
    if (-not $frontendReady) {
        Write-Step "[WARN] Frontend readiness probe timed out. It may still be compiling; check frontend terminal." Yellow
    }
    else {
        Write-Step "Frontend is reachable." Green
    }

    try {
        $null = Invoke-JsonGetWithRetry -Url "$dashboardUrl/api/health" -Attempts 3 -TimeoutSec 6 -DelaySeconds 1
        Write-Step "Frontend proxy check passed (/api/health)." Green
    }
    catch {
        Write-Step "[WARN] Frontend proxy check failed at $dashboardUrl/api/health after retries. Verify Vite proxy binding." Yellow
    }

    if ($OpenBrowser) {
        Write-Step "Opening browser: $dashboardUrl"
        Start-Process $dashboardUrl | Out-Null
    }

    if ($RunExtendedChecks) {
        Write-Step "[5.1/5] Extended chart checks (non-blocking)..."
        try {
            $null = Invoke-JsonGetWithRetry -Url "$backendUrl/api/machines/M231-11/chart-data?horizon_minutes=60" -Attempts 1 -TimeoutSec 5 -DelaySeconds 1
            $null = Invoke-JsonGetWithRetry -Url "$backendUrl/api/fleet/chart-data?horizon_minutes=60" -Attempts 1 -TimeoutSec 5 -DelaySeconds 1
            Write-Step "Extended chart smoke checks passed." Green
        }
        catch {
            Write-Step "[WARN] Extended chart endpoints are still warming up; dashboard should still open." Yellow
            Write-Host "  Last error: $($_.Exception.Message)" -ForegroundColor DarkGray
        }
    }
    else {
        Write-Step "[5.1/5] Extended chart checks skipped. Use -RunExtendedChecks to enable." DarkGray
    }

    Write-Step "`nStartup complete." Green
    Write-Host "Dashboard : $dashboardUrl" -ForegroundColor White
    Write-Host "API Docs  : $backendUrl/docs" -ForegroundColor White
    Write-Host "Health    : $backendUrl/api/health" -ForegroundColor White
    Write-Host "Backend logs : $backendStdOutLog | $backendStdErrLog" -ForegroundColor DarkGray
    Write-Host "Frontend logs: $frontendStdOutLog | $frontendStdErrLog" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Quick checks:" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS $backendUrl/api/health" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS $backendUrl/api/ai/metrics" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS $backendUrl/api/admin/models" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS `"$backendUrl/api/machines/M231-11/chart-data?horizon_minutes=60`"" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS `"$backendUrl/api/fleet/chart-data?horizon_minutes=60`"" -ForegroundColor DarkGray
    Write-Host "  curl.exe -sS $dashboardUrl" -ForegroundColor DarkGray

    $state = @{
        started_at = (Get-Date).ToString("o")
        backend = @{
            pid = $backendProc.Id
            url = $backendUrl
            docs = "$backendUrl/docs"
            health = "$backendUrl/api/health"
            data_dir = $dataDir
            mes_workbook = $mesWorkbookPath
            requested_port = $BackendPort
            actual_port = $resolvedBackendPort
        }
        frontend = @{
            pid = $frontendProc.Id
            url = $dashboardUrl
            requested_port = $FrontendPort
            actual_port = $resolvedFrontendPort
        }
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -Path $stackStatePath -Encoding UTF8
    Write-Host ""
    Write-Host "# Runtime state file (info only): $stackStatePath" -ForegroundColor DarkGray
    Write-Host "# To stop quickly run this command:" -ForegroundColor DarkGray
    Write-Host "Stop-Process -Id $($backendProc.Id),$($frontendProc.Id) -Force" -ForegroundColor DarkGray
}
catch {
    Write-Step "`n[ERROR] $($_.Exception.Message)" Red
    if ($_.ScriptStackTrace) {
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    }
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Step "Stopping backend PID $($backendProc.Id) due to startup failure." Yellow
        Stop-ProcessSafe -ProcessIds @($backendProc.Id)
    }
    if ($frontendProc -and -not $frontendProc.HasExited) {
        Write-Step "Stopping frontend PID $($frontendProc.Id) due to startup failure." Yellow
        Stop-ProcessSafe -ProcessIds @($frontendProc.Id)
    }
    if (Test-Path $stackStatePath) {
        Remove-Item -Path $stackStatePath -Force -ErrorAction SilentlyContinue
    }
    exit 1
}
