[CmdletBinding()]
param(
    [string]$InstallerPath = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\FrameForge",
    [switch]$SkipInstall,
    [switch]$SkipLaunch,
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = 'Stop'
$exePath = Join-Path $InstallDir 'VideoScreenshotFilter.exe'
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'FrameForge.lnk'
$startMenuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'

function Fail([string]$message) {
    Write-Error "SMOKE FAIL: $message"
    exit 1
}

function Read-PeSubsystem([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    try {
        $reader = [IO.BinaryReader]::new($stream)
        $stream.Seek(0x3c, [IO.SeekOrigin]::Begin) | Out-Null
        $peOffset = $reader.ReadInt32()
        $stream.Seek($peOffset + 4 + 20 + 68, [IO.SeekOrigin]::Begin) | Out-Null
        return $reader.ReadUInt16()
    } finally {
        $stream.Dispose()
    }
}

function Test-Shortcut([string]$path) {
    if (-not (Test-Path $path)) { Write-Warning "Shortcut not found: $path"; return $false }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $target = [IO.Path]::GetFullPath($shortcut.TargetPath)
    $expected = [IO.Path]::GetFullPath($exePath)
    if ($target -ne $expected) { Fail "Shortcut target mismatch: $path -> $target; expected $expected" }
    if ([IO.Path]::GetFullPath($shortcut.WorkingDirectory) -ne [IO.Path]::GetFullPath($InstallDir)) {
        Fail "Shortcut WorkingDirectory mismatch: $path -> $($shortcut.WorkingDirectory)"
    }
    Write-Host "OK shortcut: $path -> $target (WorkingDir $($shortcut.WorkingDirectory))" -ForegroundColor Green
    return $true
}

if (-not $SkipInstall) {
    if ([string]::IsNullOrWhiteSpace($InstallerPath) -or -not (Test-Path $InstallerPath)) {
        Fail "InstallerPath is required unless -SkipInstall is used."
    }
    $installer = Start-Process -FilePath $InstallerPath -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$InstallDir`"" -PassThru -Wait
    if ($installer.ExitCode -ne 0) { Fail "Installer exited with code $($installer.ExitCode)" }
}

if (-not (Test-Path $exePath)) { Fail "Installed EXE not found: $exePath" }
$subsystem = Read-PeSubsystem $exePath
if ($subsystem -ne 2) { Fail "EXE PE subsystem is $subsystem, expected GUI subsystem 2 (console=False)." }
Write-Host "OK PE subsystem: GUI (2)" -ForegroundColor Green

$shortcutCount = 0
if (Test-Shortcut $desktopShortcut) { $shortcutCount++ }
$startMenuShortcuts = @()
if (Test-Path $startMenuRoot) {
    $startMenuShortcuts = @(Get-ChildItem -Path $startMenuRoot -Filter 'FrameForge.lnk' -File -Recurse -ErrorAction SilentlyContinue)
}
foreach ($shortcut in $startMenuShortcuts) {
    if (Test-Shortcut $shortcut.FullName) { $shortcutCount++ }
}
if ($shortcutCount -eq 0) { Fail "No FrameForge shortcut was found under Desktop or Start Menu." }

if ($SkipLaunch) {
    Write-Host "OK static installer/shortcut smoke completed." -ForegroundColor Green
    exit 0
}

$env:FRAMEFORGE_AUTO_UPDATE = '0'
$env:FRAMEFORGE_NO_BROWSER = '1'
$before = @(Get-Process | Select-Object Id, ProcessName, MainWindowHandle, MainWindowTitle)
$app = Start-Process -FilePath $exePath -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
try {
    $ready = $false
    for ($i = 0; $i -lt $StartupTimeoutSeconds; $i++) {
        Start-Sleep -Seconds 1
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { Fail "Installed EXE did not expose Streamlit HTTP endpoint within timeout." }

    $app.Refresh()
    if ($app.MainWindowHandle -ne 0) { Fail "Main app unexpectedly has a visible native window handle." }

    $after = @(Get-Process | Select-Object Id, ProcessName, MainWindowHandle, MainWindowTitle)
    $newVisible = @($after | Where-Object {
        $old = $_
        ($before.Id -notcontains $old.Id) -and $old.MainWindowHandle -ne 0 -and $old.MainWindowTitle
    })
    if ($newVisible.Count -gt 0) {
        $names = ($newVisible | ForEach-Object { "$($_.ProcessName):$($_.MainWindowTitle)" }) -join ', '
        Fail "Detected new visible process window(s): $names"
    }
    Write-Host "OK launch smoke: HTTP 200 and no new visible process window detected." -ForegroundColor Green
} finally {
    if ($app -and -not $app.HasExited) { Stop-Process -Id $app.Id -Force -ErrorAction SilentlyContinue }
}

exit 0
