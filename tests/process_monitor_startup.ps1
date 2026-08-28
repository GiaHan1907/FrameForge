[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProcmonPath,
    [string]$ExecutablePath = "$env:LOCALAPPDATA\Programs\FrameForge\VideoScreenshotFilter.exe",
    [string]$OutputDirectory = "$env:USERPROFILE\Desktop\FrameForge-Procmon",
    [int]$CaptureSeconds = 20,
    [switch]$KeepAppRunning
)

$ErrorActionPreference = 'Stop'

function Fail([string]$message) {
    Write-Error "PROCESS MONITOR FAIL: $message"
    exit 1
}

if (-not (Test-Path $ProcmonPath)) { Fail "Procmon.exe not found: $ProcmonPath" }
if (-not (Test-Path $ExecutablePath)) { Fail "FrameForge EXE not found: $ExecutablePath" }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$pmlPath = Join-Path $OutputDirectory "frameforge-startup-$stamp.pml"
$csvPath = Join-Path $OutputDirectory "frameforge-startup-$stamp.csv"
$treePath = Join-Path $OutputDirectory "frameforge-process-tree-$stamp.csv"
$env:FRAMEFORGE_AUTO_UPDATE = '0'
$env:FRAMEFORGE_NO_BROWSER = '1'

function Get-ProcessSnapshot {
    Get-CimInstance Win32_Process | Select-Object Name, ProcessId, ParentProcessId, CommandLine
}

$before = @(Get-ProcessSnapshot)
$procmon = $null
$app = $null
try {
    # NoFilter deliberately captures every startup event. The exported CSV can be filtered
    # in Procmon by Process Create, Process Exit, Process Name and Parent PID.
    $procmonArgs = @('/AcceptEula', '/Quiet', '/Minimized', '/NoFilter', "/BackingFile", $pmlPath)
    $procmon = Start-Process -FilePath $ProcmonPath -ArgumentList $procmonArgs -PassThru
    Start-Sleep -Seconds 2

    $start = Get-Date
    $app = Start-Process -FilePath $ExecutablePath -WorkingDirectory (Split-Path $ExecutablePath) -PassThru -WindowStyle Hidden
    $observed = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $CaptureSeconds; $i++) {
        Start-Sleep -Seconds 1
        foreach ($item in @(Get-ProcessSnapshot)) {
            if ($item.ProcessId -eq $app.Id -or $item.ParentProcessId -eq $app.Id) {
                $observed.Add([pscustomobject]@{
                    Timestamp = (Get-Date).ToString('o')
                    Name = $item.Name
                    ProcessId = $item.ProcessId
                    ParentProcessId = $item.ParentProcessId
                    CommandLine = $item.CommandLine
                })
            }
        }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { Write-Host "Streamlit ready after $($i + 1)s"; break }
        } catch { }
    }
    $after = @(Get-ProcessSnapshot)
    $children = @($after | Where-Object { $_.ParentProcessId -eq $app.Id })
    $observed | Sort-Object Timestamp, ProcessId -Unique | Export-Csv -Path $treePath -NoTypeInformation -Encoding UTF8
    Write-Host "Process tree snapshot: $treePath"
    Write-Host "Direct child processes observed: $($children.Count)"
    $children | Format-Table Name, ProcessId, ParentProcessId, CommandLine -AutoSize
} finally {
    if ($app -and -not $KeepAppRunning -and -not $app.HasExited) {
        Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    if ($procmon -and -not $procmon.HasExited) {
        Start-Process -FilePath $ProcmonPath -ArgumentList @('/Terminate') -Wait -WindowStyle Hidden
    }
}

if (Test-Path $pmlPath) {
    # Procmon export is best-effort; PML is the authoritative capture if this fails.
    $export = Start-Process -FilePath $ProcmonPath -ArgumentList @('/OpenLog', $pmlPath, '/SaveAs', $csvPath) -PassThru -Wait -WindowStyle Hidden
    if ($export.ExitCode -ne 0) { Write-Warning "Procmon CSV export returned $($export.ExitCode); keep the PML file." }
}

if (-not (Test-Path $pmlPath)) { Fail "Procmon did not create a PML capture." }
Write-Host "PML capture: $pmlPath" -ForegroundColor Green
if (Test-Path $csvPath) { Write-Host "CSV export: $csvPath" -ForegroundColor Green }
Write-Host "Open the PML/CSV in Procmon and filter Operation = Process Create to inspect child processes." -ForegroundColor Cyan
exit 0
