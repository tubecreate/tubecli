# powershell -c "irm https://raw.githubusercontent.com/.../install.ps1 | iex"
param(
    [string]$RepoUrl = "https://github.com/tubecreate/tubecli.git",
    [string]$Branch = "main",
    [string]$InstallDir,
    # Must stay in sync with SUPPORTED_LANGUAGES in tubecli/config.py. Untyped,
    # `tubecli init --lang de` got all the way to the end of the installer and then
    # died on a click Choice error with exit 2, long after the green banners.
    [ValidateSet('zh', 'zh-TW', 'vi', 'en', 'ja', 'ko', 'es', 'tr', 'ru')]
    [string]$Lang = "en"
)

$ErrorActionPreference = "Stop"

$script:InstallExitCode = 0

function Fail-Install {
    param([int]$Code = 1)
    # No `return $false` here: at script scope that value would print as stray
    # "False" output. Callers pair this with Complete-Install -Succeeded:$false.
    $script:InstallExitCode = $Code
}

function Complete-Install {
    param([bool]$Succeeded)
    if ($Succeeded) { return }
    # A failed install must never report success. Fail-Install had no callers at
    # all, so $InstallExitCode was permanently 0 and every failure path either
    # `exit 0`-ed or threw the self-contradicting "failed with exit code 0".
    # This floor makes that impossible even if a future failure site forgets to
    # call Fail-Install.
    if ($script:InstallExitCode -eq 0) { $script:InstallExitCode = 1 }
    if ($PSCommandPath) { exit $script:InstallExitCode }
    throw "TubeCLI installation failed with exit code $($script:InstallExitCode)."
}

Write-Host ""
Write-Host "  TubeCLI Installer" -ForegroundColor Cyan
Write-Host "  =================" -ForegroundColor Cyan
Write-Host ""

# Check if running in PowerShell
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host "Error: PowerShell 5+ required" -ForegroundColor Red
    Complete-Install -Succeeded:$false
    return
}

Write-Host "[OK] Windows detected" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $userHome = [Environment]::GetFolderPath("UserProfile")
    $InstallDir = (Join-Path $userHome "tubecli")
}

# --- Python Checking and Installation ---

function Check-Python {
    param([int]$Depth = 0)
    if ($Depth -gt 1) {
        Write-Host "[!] Python found at known location but not working correctly" -ForegroundColor Yellow
        return $false
    }
    try {
        $pythonVersion = (python --version 2>$null)
        if ($pythonVersion -match "Python (\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -eq 3 -and $minor -ge 10) {
                Write-Host "[OK] $pythonVersion found" -ForegroundColor Green
                return $true
            } else {
                Write-Host "[!] $pythonVersion found, but v3.10+ required" -ForegroundColor Yellow
                return $false
            }
        }
    } catch {
        # Check if python is in another common location but not on PATH
        $localPython = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
        if (Test-Path $localPython) {
            Add-ToProcessPath (Split-Path $localPython)
            Add-ToProcessPath (Join-Path (Split-Path $localPython) "Scripts")
            return (Check-Python -Depth ($Depth + 1))
        }
        Write-Host "[!] Python not found on PATH" -ForegroundColor Yellow
        return $false
    }
    return $false
}

function Install-Python {
    Write-Host "[*] Installing Python 3.11..." -ForegroundColor Yellow

    # NOTE on `| Out-Host` and `$null = Read-Host` below, in all three Install-*
    # functions: every uncaptured value in a PowerShell function joins its return
    # value. winget's stdout and Read-Host's answer used to do exactly that, so
    # `return $false` really returned an Object[] of [winget text..., answer, $false],
    # and PowerShell coerces a non-empty array to $true. `if (-not (Install-Python))`
    # was therefore never true and the failure branch never ran.
    # Out-Host rather than Out-Null on purpose: it still shows winget's progress,
    # it just keeps it out of the pipeline.
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget..." -ForegroundColor Gray
        winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" | Out-Host

        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Check-Python) {
            Write-Host "[OK] Python installed via winget" -ForegroundColor Green
            return $true
        }
    }

    # Fallback: guide user to install manually (avoids antivirus false positives)
    Write-Host ""
    Write-Host "  [!] winget not available. Please install Python 3.11+ manually:" -ForegroundColor Yellow
    Write-Host "      https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during installation!" -ForegroundColor Yellow
    Write-Host ""
    try { Start-Process "https://www.python.org/downloads/" } catch {}
    $null = Read-Host "  Press Enter after installing Python..."

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    if (Check-Python) {
        Write-Host "[OK] Python detected after manual install" -ForegroundColor Green
        return $true
    }

    Write-Host "[!] Python still not found. Please restart your terminal and try again." -ForegroundColor Yellow
    return $false
}

