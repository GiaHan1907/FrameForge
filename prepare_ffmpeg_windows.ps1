[CmdletBinding()]
param(
    [string]$ArchiveUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-lgpl-9.0.zip",
    [string]$OutputDir = "$PSScriptRoot\vendor\ffmpeg"
)

$ErrorActionPreference = "Stop"

function Get-Sha256Hex([string]$Path) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
    }
    finally {
        $stream.Dispose()
        $sha256.Dispose()
    }
}

$TempRoot = Join-Path $env:TEMP ("frameforge_ffmpeg_" + [Guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $TempRoot "ffmpeg.zip"
$ExtractDir = Join-Path $TempRoot "extract"

try {
    New-Item -ItemType Directory -Force -Path $TempRoot, $ExtractDir, $OutputDir | Out-Null
    Write-Host "Downloading FFmpeg archive..."
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath -UseBasicParsing
    Write-Host "Expanding archive..."
    Expand-Archive -Path $ArchivePath -DestinationPath $ExtractDir -Force

    $ffmpeg = Get-ChildItem -Path $ExtractDir -Filter "ffmpeg.exe" -File -Recurse | Select-Object -First 1
    $ffprobe = Get-ChildItem -Path $ExtractDir -Filter "ffprobe.exe" -File -Recurse | Select-Object -First 1
    if (-not $ffmpeg -or -not $ffprobe) {
        throw "The archive does not contain both ffmpeg.exe and ffprobe.exe."
    }

    Copy-Item $ffmpeg.FullName (Join-Path $OutputDir "ffmpeg.exe") -Force
    Copy-Item $ffprobe.FullName (Join-Path $OutputDir "ffprobe.exe") -Force

    Get-ChildItem -Path $ExtractDir -File -Recurse |
        Where-Object { $_.Name -match '^(LICENSE|COPYING|README).*' } |
        ForEach-Object { Copy-Item $_.FullName (Join-Path $OutputDir $_.Name) -Force }

    $hashes = @(
        "Archive URL: $ArchiveUrl",
        "Archive SHA256: $(Get-Sha256Hex $ArchivePath)",
        "ffmpeg.exe SHA256: $(Get-Sha256Hex (Join-Path $OutputDir 'ffmpeg.exe'))",
        "ffprobe.exe SHA256: $(Get-Sha256Hex (Join-Path $OutputDir 'ffprobe.exe'))",
        "Prepared UTC: $([DateTime]::UtcNow.ToString('o'))"
    )
    $hashes | Set-Content (Join-Path $OutputDir "BUILD_METADATA.txt") -Encoding UTF8
    Write-Host "FFmpeg binaries prepared in $OutputDir"
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
