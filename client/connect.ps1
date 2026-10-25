<#
TubeCLI - Windows bootstrap for the pairing client (25/10/2026).

WHY: the one-line "Connect my computer" command used to download client/tubecli_connect.pyw and run `pythonw`
directly. On a fresh Windows machine there is no Python (or only the Microsoft Store alias), so the line died
with "pythonw is not recognized" before anything happened. This script does what a person would do first:
find a real Python 3.10+, install one when missing, then start the connector with the pairing code.

Usage - exactly what TubeCLI Cloud prints (no file is executed, so the default ExecutionPolicy does not matter):
  powershell -c "&([ScriptBlock]::Create((irm https://raw.githubusercontent.com/tubecreate/tubecli/main/client/connect.ps1))) -Code XXXXXX"
Params:
  -Code       pairing code shown by TubeCLI Cloud (passed through as --code=)
  -GhProxy    mainland China: prefix for GitHub URLs (https://gh-proxy.com/); also exported as TUBECLI_GH_PROXY
  -ClientPath use a local tubecli_connect.pyw instead of downloading (tests, offline)
  -NoInstall  never install Python; fail with a clear message instead
  -DryRun     find/install Python, download the client, print the command - do not start it

Keeps the same search order as install.ps1 (PATH, py launcher, known folders) and the same installers
(winget Python.Python.3.11, then the official python.org installer). PowerShell 5.1 compatible on purpose.
#>
param(
    [string]$Code = "",
    [string]$GhProxy = "",
    [string]$ClientPath = "",
    [switch]$NoInstall,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
$RAW = "https://raw.githubusercontent.com/tubecreate/tubecli/main/"
$PY_VER = "3.11.9"

function Say([string]$Msg, [string]$Color = "Gray") { Write-Host $Msg -ForegroundColor $Color }

# A real CPython >= 3.10 at $Exe? Returns its version string, or $null (the Store alias prints nothing).
function Test-PyExe([string]$Exe) {
    if (-not $Exe) { return $null }
    if ($Exe -match 'WindowsApps') { return $null }
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }
    $v = $null
    try { $v = (& $Exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null | Select-Object -First 1) } catch { $v = $null }
    if ($v -and ("$v" -match '^(\d+)\.(\d+)\.(\d+)')) {
        $major = [int]$matches[1]; $minor = [int]$matches[2]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) { return "$v".Trim() }
    }
    return $null
}

function Find-Python {
    $cands = New-Object System.Collections.ArrayList
    foreach ($n in @("python", "python3")) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c -and $c.Source) { [void]$cands.Add($c.Source) }
    }
    try {
        $p = (& py -3 -c "import sys;print(sys.executable)" 2>$null | Select-Object -First 1)
        if ($p) { [void]$cands.Add("$p".Trim()) }
    } catch {}
    foreach ($ver in @("314", "313", "312", "311", "310")) {
        foreach ($base in @("$env:LOCALAPPDATA\Programs\Python\Python$ver", "$env:ProgramFiles\Python$ver", "${env:ProgramFiles(x86)}\Python$ver", "C:\Python$ver")) {
            if ($base) { [void]$cands.Add((Join-Path $base "python.exe")) }
        }
    }
    foreach ($exe in ($cands | Where-Object { $_ } | Select-Object -Unique)) {
        $v = Test-PyExe $exe
        if ($v) { return @{ exe = $exe; ver = $v } }
    }
    return $null
}

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u;$env:Path"
}

function Install-Python {
    Say "[..] Python 3.10+ not found - installing Python $PY_VER once (a few minutes)" "Yellow"
    $ok = $false
    $w = Get-Command winget -ErrorAction SilentlyContinue
    if ($w) {
        Say "  using winget..." "Gray"
        try {
            winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" | Out-Host
            $ok = ($LASTEXITCODE -eq 0)
        } catch { $ok = $false }
    }
    if (-not $ok) {
        $arch = "amd64"
        if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $arch = "arm64" }
        $url = "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-$arch.exe"
        $f = Join-Path $env:TEMP "python-$PY_VER-$arch.exe"
        Say "  winget not usable - downloading $url" "Gray"
        try {
            Invoke-WebRequest -Uri $url -OutFile $f -UseBasicParsing -ErrorAction Stop
            $p = Start-Process -FilePath $f -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
            $ok = ($p.ExitCode -eq 0)
        } catch { Say "  [!] download/install failed: $($_.Exception.Message)" "Yellow"; $ok = $false }
    }
    Refresh-Path
    return $ok
}

# ── main ─────────────────────────────────────────────────────────────────────
$py = Find-Python
if (-not $py) {
    if ($NoInstall) {
        Say "[X] Python 3.10+ not found and -NoInstall was given." "Red"
        exit 2
    }
    [void](Install-Python)
    $py = Find-Python
    if (-not $py) {
        Say "[X] Python 3.10+ still not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), open a NEW PowerShell window and paste the command again." "Red"
        exit 3
    }
}
Say "[OK] Python $($py.ver) at $($py.exe)" "Green"
$pyw = Join-Path (Split-Path -Parent $py.exe) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pyw)) { $pyw = $py.exe }

if ($ClientPath) {
    $client = $ClientPath
} else {
    $client = Join-Path $env:TEMP "tubecli_connect.pyw"
    $src = "$GhProxy$RAW" + "client/tubecli_connect.pyw"
    Say "[..] downloading $src"
    try { Invoke-WebRequest -Uri $src -OutFile $client -UseBasicParsing -ErrorAction Stop }
    catch { Say "[X] could not download the connector: $($_.Exception.Message)" "Red"; exit 4 }
}
if (-not (Test-Path -LiteralPath $client)) { Say "[X] connector file missing: $client" "Red"; exit 4 }
if ($GhProxy) { $env:TUBECLI_GH_PROXY = $GhProxy }

$cliArgs = @("`"$client`"")
if ($Code) { $cliArgs += "--code=$Code" }
if ($DryRun) {
    Write-Output ("[dry-run] " + $pyw + " " + ($cliArgs -join " "))
    exit 0
}
Say "[..] starting the TubeCLI connector (no window - follow it in TubeCLI Cloud)"
Start-Process -FilePath $pyw -ArgumentList $cliArgs | Out-Null
Say "[OK] Connector started with code $Code." "Green"
