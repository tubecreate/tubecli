# powershell -c "irm https://raw.githubusercontent.com/.../install.ps1 | iex"
param(
    [string]$RepoUrl = "https://github.com/tubecreate/tubecli.git",
    [string]$Branch = "main",
    [string]$InstallDir
)

$ErrorActionPreference = "Stop"

$script:InstallExitCode = 0

function Fail-Install {
    param([int]$Code = 1)
    $script:InstallExitCode = $Code
    return $false
}

function Complete-Install {
    param([bool]$Succeeded)
    if ($Succeeded) { return }
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
            return Check-Python
        }
        Write-Host "[!] Python not found on PATH" -ForegroundColor Yellow
        return $false
    }
    return $false
}

function Install-Python {
    Write-Host "[*] Installing Python 3.11..." -ForegroundColor Yellow

    # Try winget
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget..." -ForegroundColor Gray
        winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0"
        
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Check-Python) {
            Write-Host "[OK] Python installed via winget" -ForegroundColor Green
            return $true
        }
    }

    # Fallback to direct download
    Write-Host "  Downloading Python installer..." -ForegroundColor Gray
    $installerPath = Join-Path $env:TEMP "python-installer.exe"
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.8/python-3.11.8-amd64.exe" -OutFile $installerPath
    
    Write-Host "  Running Python installer (this may take a minute)..." -ForegroundColor Gray
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
    
    Remove-Item $installerPath -ErrorAction SilentlyContinue

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    if (Check-Python) {
        Write-Host "[OK] Python installed via direct download" -ForegroundColor Green
        return $true
    }

    Write-Host "[!] Python installation completed, but 'python' is still not found in this shell." -ForegroundColor Yellow
    Write-Host "Please restart your computer or terminal, and try again." -ForegroundColor Yellow
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
        winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
        
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        
        if (Check-Git) {
            Write-Host "[OK] Git installed via winget" -ForegroundColor Green
            return $true
        }
    }

    # Fallback portable git download similar to openclaw can go here, but winget usually works
    # For now, let's use direct download of MinGit
    Write-Host "  Downloading Portable MinGit..." -ForegroundColor Gray
    $minGitUrl = "https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/MinGit-2.44.0-64-bit.zip"
    $minGitZip = Join-Path $env:TEMP "mingit.zip"
    $minGitDir = Join-Path $env:LOCALAPPDATA "MinGit"

    if (-not (Test-Path $minGitDir)) {
        New-Item -ItemType Directory -Force -Path $minGitDir | Out-Null
    }

    Invoke-WebRequest -Uri $minGitUrl -OutFile $minGitZip
    Expand-Archive -Path $minGitZip -DestinationPath $minGitDir -Force
    Remove-Item $minGitZip -ErrorAction SilentlyContinue

    Add-ToProcessPath (Join-Path $minGitDir "cmd")
    Add-ToUserPath (Join-Path $minGitDir "cmd")

    if (Check-Git) {
        Write-Host "[OK] Portable Git installed" -ForegroundColor Green
        return $true
    }

    Write-Host "[!] Git installation failed." -ForegroundColor Red
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

# Kill all running TubeCLI processes to prevent conflicts
Write-Host "[*] Killing existing TubeCLI processes..." -ForegroundColor Yellow
$killedCount = 0
try {
    # Kill by window title
    Get-Process | Where-Object { $_.MainWindowTitle -like "TubeCLI*" } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        $killedCount++
    }
    # Kill python processes running tubecli or uvicorn
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
        $cmdLine = $_.CommandLine
        if ($cmdLine -and ($cmdLine -match "tubecli|uvicorn")) {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killedCount++
        }
    }
} catch {
    # Silently continue if process killing fails
}
if ($killedCount -gt 0) {
    Write-Host "[OK] Killed $killedCount process(es)" -ForegroundColor Green
} else {
    Write-Host "[OK] No running TubeCLI processes found" -ForegroundColor Green
}

if (-not (Check-Python)) {
    if (-not (Install-Python)) {
        Complete-Install -Succeeded:$false
        return
    }
}

