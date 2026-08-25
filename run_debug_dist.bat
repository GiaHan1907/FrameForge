@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "VideoScreenshotFilter.exe" (
  echo Khong tim thay VideoScreenshotFilter.exe trong:
  echo %CD%
  pause
  exit /b 2
)

echo Dang chay VideoScreenshotFilter.exe ...
echo Log se duoc ghi vao:
echo %CD%\VideoScreenshotFilter_error.log

echo ==== START %DATE% %TIME% ==== > "VideoScreenshotFilter_error.log"
"%CD%\VideoScreenshotFilter.exe" >> "VideoScreenshotFilter_error.log" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo ==== END %DATE% %TIME% | exit_code=%EXITCODE% ==== >> "VideoScreenshotFilter_error.log"

echo.
echo ===== NOI DUNG LOG =====
type "VideoScreenshotFilter_error.log"
echo.
echo ===== EXIT CODE: %EXITCODE% =====
echo Gui file VideoScreenshotFilter_error.log cho nguoi ho tro.
pause
exit /b %EXITCODE%