# --- Git Checking and Installation ---

function Check-Git {
    try {
        $null = Get-Command git -ErrorAction Stop
        Write-Host "[OK] Git found" -ForegroundColor Green
        return $true
    } catch {
        return $false
    }
}

function Install-Git {
    Write-Host "[*] Installing Git..." -ForegroundColor Yellow

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget..." -ForegroundColor Gray
        winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements | Out-Host

        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Check-Git) {
            Write-Host "[OK] Git installed via winget" -ForegroundColor Green
            return $true
        }
    }

    # Fallback: guide user to install manually (avoids antivirus false positives)
    Write-Host ""
    Write-Host "  [!] winget not available. Please install Git manually:" -ForegroundColor Yellow
    Write-Host "      https://git-scm.com/download/win" -ForegroundColor Cyan
    Write-Host ""
    try { Start-Process "https://git-scm.com/download/win" } catch {}
    $null = Read-Host "  Press Enter after installing Git..."

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    if (Check-Git) {
        Write-Host "[OK] Git detected after manual install" -ForegroundColor Green
        return $true
    }

    Write-Host "[!] Git still not found. Please restart your terminal and try again." -ForegroundColor Red
    return $false
}

# --- Node.js checking and Installation ---

function Check-Node {
    try {
        $null = Get-Command node -ErrorAction Stop
        $null = Get-Command npm -ErrorAction Stop
        Write-Host "[OK] Node.js and npm found" -ForegroundColor Green
        return $true
    } catch {
        return $false
    }
}

function Install-Node {
    Write-Host "[*] Installing Node.js..." -ForegroundColor Yellow

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget..." -ForegroundColor Gray
        winget install --id OpenJS.NodeJS --source winget --accept-package-agreements --accept-source-agreements | Out-Host

        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Check-Node) {
            Write-Host "[OK] Node.js installed via winget" -ForegroundColor Green
            return $true
        }
    }

    # Fallback: guide user to install manually (avoids antivirus false positives)
    Write-Host ""
    Write-Host "  [!] winget not available. Please install Node.js LTS manually:" -ForegroundColor Yellow
    Write-Host "      https://nodejs.org/" -ForegroundColor Cyan
    Write-Host ""
    try { Start-Process "https://nodejs.org/" } catch {}
    $null = Read-Host "  Press Enter after installing Node.js (or press Enter to skip)..."

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    if (Check-Node) {
        Write-Host "[OK] Node.js detected after manual install" -ForegroundColor Green
        return $true
    }

    Write-Host "[!] Node.js still not found. Browser extension may not work until installed." -ForegroundColor Yellow
    return $false
}

# --- Environment Variable Helpers ---

function Add-ToProcessPath([string]$PathEntry) {
    if ([string]::IsNullOrWhiteSpace($PathEntry)) { return }
    $currentEntries = @($env:Path -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($currentEntries | Where-Object { $_ -ieq $PathEntry }) { return }
    $env:Path = "$PathEntry;$env:Path"
}

function Add-ToUserPath([string]$PathEntry) {
    if ([string]::IsNullOrWhiteSpace($PathEntry)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not ($userPath -split ";" | Where-Object { $_ -ieq $PathEntry })) {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$PathEntry", "User")
        Write-Host "[!] Added $PathEntry to User PATH" -ForegroundColor Gray
    }
}

function Ensure-PythonScriptsInPath {
    # Get Python executable path
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source) {
        $pythonDir = Split-Path $pythonCmd.Source
        $scriptsDir = Join-Path $pythonDir "Scripts"
        
        if (Test-Path $scriptsDir) {
            Add-ToProcessPath $scriptsDir
            Add-ToUserPath $scriptsDir
        }
    }
    
    # Also check roaming appdata Python paths (often where pip installs user scripts)
    $appdataScripts = Join-Path $env:APPDATA "Python\Python311\Scripts" # Adjust based on version if needed
    if (Test-Path $appdataScripts) {
        Add-ToProcessPath $appdataScripts
        Add-ToUserPath $appdataScripts
    }
}

# --- Main Logic ---

# Stop any running TubeCLI processes to prevent file lock during install
Write-Host "[*] Stopping running TubeCLI processes..." -ForegroundColor Yellow
$killedCount = 0

