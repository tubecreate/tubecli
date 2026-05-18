@echo off
title TubeCLI - Kill & Repair
echo.
echo  ============================================
echo   TubeCLI Kill ^& Repair Tool
echo  ============================================
echo.

echo [1] Killing all TubeCLI processes...
taskkill /F /FI "WINDOWTITLE eq TubeCLI*" 2>nul
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST 2^>nul ^| findstr "PID:"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr /I "tubecli uvicorn" >nul 2>nul && (
        taskkill /F /PID %%a >nul 2>nul
        echo     Killed PID %%a
    )
)
echo [OK] Processes cleaned.
echo.

echo [2] Reinstalling TubeCLI module...
cd /d "%~dp0"
python -m pip install -e . --quiet
if %ERRORLEVEL% EQU 0 (
    echo [OK] TubeCLI reinstalled successfully!
) else (
    echo [!] pip install failed. Trying with --force-reinstall...
    python -m pip install -e . --force-reinstall --quiet
)
echo.

echo [3] Verifying...
tubecli --version
if %ERRORLEVEL% EQU 0 (
    echo.
    echo  ============================================
    echo   [OK] TubeCLI is working! You can now run:
    echo        tubecli
    echo  ============================================
) else (
    echo.
    echo  [!] tubecli still not found.
    echo  Please close this window, open a NEW terminal,
    echo  and try: tubecli
)
echo.
pause
