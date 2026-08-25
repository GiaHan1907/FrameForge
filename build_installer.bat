@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined ISCC (
  where ISCC.exe >nul 2>nul
  if not errorlevel 1 set "ISCC=ISCC.exe"
)
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Khong tim thay Inno Setup Compiler ISCC.exe.
  echo Cai Inno Setup 6 roi chay lai, hoac dat bien ISCC tro toi ISCC.exe.
  exit /b 1
)

if not exist "dist\VideoScreenshotFilter\VideoScreenshotFilter.exe" (
  echo Khong tim thay dist\VideoScreenshotFilter\VideoScreenshotFilter.exe.
  echo Hay chay build_windows.bat truoc voi profile onedir.
  exit /b 1
)

if not exist installer mkdir installer
del /q installer\FrameForge-Setup-*.exe 2>nul
set "ISCC_ARGS=/Qp"
if defined FRAMEFORGE_VERSION set "ISCC_ARGS=/Qp /DMyAppVersion=%FRAMEFORGE_VERSION%"
"%ISCC%" %ISCC_ARGS% FrameForge.iss
if errorlevel 1 (
  echo Inno Setup build failed.
  exit /b 1
)

set "SETUP_FILE="
for /f "delims=" %%F in ('dir /b /a-d installer\FrameForge-Setup-*.exe 2^>nul') do set "SETUP_FILE=installer\%%F"
if not defined SETUP_FILE (
  echo Inno Setup returned success but no Setup file was found.
  exit /b 1
)

echo Installer created: %SETUP_FILE%
for %%F in ("%SETUP_FILE%") do echo Size: %%~zF bytes
endlocal
