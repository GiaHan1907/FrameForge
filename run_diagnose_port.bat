@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "LOG=%~dp0VideoScreenshotFilter_diagnostic.log"
del /q "%LOG%" 2>nul

echo ==== START %DATE% %TIME% ==== > "%LOG%"
if not exist "%~dp0VideoScreenshotFilter.exe" (
  echo Khong tim thay VideoScreenshotFilter.exe >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 2
)

echo Starting EXE... >> "%LOG%"
start "VideoScreenshotFilter" /b "%~dp0VideoScreenshotFilter.exe"
echo Waiting 12 seconds... >> "%LOG%"
timeout /t 12 /nobreak >nul

echo ==== TASKLIST ==== >> "%LOG%"
tasklist /fi "IMAGENAME eq VideoScreenshotFilter.exe" >> "%LOG%" 2>&1

echo ==== PORT 8501 ==== >> "%LOG%"
netstat -ano | findstr ":8501" >> "%LOG%" 2>&1

echo ==== HTTP CHECK ==== >> "%LOG%"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$u='http://127.0.0.1:8501/'; try { $r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 5; Add-Content -LiteralPath '%LOG%' -Value ('HTTP_STATUS=' + [int]$r.StatusCode) } catch { Add-Content -LiteralPath '%LOG%' -Value ('HTTP_ERROR=' + $_.Exception.Message) }" >> "%LOG%" 2>&1

if exist "%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log" (
  echo ==== LAUNCHER ERROR LOG ==== >> "%LOG%"
  type "%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log" >> "%LOG%"
)
echo ==== END %DATE% %TIME% ==== >> "%LOG%"

echo.
echo Diagnostic da xong. Noi dung log:
echo ----------------------------------------
type "%LOG%"
echo ----------------------------------------
echo Gui file VideoScreenshotFilter_diagnostic.log cho nguoi ho tro.
pause