# NOTE: the loop below must not use $pid - that is a read-only automatic variable
# holding this shell's own PID, and assigning to it throws a TERMINATING error.
# It used to, inside one big try/catch, so the throw skipped steps 2 and 3 as well:
# nothing was ever killed, the file handle stayed locked, pip failed on the copy
# step, and the script still printed a green "No running TubeCLI processes found".
# Each step also gets its own try now, so one failure can't silence the others.
try {
    # 1. Kill API server by port
    $netstatOut = netstat -ano | Select-String ":5295\s" | Select-String "LISTENING"
    foreach ($line in $netstatOut) {
        $parts = $line.ToString().Trim() -split '\s+'
        $procId = $parts[-1]
        if ($procId -and $procId -ne "0" -and $procId -match '^\d+$' -and [int]$procId -ne $PID) {
            Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
            $killedCount++
        }
    }
} catch { }

try {
    # 2. Kill tubecli.exe CLI process via PowerShell
    Get-Process -Name "tubecli" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        $killedCount++
    }
} catch { }

try {
    # 3. Fallback: taskkill /F /IM ensures Windows releases the file handle.
    # Routed through cmd so its "process not found" stderr is swallowed there -
    # redirecting a native command's stderr inside PS 5.1 wraps each line in a
    # NativeCommandError and would print a red ERROR during a normal install.
    cmd /c "taskkill /F /IM tubecli.exe >nul 2>nul"
    if ($LASTEXITCODE -eq 0) { $killedCount++ }
} catch { }
if ($killedCount -gt 0) {
    Write-Host "[OK] Stopped $killedCount running process(es)" -ForegroundColor Green
    Start-Sleep -Seconds 3  # Wait for Windows to fully release file handles
} else {
    Write-Host "[OK] No running TubeCLI processes found" -ForegroundColor Green
}

# Clean up corrupted pip distributions (~ / ~ubecli / ~~becli remnants)
try {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source) {
        $sitePackages = Join-Path (Split-Path $pythonCmd.Source) "Lib\site-packages"
        if (Test-Path $sitePackages) {
            Get-ChildItem -Path $sitePackages -Directory -Filter "~*" -ErrorAction SilentlyContinue | ForEach-Object {
                Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "  [OK] Cleaned corrupted distribution: $($_.Name)" -ForegroundColor Gray
            }
        }
    }
} catch {}

# @(...)[-1] rather than `-not (...)`: the Install-* functions are fixed at the
# source now, but taking the last emitted value means a future stray write into
# the output stream still cannot turn a failure into a success. Note that the
# obvious-looking `(Install-Python) -ne $true` would NOT work - against an array
# PowerShell filters instead of comparing, and a non-empty result is truthy.
if (-not (Check-Python)) {
    if (@(Install-Python)[-1] -ne $true) {
        Write-Host "[!] Python 3.10+ is required and could not be installed." -ForegroundColor Red
        Fail-Install
        Complete-Install -Succeeded:$false
        return
    }
}

if (-not (Check-Git)) {
    if (@(Install-Git)[-1] -ne $true) {
        Write-Host "[!] Git is required and could not be installed." -ForegroundColor Red
        Fail-Install
        Complete-Install -Succeeded:$false
        return
    }
}

# Node stays a warning on purpose: only the browser extension needs it.
if (-not (Check-Node)) {
    if (@(Install-Node)[-1] -ne $true) {
        Write-Host "[!] Warning: Node.js installation failed or requires a terminal restart. The browser extension might not work until Node.js is installed manually." -ForegroundColor Yellow
    }
}

Write-Host "[*] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip | Out-Null

$targetDir = ""

