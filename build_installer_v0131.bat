@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem FrameForge v0.1.31: build EXE windowed + child-process console suppression.
set "FRAMEFORGE_VERSION=0.1.31"
set "BUILD_MODE=onedir"
set "BUILD_PROFILE=full"

where python >nul 2>nul
if errorlevel 1 (
  echo Khong tim thay Python trong PATH.
  exit /b 1
)

if not exist "%~dp0video_screenshot_filter_onedir.spec" (
  echo Khong tim thay PyInstaller spec onedir.
  exit /b 1
)
if not exist "%~dp0FrameForge.iss" (
  echo Khong tim thay FrameForge.iss.
  exit /b 1
)

if not exist "%~dp0vendor\ffmpeg\ffmpeg.exe" (
  echo Missing embedded vendor\ffmpeg\ffmpeg.exe.
  echo Hay chay prepare_ffmpeg_windows.ps1 hoac build_windows.bat truoc.
  exit /b 1
)
if not exist "%~dp0vendor\ffmpeg\ffprobe.exe" (
  echo Missing embedded vendor\ffmpeg\ffprobe.exe.
  exit /b 1
)

rem Luon build lai tu source hien tai, khong dung dist cu.
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist\VideoScreenshotFilter" rmdir /s /q "%~dp0dist\VideoScreenshotFilter"
if exist "%~dp0installer\FrameForge-Setup-0.1.31.exe" del /q "%~dp0installer\FrameForge-Setup-0.1.31.exe"

call "%~dp0build_windows.bat"
if errorlevel 1 (
  echo PyInstaller build failed.
  exit /b 1
)

if not exist "%~dp0dist\VideoScreenshotFilter\VideoScreenshotFilter.exe" (
  echo EXE windowed khong duoc tao.
  exit /b 1
)

set "ISCC=%ISCC%"
call "%~dp0build_installer.bat"
if errorlevel 1 (
  echo Inno Setup build failed.
  exit /b 1
)

if not exist "%~dp0installer\FrameForge-Setup-0.1.31.exe" (
  echo Khong tim thay installer v0.1.31.
  exit /b 1
)

for %%F in ("%~dp0installer\FrameForge-Setup-0.1.31.exe") do set "SETUP_SIZE=%%~zF"
echo.
echo ================================================
echo FrameForge v0.1.31 installer build completed.
echo Artifact: installer\FrameForge-Setup-0.1.31.exe
echo Size: !SETUP_SIZE! bytes
echo Main EXE: dist\VideoScreenshotFilter\VideoScreenshotFilter.exe
echo Console policy: PyInstaller console=False + CREATE_NO_WINDOW child processes
echo ================================================
endlocal
