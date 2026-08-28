@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem FrameForge v0.1.32: desktop watchdog auto-shutdown + silent child process tree.
set "FRAMEFORGE_VERSION=0.1.32"
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
  exit /b 1
)
if not exist "%~dp0vendor\ffmpeg\ffprobe.exe" (
  echo Missing embedded vendor\ffmpeg\ffprobe.exe.
  exit /b 1
)

if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist\VideoScreenshotFilter" rmdir /s /q "%~dp0dist\VideoScreenshotFilter"
if exist "%~dp0installer\FrameForge-Setup-0.1.32.exe" del /q "%~dp0installer\FrameForge-Setup-0.1.32.exe"

call "%~dp0build_windows.bat"
if errorlevel 1 (
  echo PyInstaller build failed.
  exit /b 1
)

if not exist "%~dp0dist\VideoScreenshotFilter\VideoScreenshotFilter.exe" (
  echo EXE windowed khong duoc tao.
  exit /b 1
)

call "%~dp0build_installer.bat"
if errorlevel 1 (
  echo Inno Setup build failed.
  exit /b 1
)

if not exist "%~dp0installer\FrameForge-Setup-0.1.32.exe" (
  echo Khong tim thay installer v0.1.32.
  exit /b 1
)

for %%F in ("%~dp0installer\FrameForge-Setup-0.1.32.exe") do set "SETUP_SIZE=%%~zF"
echo.
echo ================================================
echo FrameForge v0.1.32 installer build completed.
echo Artifact: installer\FrameForge-Setup-0.1.32.exe
echo Size: !SETUP_SIZE! bytes
echo Console policy: console=False + CREATE_NO_WINDOW
echo Shutdown policy: watchdog kills current PID tree on desktop session close
echo ================================================
endlocal
