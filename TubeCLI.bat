@echo off
setlocal enabledelayedexpansion

REM === Check if TubeCLI is already running (by checking API port) ===
set ALREADY_RUNNING=0
netstat -ano 2>nul | findstr ":5295" | findstr "LISTENING" >nul 2>nul
if !ERRORLEVEL! EQU 0 set ALREADY_RUNNING=1

if !ALREADY_RUNNING! EQU 1 (
    cls
    echo ==============================================================
    echo  TubeCLI is already running.
    echo ==============================================================
    echo.
    echo  What would you like to do?
    echo.
    echo  [1] Open Dashboard
    echo  [2] Restart TubeCLI
    echo  [3] Shut down TubeCLI
    echo  [4] Exit
    echo.
    set /p opt="Select an option (1-4, default is 1): "
    
    if "!opt!"=="" set opt=1
    
    if "!opt!"=="1" (
        start http://localhost:5295/dashboard
        exit
    )
    if "!opt!"=="2" (
        echo Restarting TubeCLI...
        echo Shutting down existing instance...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5295" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        timeout /t 2 /nobreak >nul
        goto :START_CLI
    )
    if "!opt!"=="3" (
        echo Shutting down TubeCLI...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5295" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        echo Done.
        timeout /t 1 /nobreak >nul
        exit
    )
    exit
)

:START_CLI
title TubeCLI - AI Agent System
cd /d "C:\tubecreate-vue\tubecli"

where tubecli >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    tubecli init
) else (
    python -m tubecli.main init
)
pause
