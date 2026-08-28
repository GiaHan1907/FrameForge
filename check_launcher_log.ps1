[CmdletBinding()]
param(
    [switch]$Watch,
    [int]$IntervalSeconds = 5,
    [int]$Tail = 80,
    [switch]$OpenFolder
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'VideoScreenshotFilter'
$logPath = Join-Path $logDir 'launcher_error.log'
$statePath = Join-Path $logDir 'launcher_log_monitor.json'

if ($OpenFolder) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Start-Process explorer.exe -ArgumentList "`"$logDir`""
}

function Get-LogState {
    if (Test-Path $statePath) {
        try { return Get-Content $statePath -Raw | ConvertFrom-Json } catch { }
    }
    return [pscustomobject]@{ LastWriteUtc = ''; LastSize = 0 }
}

function Save-LogState([System.IO.FileInfo]$file) {
    [pscustomobject]@{
        LastWriteUtc = $file.LastWriteTimeUtc.ToString('o')
        LastSize = $file.Length
    } | ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8
}

function Test-LauncherLog {
    if (-not (Test-Path $logPath)) {
        Write-Host "OK: chưa có launcher_error.log — chưa ghi nhận lỗi khởi động." -ForegroundColor Green
        return $false
    }

    $file = Get-Item $logPath
    $state = Get-LogState
    $isNew = ($state.LastWriteUtc -ne $file.LastWriteTimeUtc.ToString('o')) -or ([int64]$state.LastSize -ne $file.Length)
    $content = Get-Content $logPath -Tail $Tail -ErrorAction SilentlyContinue
    $errorPattern = 'launcher error|Traceback|Exception|Error|FileNotFoundError|ModuleNotFoundError|PermissionError|ConnectionError'
    $matches = @($content | Where-Object { $_ -match $errorPattern })

    if ($isNew -and $matches.Count -gt 0) {
        Write-Warning "Phát hiện lỗi launcher mới trong $logPath"
        $matches | Select-Object -Last 20 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        Save-LogState $file
        return $true
    }

    if ($matches.Count -gt 0) {
        Write-Host "WARN: log vẫn chứa lỗi gần nhất; chưa phát hiện thay đổi mới." -ForegroundColor Yellow
    } else {
        Write-Host "OK: launcher_error.log không có mẫu lỗi trong $Tail dòng cuối." -ForegroundColor Green
    }
    Save-LogState $file
    return $false
}

if ($Watch) {
    Write-Host "Đang theo dõi $logPath mỗi $IntervalSeconds giây. Nhấn Ctrl+C để dừng." -ForegroundColor Cyan
    while ($true) {
        [void](Test-LauncherLog)
        Start-Sleep -Seconds ([Math]::Max(1, $IntervalSeconds))
    }
} else {
    $hasError = Test-LauncherLog
    if ($hasError) { exit 2 }
    exit 0
}