# If setup.py or pyproject.toml exists in current directory, assume local installation
if ((Test-Path ".\setup.py") -or (Test-Path ".\pyproject.toml")) {
    Write-Host "[*] Local project directory detected, installing from current directory." -ForegroundColor Green
    $targetDir = (Get-Location).Path
} else {
    Write-Host "[*] Cloning TubeCLI repository to $InstallDir..." -ForegroundColor Yellow
    # Both git calls used to run unchecked. A clone blocked by a proxy, or a pull
    # against a directory that is not a git repo (exit 128), left the old code -
    # or no code - in place while the installer carried on printing success.
    if (-not (Test-Path $InstallDir)) {
        git clone -b $Branch $RepoUrl $InstallDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] Could not download TubeCLI (git clone failed, exit $LASTEXITCODE)." -ForegroundColor Red
            Write-Host "    Check your internet connection, proxy, or company firewall, then run this again." -ForegroundColor Yellow
            Fail-Install
            Complete-Install -Succeeded:$false
            return
        }
    } elseif (-not (Test-Path (Join-Path $InstallDir ".git"))) {
        Write-Host "[!] $InstallDir already exists but is not a TubeCLI checkout." -ForegroundColor Red
        Write-Host "    Move or delete it, or re-run with -InstallDir <another path>." -ForegroundColor Yellow
        Fail-Install
        Complete-Install -Succeeded:$false
        return
    } else {
        Write-Host "  Directory exists, pulling latest changes..." -ForegroundColor Gray
        git -C $InstallDir pull origin $Branch
        if ($LASTEXITCODE -ne 0) {
            # Not fatal: the existing checkout is still installable, and stopping
            # here would strand anyone offline. But say so, instead of letting the
            # user believe they upgraded.
            Write-Host "[!] Could not fetch updates (git pull failed, exit $LASTEXITCODE)." -ForegroundColor Yellow
            Write-Host "    Continuing with the version already in $InstallDir." -ForegroundColor Yellow
        }
    }
    $targetDir = $InstallDir
}

Write-Host "[*] Installing TubeCLI (this may take a few minutes)..." -ForegroundColor Yellow
$prevDir = Get-Location
Set-Location $targetDir

try {
    # Install with retry logic for file lock issues (WinError 32)
    $installSuccess = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        python -m pip install -e .
        if ($LASTEXITCODE -eq 0) {
            $installSuccess = $true
            break
        }
        if ($attempt -lt 3) {
            Write-Host "  [!] Install attempt $attempt failed. Retrying in 5 seconds..." -ForegroundColor Yellow
            # Force kill any remaining tubecli processes before retry
            taskkill /F /IM "tubecli.exe" 2>$null | Out-Null
            Start-Sleep -Seconds 5
        }
    }
    if (-not $installSuccess) {
        Write-Host "[!] pip install failed after 3 attempts." -ForegroundColor Red
        Write-Host "    Please close all TubeCLI windows and terminals, then try again." -ForegroundColor Yellow
        Set-Location $prevDir
        Fail-Install
        Complete-Install -Succeeded:$false
        return
    }
} finally {
    Set-Location $prevDir
}

Ensure-PythonScriptsInPath

# Check if tubecli is available
$tubecliCmd = Get-Command tubecli -ErrorAction SilentlyContinue
if (-not $tubecliCmd) {
    Write-Host "[!] tubecli command not found on PATH. Checking common locations..." -ForegroundColor Yellow
    Ensure-PythonScriptsInPath
    $tubecliCmd = Get-Command tubecli -ErrorAction SilentlyContinue
}

# We always create launcher and shortcuts because the installation was successful!
Write-Host "[OK] TubeCLI installed successfully!" -ForegroundColor Green

# -- Create Launcher & Shortcuts (BEFORE init, since init blocks) --
Write-Host ""
Write-Host "[*] Creating launcher and shortcuts..." -ForegroundColor Yellow

# 1. Create TubeCLI.bat launcher in install directory
$batPath = Join-Path $targetDir "TubeCLI.bat"
$batContent = @"
@echo off
setlocal enabledelayedexpansion

REM === Check if TubeCLI is already running (by checking API port) ===
set ALREADY_RUNNING=0
netstat -ano 2>nul | findstr ":5295" | findstr "LISTENING" >nul 2>nul
if !ERRORLEVEL! EQU 0 set ALREADY_RUNNING=1

if !ALREADY_RUNNING! EQU 1 (
    cls
    echo.
    echo  ==================================================
    echo             TubeCLI - Already Running
    echo  ==================================================
    echo.
    echo    1. Open Dashboard
    echo    2. Restart TubeCLI
    echo    3. Shut down TubeCLI
    echo    0. Exit
    echo.
    echo  ==================================================
    echo.
    set /p opt="  Select an option: "
    
    if "!opt!"=="" set opt=1
    
    if "!opt!"=="1" (
        start http://localhost:5295/dashboard
        exit
    )
    if "!opt!"=="2" (
        echo.
        echo   Restarting TubeCLI...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5295" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        timeout /t 2 /nobreak >nul
        goto :START_CLI
    )
    if "!opt!"=="3" (
        echo.
        echo   Shutting down TubeCLI...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5295" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        echo   Done.
        timeout /t 1 /nobreak >nul
        exit
    )
    exit
)

:START_CLI
title TubeCLI - AI Agent System
cd /d "$targetDir"

