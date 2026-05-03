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
    Write-Host "[*] Initializing TubeCLI Workspace..." -ForegroundColor Yellow
    try {
        tubecli init --lang en --port 5295
        Write-Host "[OK] Workspace Initialized." -ForegroundColor Green
    } catch {
        Write-Host "[!] Failed to run 'tubecli init'. You may need to run it manually." -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "Installation Complete! You can now use the 'tubecli' command." -ForegroundColor Cyan
    Write-Host "Note: If 'tubecli' is not recognized, please close and reopen your terminal." -ForegroundColor Yellow
} else {
    Write-Host "[!] TubeCLI installed, but the 'tubecli' command is not in your PATH." -ForegroundColor Yellow
    Write-Host "Please close this terminal, open a new one, and try running 'tubecli'." -ForegroundColor Yellow
}

Complete-Install -Succeeded:$true
