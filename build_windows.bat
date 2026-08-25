@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%BUILD_MODE%"=="" set "BUILD_MODE=onedir"
if "%BUILD_PROFILE%"=="" set "BUILD_PROFILE=full"
if /I not "%BUILD_MODE%"=="onedir" if /I not "%BUILD_MODE%"=="onefile" (
  echo BUILD_MODE phai la onedir hoac onefile.
  exit /b 1
)
if /I not "%BUILD_PROFILE%"=="full" if /I not "%BUILD_PROFILE%"=="minimal" (
  echo BUILD_PROFILE phai la full hoac minimal.
  exit /b 1
)
if /I "%BUILD_PROFILE%"=="minimal" if /I "%BUILD_MODE%"=="onefile" (
  echo Profile minimal hien chi duoc kiem thu voi BUILD_MODE=onedir.
  echo Hay dung: set BUILD_PROFILE=minimal ^&^& set BUILD_MODE=onedir
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Khong tim thay Python trong PATH.
  exit /b 1
)

if /I "%FRAMEFORGE_SKIP_VENV%"=="1" (
  echo Using Python environment from PATH (CI mode)...
) else (
  if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
  )
  call .venv\Scripts\activate.bat
)
python -m pip install --upgrade pip
if /I "%BUILD_PROFILE%"=="minimal" (
  python -m pip install -r requirements.txt pyinstaller
) else (
  python -m pip install -r requirements_full.txt pyinstaller
)

if not exist vendor\ffmpeg\ffmpeg.exe (
  echo Preparing embedded FFmpeg binaries...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_ffmpeg_windows.ps1" -OutputDir "%~dp0vendor\ffmpeg"
)
if not exist vendor\ffmpeg\ffprobe.exe (
  echo Missing vendor\ffmpeg\ffprobe.exe
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 echo Note: system FFmpeg is not required; embedded binaries will be used.

if defined FRAMEFORGE_VERSION (
  >frameforge_version.txt echo %FRAMEFORGE_VERSION%
)

if /I "%BUILD_PROFILE%"=="minimal" (
  set "SPEC=video_screenshot_filter_minimal.spec"
) else (
  set "SPEC=video_screenshot_filter_onedir.spec"
)

if /I "%BUILD_MODE%"=="onedir" (
  echo Building %BUILD_PROFILE% onedir package...
  pyinstaller --noconfirm --clean "%SPEC%"
  if errorlevel 1 exit /b 1
  set "ARTIFACT=dist\VideoScreenshotFilter\VideoScreenshotFilter.exe"
) else (
  echo Building full one-file executable...
  pyinstaller --noconfirm --clean video_screenshot_filter.spec
  if errorlevel 1 exit /b 1
  set "ARTIFACT=dist\VideoScreenshotFilter.exe"
)

python measure_package_size.py . --json build_size_report.json

echo.
echo Build completed: %ARTIFACT%
echo Size report: build_size_report.json
endlocal