python -m tubecli.main init
pause
"@
Set-Content -Path $batPath -Value $batContent -Encoding UTF8
Write-Host "  [OK] Created launcher: $batPath" -ForegroundColor Green

# 2. Use the provided dashboard logo (.ico)
$icoPath = Join-Path $targetDir "tubecli\extensions\webui\static\logo.ico"
$useDefaultIcon = $false
if (-not (Test-Path $icoPath)) {
    Write-Host "  [!] Warning: $icoPath not found, shortcut might not have an icon." -ForegroundColor Yellow
} else {
    Write-Host "  [OK] Found icon: $icoPath" -ForegroundColor Green
}

# 3. Create Desktop shortcut
try {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "TubeCLI.lnk"

    $WshShell = New-Object -ComObject WScript.Shell
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $batPath
    $shortcut.WorkingDirectory = $targetDir
    $shortcut.Description = "TubeCLI - Open Source AI Agent System"
    $shortcut.WindowStyle = 1
    if ((-not $useDefaultIcon) -and (Test-Path $icoPath)) {
        $shortcut.IconLocation = "$icoPath,0"
    }
    $shortcut.Save()
    Write-Host "  [OK] Desktop shortcut created: $shortcutPath" -ForegroundColor Green
} catch {
    Write-Host "  [!] Could not create Desktop shortcut: $_" -ForegroundColor Yellow
}

# 4. Create Start Menu shortcut
try {
    $startMenuDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\TubeCLI"
    if (-not (Test-Path $startMenuDir)) {
        New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null
    }
    $startShortcutPath = Join-Path $startMenuDir "TubeCLI.lnk"

    $WshShell2 = New-Object -ComObject WScript.Shell
    $startShortcut = $WshShell2.CreateShortcut($startShortcutPath)
    $startShortcut.TargetPath = $batPath
    $startShortcut.WorkingDirectory = $targetDir
    $startShortcut.Description = "TubeCLI - Open Source AI Agent System"
    $startShortcut.WindowStyle = 1
    if ((-not $useDefaultIcon) -and (Test-Path $icoPath)) {
        $startShortcut.IconLocation = "$icoPath,0"
    }
    $startShortcut.Save()
    Write-Host "  [OK] Start Menu shortcut created" -ForegroundColor Green
} catch {
    Write-Host "  [!] Could not create Start Menu shortcut: $_" -ForegroundColor Yellow
}

# Prove it before announcing it. "Installation Complete!" used to be printed on
# hope alone - pip could have succeeded while the console script was unusable, and
# the user was told to double-click a shortcut that would then do nothing.
Write-Host "[*] Verifying installation..." -ForegroundColor Yellow
if ($tubecliCmd) {
    tubecli --version | Out-Host
} else {
    python -m tubecli.main --version | Out-Host
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] TubeCLI was installed but does not run (exit $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "    Close this window, open a NEW terminal, and run: tubecli --version" -ForegroundColor Yellow
    Write-Host "    If it still fails, please report the output above." -ForegroundColor Yellow
    Fail-Install
    Complete-Install -Succeeded:$false
    return
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  You can now launch TubeCLI by:" -ForegroundColor White
Write-Host "    1. Double-click 'TubeCLI' on your Desktop" -ForegroundColor Cyan
Write-Host "    2. Search 'TubeCLI' in Start Menu" -ForegroundColor Cyan
Write-Host "    3. Type 'tubecli' in any terminal" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dashboard: http://127.0.0.1:5295/dashboard" -ForegroundColor Cyan
Write-Host "  (the control panel opening next starts it for you - pick option 1)" -ForegroundColor Gray
Write-Host ""

# -- Run init LAST (blocks with interactive menu) --
# These instructions are printed before init on purpose: init does not return, it
# hands over to the control panel, so anything printed after would never be seen.
Write-Host "[*] Launching TubeCLI..." -ForegroundColor Yellow
if ($tubecliCmd) {
    tubecli init --lang $Lang --port 5295
} else {
    python -m tubecli.main init --lang $Lang --port 5295
}
$initExit = $LASTEXITCODE

# Was unconditionally -Succeeded:$true, so a wizard that died still ended the
# installer with a success status.
if ($initExit -ne 0) {
    Write-Host ""
    Write-Host "[!] Setup did not finish cleanly (exit $initExit)." -ForegroundColor Yellow
    Write-Host "    TubeCLI itself is installed - run 'tubecli init' again when ready." -ForegroundColor Yellow
    Fail-Install -Code $initExit
    Complete-Install -Succeeded:$false
    return
}

Complete-Install -Succeeded:$true