if (-not (Check-Git)) {
    if (-not (Install-Git)) {
        Complete-Install -Succeeded:$false
        return
    }
}

Write-Host "[*] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip | Out-Null

$targetDir = ""

# If setup.py exists in current directory, assume local installation
if (Test-Path ".\setup.py") {
    Write-Host "[*] Local setup.py detected, installing from current directory." -ForegroundColor Green
    $targetDir = (Get-Location).Path
} else {
    Write-Host "[*] Cloning TubeCLI repository to $InstallDir..." -ForegroundColor Yellow
    if (-not (Test-Path $InstallDir)) {
        git clone -b $Branch $RepoUrl $InstallDir
    } else {
        Write-Host "  Directory exists, pulling latest changes..." -ForegroundColor Gray
        git -C $InstallDir pull origin $Branch
    }
    $targetDir = $InstallDir
}

Write-Host "[*] Installing TubeCLI (this may take a few minutes)..." -ForegroundColor Yellow
$prevDir = Get-Location
Set-Location $targetDir

try {
    # Install in development mode
    python -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] pip install failed." -ForegroundColor Red
        Set-Location $prevDir
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

if ($tubecliCmd) {
    Write-Host "[OK] TubeCLI installed successfully!" -ForegroundColor Green

    # ── Create Launcher & Shortcuts (BEFORE init, since init blocks) ──
    Write-Host ""
    Write-Host "[*] Creating launcher and shortcuts..." -ForegroundColor Yellow

    # 1. Create TubeCLI.bat launcher in install directory
    $batPath = Join-Path $targetDir "TubeCLI.bat"
    $batContent = @"
@echo off
title TubeCLI - AI Agent System
cd /d "$targetDir"
echo Starting TubeCLI...
start "" /B tubecli api start --quiet
timeout /t 2 /nobreak >nul
start http://localhost:5295/dashboard
tubecli
pause
"@
    Set-Content -Path $batPath -Value $batContent -Encoding ASCII
    Write-Host "  [OK] Created launcher: $batPath" -ForegroundColor Green

    # 2. Create .ico icon for shortcut
    $icoPath = Join-Path $targetDir "tubecli.ico"
    $svgPath = Join-Path $targetDir "tubecli\extensions\webui\static\logo.svg"

    $useDefaultIcon = $true
    if (Test-Path $svgPath) {
        try {
            Add-Type -AssemblyName System.Drawing
            $bmp = New-Object System.Drawing.Bitmap(64, 64)
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $bgBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(30, 30, 46))
            $g.FillEllipse($bgBrush, 2, 2, 60, 60)
            $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(0, 200, 255), 3)
            $g.DrawEllipse($pen, 4, 4, 56, 56)
            $font = New-Object System.Drawing.Font("Segoe UI", 28, [System.Drawing.FontStyle]::Bold)
            $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(0, 200, 255))
            $sf = New-Object System.Drawing.StringFormat
            $sf.Alignment = [System.Drawing.StringAlignment]::Center
            $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
            $rect = New-Object System.Drawing.RectangleF(0, 0, 64, 64)
            $g.DrawString("T", $font, $textBrush, $rect, $sf)
            $g.Dispose()
            $icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
            $fs = [System.IO.FileStream]::new($icoPath, [System.IO.FileMode]::Create)
            $icon.Save($fs)
            $fs.Close()
            $bmp.Dispose()
            $useDefaultIcon = $false
            Write-Host "  [OK] Created icon: $icoPath" -ForegroundColor Green
        } catch {
            Write-Host "  [!] Could not create custom icon, using default" -ForegroundColor Gray
        }
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

    # ── Run init LAST (blocks with interactive menu) ──
    Write-Host "[*] Launching TubeCLI..." -ForegroundColor Yellow
    tubecli init --lang en --port 5295
} else {
    Write-Host "[!] TubeCLI installed, but the 'tubecli' command is not in your PATH." -ForegroundColor Yellow
    Write-Host "Please close this terminal, open a new one, and try running 'tubecli'." -ForegroundColor Yellow
}

Complete-Install -Succeeded:$true
