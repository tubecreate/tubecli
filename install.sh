#!/bin/bash
set -euo pipefail

# Usage: curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash

# Overridable so a fork, a mirror, an air-gapped copy or a test harness can point
# this at another source without editing the script.
REPO_URL="${TUBECLI_REPO_URL:-https://github.com/tubecreate/tubecli.git}"
BRANCH="${TUBECLI_BRANCH:-main}"
INSTALL_DIR="${TUBECLI_INSTALL_DIR:-${HOME}/tubecli}"
LANG_VAL="en"
# LANG_EXPLICIT: pass --lang through to `tubecli init` only when the user chose
# one. Passing the default unconditionally would overwrite the language a user
# picked earlier every time they re-run this script to update.
LANG_EXPLICIT=0
# NONINTERACTIVE: skip every keyboard prompt - for automated/headless installs
# (e.g. provisioning scripts). Also settable via TUBECLI_NONINTERACTIVE=1.
NONINTERACTIVE="${TUBECLI_NONINTERACTIVE:-0}"
# Mirror of tubecli.config.SUPPORTED_LANGUAGES — validated here so a typo fails
# in one second instead of after a full install.
SUPPORTED_LANGS="zh zh-TW vi en ja ko es tr ru"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      LANG_VAL="$2"
      LANG_EXPLICIT=1
      shift 2
      ;;
    --non-interactive|--noninteractive|--unattended|--yes|-y)
      NONINTERACTIVE=1
      shift
      ;;
    *)
      if [[ "$1" =~ ^[a-zA-Z-]{2,5}$ ]]; then
        LANG_VAL="$1"
        LANG_EXPLICIT=1
      fi
      shift
      ;;
  esac
done

# Validate now, not after a full install. An unsupported code used to travel all
# the way to `tubecli init --lang`, which rejects it with a click error long after
# the installer has finished printing success.
case " $SUPPORTED_LANGS " in
  *" $LANG_VAL "*) ;;
  *)
    echo "[!] Unsupported language '$LANG_VAL'. Choose one of: $SUPPORTED_LANGS" >&2
    exit 2
    ;;
esac

BOLD='\033[1m'
CYAN='\033[38;5;51m'
GREEN='\033[38;5;46m'
YELLOW='\033[38;5;226m'
RED='\033[38;5;196m'
NC='\033[0m'

echo -e "\n${CYAN}${BOLD}  TubeCLI Installer${NC}"
echo -e "${CYAN}${BOLD}  =================${NC}\n"

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]] || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
    OS="linux"
fi

if [[ "$OS" == "unknown" ]]; then
    echo -e "${RED}[!] Unsupported operating system: $OSTYPE${NC}"
    echo "Please install Python 3.10+ and Git manually, then run: pip install -e ."
    exit 1
fi
echo -e "${GREEN}[OK] Detected OS: $OS${NC}"

# --- Helper Functions ---

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# --- Install Dependencies ---

# Prefix sudo only when it is both needed and available. Every call below used to
# hardcode it, so inside a container — where the user is already root and sudo is
# usually not installed — each one failed with "sudo: command not found".
SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command_exists sudo; then
    SUDO="sudo"
fi

# Install the named packages with whatever package manager exists.
# Returns non-zero if there is no package manager, or if it genuinely failed.
install_system_packages() {
    local rc=0
    if command_exists apt-get; then
        echo -e "${YELLOW}[*] Installing $* via apt...${NC}"
        $SUDO apt-get update -qq || rc=$?
        # -q, not -qq: -qq prints nothing at all, so a multi-minute download looked
        # like the installer had frozen. -q keeps the per-package lines without the
        # terminal-control progress bar.
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@" || rc=$?
    elif command_exists dnf; then
        echo -e "${YELLOW}[*] Installing $* via dnf...${NC}"
        $SUDO dnf install -y -q "$@" || rc=$?
    elif command_exists yum; then
        echo -e "${YELLOW}[*] Installing $* via yum...${NC}"
        $SUDO yum install -y -q "$@" || rc=$?
    elif command_exists pacman; then
        echo -e "${YELLOW}[*] Installing $* via pacman...${NC}"
        $SUDO pacman -Sy --noconfirm "$@" || rc=$?
    elif command_exists zypper; then
        echo -e "${YELLOW}[*] Installing $* via zypper...${NC}"
        $SUDO zypper --non-interactive install "$@" || rc=$?
    elif command_exists apk; then
        echo -e "${YELLOW}[*] Installing $* via apk...${NC}"
        $SUDO apk add --quiet "$@" || rc=$?
    else
        return 1
    fi
    return $rc
}

# Package names differ per distribution; venv is only a separate package on Debian
# and openSUSE.
python_packages() {
    # unzip is not optional: the browser engine archive can only be extracted with
    # it (Python's zipfile loses symlinks and exec bits), and discovering that
    # after a 200 MB download is a bad way to find out.
    if command_exists apt-get;   then echo "python3 python3-pip python3-venv unzip"
    elif command_exists zypper;  then echo "python3 python3-pip python3-virtualenv unzip"
    elif command_exists pacman;  then echo "python python-pip unzip"
    elif command_exists apk;     then echo "python3 py3-pip unzip"
    else                              echo "python3 python3-pip unzip"   # dnf / yum
    fi
}

install_deps_linux() {
    # Previously every branch ended in an unconditional `return 0` with output sent
    # to /dev/null, so a package manager that failed — no network, no sudo, locked
    # dpkg — was reported as success and the script carried on. Let the real status
    # through, and stop hiding the errors that explain it.
    # shellcheck disable=SC2046
    install_system_packages git $(python_packages)
}

install_deps_macos() {
    if command_exists brew; then
        echo -e "${YELLOW}[*] Installing dependencies via Homebrew...${NC}"
        brew install git python >/dev/null 2>&1
        return 0
    else
        echo -e "${RED}[!] Homebrew is not installed. Please install Homebrew first:${NC}"
        echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        exit 1
    fi
}

check_python() {
    if command_exists python3; then
        # Check version >= 3.10
        local py_version
        py_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        local major
        local minor
        major=$(echo "$py_version" | cut -d. -f1)
        minor=$(echo "$py_version" | cut -d. -f2)
        # Must match requires-python in pyproject.toml (>=3.10). Accepting 3.9
        # here printed a green [OK] and then let pip refuse the package, and
        # because this check "passed" the brew/apt rescue path below never ran.
        if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then
            echo -e "${GREEN}[OK] Python $py_version found${NC}"
            return 0
        fi
        echo -e "${YELLOW}[!] Python $py_version found, but TubeCLI needs 3.10 or newer.${NC}"
    fi
    return 1
}

# Ensure Git and Python
if ! command_exists git || ! check_python; then
    echo -e "${YELLOW}[*] Missing Git or Python 3.10+. Attempting to install...${NC}"
    if [[ "$OS" == "linux" ]]; then
        install_deps_linux || { echo -e "${RED}[!] Failed to install dependencies via package manager.${NC}"; exit 1; }
    elif [[ "$OS" == "macos" ]]; then
        install_deps_macos || { exit 1; }
    fi
    
    # Check again
    if ! command_exists git || ! check_python; then
        echo -e "${RED}[!] Failed to ensure Python 3.10+ and Git are installed.${NC}"
        exit 1
    fi
fi

# Having python3 does not mean having pip or venv. Debian and Ubuntu ship them as
# separate packages, so a container base image or a minimal server passes the check
# above and then dies on the install command with a message about neither. Ask for
# them by name here, while we can still say which package to install.
missing_pip_venv() {
    local missing=()
    python3 -m pip --version >/dev/null 2>&1 || missing+=("pip")
    python3 -m venv --help  >/dev/null 2>&1 || missing+=("venv")
    echo "${missing[@]:-}"
}

check_pip_and_venv() {
    local missing names verb
    missing=$(missing_pip_venv)
    [[ -z "$missing" ]] && return 0

    names=$(echo "$missing" | sed 's/ / and /')
    [[ "$missing" == *" "* ]] && verb="are" || verb="is"
    echo -e "${YELLOW}[!] Python is installed, but $names $verb not available.${NC}"

    # Install it rather than telling the user to. This script already installs
    # system packages when Python or Git are missing; it just never reached that
    # code when they were present, which is the common case — a distro image with
    # python3 but no pip. Printing "install this, then run me again" made the user
    # do by hand what the installer was already equipped to do.
    if install_system_packages $(python_packages); then
        missing=$(missing_pip_venv)
        if [[ -z "$missing" ]]; then
            echo -e "${GREEN}[OK] pip and venv are now available.${NC}"
            return 0
        fi
    fi

    # Automatic install did not work; say exactly what to run. sudo is prefixed only
    # when the user is not root and sudo exists, because inside a container a copied
    # "sudo apt install ..." answers "sudo: command not found".
    local pfx=""
    [[ -n "$SUDO" ]] && pfx="$SUDO "
    echo -e "${RED}[!] Could not install them automatically.${NC}"
    if command_exists apt-get; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}apt-get update && ${pfx}apt-get install -y python3-pip python3-venv"
    elif command_exists dnf; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}dnf install -y python3-pip"
    elif command_exists yum; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}yum install -y python3-pip"
    elif command_exists pacman; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}pacman -Sy --noconfirm python-pip"
    elif command_exists zypper; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}zypper install -y python3-pip python3-virtualenv"
    elif command_exists apk; then
        echo -e "${YELLOW}    Run:${NC} ${pfx}apk add py3-pip"
    elif command_exists brew; then
        echo -e "${YELLOW}    Run:${NC} brew install python"
    else
        echo -e "${YELLOW}    Install your distribution's python3-pip and python3-venv packages,${NC}"
        echo -e "${YELLOW}    or try:${NC} python3 -m ensurepip --upgrade"
    fi
    echo -e "${YELLOW}    The errors above say why it failed. Then run this installer again.${NC}"
    return 1
}

check_pip_and_venv || exit 1

# Node is optional — only browser automation and the website deploy runner need it —
# but install.ps1 installs it on Windows while this script never did, so Linux users
# always landed in the control panel with browser automation broken. Best effort,
# never fatal.
NODE_MIN_MAJOR=20

node_major() {
    command_exists node || { echo 0; return; }
    node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1
}

check_node() {
    # A version check, not just a presence check. Debian 12 packages Node 18 while
    # Playwright requires 20 or newer, so `apt install nodejs` satisfied
    # command_exists and then the browser engine refused to start with
    # "Playwright requires Node.js 20 or higher" — a failure that only showed up
    # deep inside the preview server's own log.
    local have
    have=$(node_major)
    if [[ "$have" -ge "$NODE_MIN_MAJOR" ]] && command_exists npm; then
        echo -e "${GREEN}[OK] Node.js v$(node -v | sed 's/^v//') found${NC}"
        return 0
    fi
    if [[ "$have" -gt 0 && "$have" -lt "$NODE_MIN_MAJOR" ]]; then
        echo -e "${YELLOW}[!] Node.js v${have} is installed, but browser automation needs ${NODE_MIN_MAJOR}+.${NC}"
        # The distribution package is the old one, so installing from NodeSource is
        # the only way to satisfy this on Debian/Ubuntu stable.
        if command_exists curl && command_exists apt-get; then
            echo -e "${YELLOW}[*] Installing Node.js ${NODE_MIN_MAJOR}.x from NodeSource...${NC}"
            if curl -fsSL "https://deb.nodesource.com/setup_${NODE_MIN_MAJOR}.x" -o /tmp/nodesource_setup.sh; then
                $SUDO bash /tmp/nodesource_setup.sh >/dev/null 2>&1 || true
                rm -f /tmp/nodesource_setup.sh
                install_system_packages nodejs || true
            fi
        fi
        have=$(node_major)
        if [[ "$have" -ge "$NODE_MIN_MAJOR" ]]; then
            echo -e "${GREEN}[OK] Node.js v$(node -v | sed 's/^v//') installed${NC}"
        else
            echo -e "${YELLOW}[!] Still on Node.js v${have}. TubeCLI works, but browser${NC}"
            echo -e "${YELLOW}    automation stays off until Node ${NODE_MIN_MAJOR}+ is installed:${NC}"
            echo -e "${YELLOW}    https://github.com/nodesource/distributions${NC}"
        fi
        return 0
    fi

    echo -e "${YELLOW}[*] Node.js not found. It is only needed for browser automation${NC}"
    echo -e "${YELLOW}    and website deployment; installing it now (optional).${NC}"
    echo -e "${YELLOW}    This downloads ~100 MB and can take a few minutes.${NC}"
    # Prefer NodeSource on Debian/Ubuntu: their own package is Node 18, which
    # Playwright rejects, so installing it would only lead back here.
    if command_exists curl && command_exists apt-get; then
        echo -e "${YELLOW}[*] Installing Node.js ${NODE_MIN_MAJOR}.x from NodeSource...${NC}"
        if curl -fsSL "https://deb.nodesource.com/setup_${NODE_MIN_MAJOR}.x" -o /tmp/nodesource_setup.sh; then
            $SUDO bash /tmp/nodesource_setup.sh >/dev/null 2>&1 || true
            rm -f /tmp/nodesource_setup.sh
        fi
        install_system_packages nodejs || true
    elif command_exists apt-get || command_exists dnf || command_exists yum \
       || command_exists pacman || command_exists zypper || command_exists apk; then
        # Output deliberately NOT sent to /dev/null. Suppressing it left the
        # installer sitting silent for minutes on a large download, which reads as
        # a hang — the user cannot tell progress from a freeze.
        if command_exists apk; then
            install_system_packages nodejs npm || true
        else
            install_system_packages nodejs npm || install_system_packages nodejs || true
        fi
    fi

    have=$(node_major)
    if [[ "$have" -ge "$NODE_MIN_MAJOR" ]]; then
        echo -e "${GREEN}[OK] Node.js v$(node -v | sed 's/^v//') installed${NC}"
    elif [[ "$have" -gt 0 ]]; then
        echo -e "${YELLOW}[!] Installed Node.js v${have}, but browser automation needs ${NODE_MIN_MAJOR}+.${NC}"
        echo -e "${YELLOW}    Everything else works. See https://github.com/nodesource/distributions${NC}"
    else
        echo -e "${YELLOW}[!] Could not install Node.js. TubeCLI will still work;${NC}"
        echo -e "${YELLOW}    browser automation stays off until you install it from https://nodejs.org${NC}"
    fi
}

check_node

# --- Install TubeCLI ---

TARGET_DIR=""

# This tested ./setup.py, which this project does not have (it is pyproject-only),
# so the branch was dead: running the installer from inside a checkout cloned a
# second copy into ~/tubecli and installed that one instead. Check for the manifest
# that actually exists, and confirm it is TubeCLI rather than whatever project the
# user happened to be standing in.
if [[ -d "./tubecli" ]] && { [[ -f "./pyproject.toml" ]] || [[ -f "./setup.py" ]]; } \
   && grep -q '^name = "tubecli"' ./pyproject.toml 2>/dev/null; then
    echo -e "${GREEN}[*] TubeCLI source detected here, installing from the current directory.${NC}"
    TARGET_DIR="$PWD"
else
    echo -e "${YELLOW}[*] Cloning TubeCLI repository to $INSTALL_DIR...${NC}"
    if [[ ! -d "$INSTALL_DIR" ]]; then
        git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    else
        echo -e "  Directory exists, pulling latest changes..."
        # --ff-only under set +e: a dirty or diverged checkout must degrade to a
        # warning, not abort the whole script under `set -e` — re-running this
        # installer IS the advertised update path, and an installed machine must
        # never be brickable by its own checkout state.
        set +e
        git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
        PULL_RC=$?
        set -e
        if [[ "$PULL_RC" -ne 0 ]]; then
            echo -e "${YELLOW}[!] Could not update $INSTALL_DIR (local changes or diverged history).${NC}"
            echo -e "${YELLOW}    Continuing with the existing copy. To update by hand:${NC}"
            echo -e "      git -C $INSTALL_DIR stash && git -C $INSTALL_DIR pull"
            # Carried through to the final summary, which otherwise announces a
            # successful update minutes after this warning has scrolled away.
            export TUBECLI_UPDATE_STATUS="stale"
        fi
    fi
    TARGET_DIR="$INSTALL_DIR"
fi

echo -e "${YELLOW}[*] Upgrading pip...${NC}"
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true

echo -e "${YELLOW}[*] Installing TubeCLI (this may take a few minutes)...${NC}"
cd "$TARGET_DIR"

# Install in development mode.
#
# The plain call is kept as the first attempt so machines where it already works
# keep behaving exactly as before. What is new is the fallback: on Debian 12+,
# Ubuntu 23.04+ and Homebrew Python, pip refuses to touch the system interpreter
# (PEP 668, "externally-managed-environment"). This script used to print
# "pip install failed." and exit 1 there, which is every one of those users, and
# on macOS the brew branch above installs the very interpreter that then refuses.
# A venv from a previous run means the PEP 668 dance already happened — going
# through the system-pip attempt again just prints a screenful of expected
# errors that reads as breakage on every update.
if [[ -x "$TARGET_DIR/.venv/bin/python" ]]; then
    echo -e "  Existing virtualenv found, installing into it."
    "$TARGET_DIR/.venv/bin/python" -m pip install -e . || {
        echo -e "${RED}[!] pip install failed inside the existing virtualenv.${NC}"
        exit 1
    }
    PIP_RC=0
    SKIP_SYSTEM_PIP=1
else
    SKIP_SYSTEM_PIP=0
fi

PIP_LOG="$(mktemp 2>/dev/null || echo /tmp/tubecli-pip.log)"
if [[ "$SKIP_SYSTEM_PIP" -eq 0 ]]; then
    # `set +e` around this on purpose. The script runs under `set -euo pipefail`
    # (line 2), so a failing pip would abort right here and none of the recovery below
    # would ever run — the user would just get a silent exit 1.
    set +e
    python3 -m pip install -e . 2>&1 | tee "$PIP_LOG"
    # PIPESTATUS[0], not $?: the exit status of a pipeline is tee's, which is always 0,
    # so testing $? here would treat every pip failure as a success. (And guarding
    # the pipeline itself with `[[ ]] &&` would make PIPESTATUS the guard's — the
    # first draft of this skip did exactly that and turned skip into failure.)
    PIP_RC=${PIPESTATUS[0]}
    set -e
fi
if [[ "$PIP_RC" -eq 0 ]]; then
    :
elif grep -q "externally-managed-environment" "$PIP_LOG"; then
    echo -e "${YELLOW}[!] This Python is managed by your OS and will not accept packages directly.${NC}"
    echo -e "${YELLOW}[*] Installing into a private virtualenv instead...${NC}"
    if ! python3 -m venv "$TARGET_DIR/.venv"; then
        echo -e "${RED}[!] Could not create a virtualenv.${NC}"
        echo -e "${YELLOW}    Install the venv package first, then re-run this script:${NC}"
        echo -e "      sudo apt install python3-venv     ${YELLOW}# Debian/Ubuntu${NC}"
        exit 1
    fi
    "$TARGET_DIR/.venv/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
    if ! "$TARGET_DIR/.venv/bin/python" -m pip install -e . ; then
        echo -e "${RED}[!] pip install failed inside the virtualenv too.${NC}"
        exit 1
    fi
    # Put a launcher on PATH so `tubecli` works without activating anything.
    mkdir -p "$HOME/.local/bin"
    printf '#!/bin/sh\nexec "%s/.venv/bin/tubecli" "$@"\n' "$TARGET_DIR" > "$HOME/.local/bin/tubecli"
    chmod +x "$HOME/.local/bin/tubecli"
    echo -e "${GREEN}[OK] Installed in $TARGET_DIR/.venv (launcher: ~/.local/bin/tubecli)${NC}"
else
    echo -e "${RED}[!] pip install failed. Full output above; log kept at $PIP_LOG${NC}"
    exit 1
fi
rm -f "$PIP_LOG" 2>/dev/null || true

# --- Ensure PATH ---

LOCAL_BIN="$HOME/.local/bin"
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo -e "${YELLOW}[!] Adding $LOCAL_BIN to PATH...${NC}"
    export PATH="$LOCAL_BIN:$PATH"
    
    # Try to add to profile
    PROFILE_FILE=""
    if [[ -f "$HOME/.zshrc" ]]; then
        PROFILE_FILE="$HOME/.zshrc"
    elif [[ -f "$HOME/.bashrc" ]]; then
        PROFILE_FILE="$HOME/.bashrc"
    elif [[ -f "$HOME/.profile" ]]; then
        PROFILE_FILE="$HOME/.profile"
    fi
    
    if [[ -n "$PROFILE_FILE" ]]; then
        if ! grep -q "$LOCAL_BIN" "$PROFILE_FILE"; then
            echo -e "\nexport PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$PROFILE_FILE"
            echo -e "${GREEN}[OK] Added ~/.local/bin to $PROFILE_FILE${NC}"
        fi
    fi
fi

# The profile edit only helps future shells, and `curl | bash` runs the installer
# in a subshell so the export above never reaches the caller's shell either — the
# first thing users hit after a successful install was "tubecli: command not
# found". When /usr/local/bin is writable it is already on PATH everywhere, so a
# link there makes the command work immediately, in this shell and in any other.
if [[ -w /usr/local/bin ]] || [[ "$(id -u)" -eq 0 ]]; then
    TUBECLI_BIN=""
    for cand in "$LOCAL_BIN/tubecli" "$TARGET_DIR/.venv/bin/tubecli" "$(command -v tubecli 2>/dev/null)"; do
        if [[ -n "$cand" && -x "$cand" && "$cand" != "/usr/local/bin/tubecli" ]]; then
            TUBECLI_BIN="$cand"
            break
        fi
    done
    if [[ -n "$TUBECLI_BIN" ]]; then
        ln -sf "$TUBECLI_BIN" /usr/local/bin/tubecli 2>/dev/null \
            && echo -e "${GREEN}[OK] Linked tubecli into /usr/local/bin${NC}"
    fi
fi

# --- The interpreter that owns this install ---
#
# ABSOLUTE path, resolved once. Two layouts exist in the wild: the venv from the
# PEP 668 fallback, and a conda/system python where pip installed directly (the
# project's own server runs miniconda). The absolute path matters because Phase B
# runs this interpreter under sudo, and sudo resets PATH to secure_path — a bare
# `python3` would silently become /usr/bin/python3, which does not have tubecli,
# and the library check would report success while checking nothing.
if [[ -x "$TARGET_DIR/.venv/bin/python" ]]; then
    PYEXE="$TARGET_DIR/.venv/bin/python"
else
    PYEXE="$(command -v python3)"
fi

# --- Browser runtime libraries (Linux only) ---
#
# Installed HERE because install time is the only reliably privileged moment.
# The runtime preflight can only fix this with passwordless sudo, which a normal
# VPS user does not have — deferring means browser automation stays broken under
# the systemd service forever. The ~200MB Chromium engine itself is NOT
# downloaded here: it installs unprivileged on first browser use, so a box that
# never uses browser automation never pays for it. TUBECLI_MINIMAL=1 skips.
if [[ "$OS" == "linux" && -z "${TUBECLI_MINIMAL:-}" ]]; then
    MISS="$("$PYEXE" -c 'from tubecli.extensions.browser.shardx_runtime import missing_linux_libraries; print(len(missing_linux_libraries()))' 2>/dev/null | tail -n1)"
    if [[ "$MISS" =~ ^[0-9]+$ && "$MISS" -gt 0 ]]; then
        echo -e "${YELLOW}[*] Installing $MISS browser runtime libraries (this can take a few minutes)...${NC}"
        $SUDO "$PYEXE" -c 'from tubecli.extensions.browser.shardx_runtime import install_chromium_libs; install_chromium_libs()' || true
        LEFT="$("$PYEXE" -c 'from tubecli.extensions.browser.shardx_runtime import missing_linux_libraries; print(len(missing_linux_libraries()))' 2>/dev/null | tail -n1)"
        if [[ "$LEFT" =~ ^[0-9]+$ && "$LEFT" -gt 0 ]]; then
            echo -e "${YELLOW}[!] $LEFT libraries could not be installed — browser automation stays off until they are.${NC}"
            echo -e "${YELLOW}    The dashboard's Browser Engines page shows the exact command.${NC}"
        else
            echo -e "${GREEN}[OK] Browser runtime libraries present.${NC}"
        fi
    fi
fi

# --- Initialize ---

if command_exists tubecli; then
    echo -e "${GREEN}[OK] TubeCLI installed successfully!${NC}"

    # Which ending? A headless machine (VPS, container) gets the server finisher:
    # password, systemd service, summary-with-URL, exit. A desktop gets the
    # interactive control panel, exactly as before. Python owns the detection —
    # bash does not read DISPLAY itself. Decided by EXIT CODE, not stdout: any
    # stray print inside the import chain would corrupt a captured value, and a
    # probe that cannot run at all defaults to the server path (the primary Linux
    # case, and the one that is safe without a terminal).
    HEADLESS=1
    if [[ "$OS" == "linux" ]]; then
        if "$PYEXE" -c 'import sys; from tubecli.cli.init_cmd import _is_headless_server, _in_container; sys.exit(3 if not (_is_headless_server() or _in_container()) else 0)' 2>/dev/null; then
            HEADLESS=1
        elif [[ $? -eq 3 ]]; then
            HEADLESS=0
        fi
    else
        HEADLESS=0                     # macOS: always the desktop path
    fi

    INIT_ARGS=()
    [[ "$HEADLESS" -eq 1 ]] && INIT_ARGS+=("--server")
    # --lang only when the user chose one; --port never (it used to be forced to
    # 5295 on every run, resetting any port the user had changed).
    [[ "$LANG_EXPLICIT" -eq 1 ]] && INIT_ARGS+=("--lang" "$LANG_VAL")

    # `tubecli init` reads the keyboard. Under `curl | bash` stdin is the script
    # itself, so read /dev/tty directly; with no terminal at all, run it anyway —
    # the server path is designed to complete without one (and says what it kept).
    TTY_IN=""
    if [[ "$NONINTERACTIVE" == "1" ]]; then
        TTY_IN=""                      # forced: never read a keyboard prompt
    elif [[ -t 0 ]]; then
        TTY_IN=""                      # stdin already is the terminal
    elif (exec 3</dev/tty) 2>/dev/null; then
        TTY_IN="/dev/tty"
    fi

    set +e
    # ${INIT_ARGS[@]+...}: expanding an EMPTY array with plain "${INIT_ARGS[@]}"
    # is an "unbound variable" error under `set -u` on bash 3.2 — which is what
    # macOS ships, and macOS with no --lang reaches here with the array empty.
    if [[ "$NONINTERACTIVE" != "1" && -n "$TTY_IN" ]]; then
        tubecli init ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} < "$TTY_IN"
    elif [[ -t 0 || "$HEADLESS" -eq 1 || "$NONINTERACTIVE" == "1" ]]; then
        tubecli init ${INIT_ARGS[@]+"${INIT_ARGS[@]}"} </dev/null
    else
        # Desktop with no terminal: the interactive panel cannot run.
        echo -e "${YELLOW}[!] No terminal available, so interactive setup was skipped.${NC}"
        echo -e "${YELLOW}    Finish setup yourself with:  tubecli init${NC}"
        false
    fi
    INIT_RC=$?
    set -e

    if [[ "$INIT_RC" -ne 0 && "$HEADLESS" -eq 1 ]]; then
        # Print a path that works in THIS shell: the bare name may only exist in
        # future shells (PATH edit) — that trap is why `sudo tubecli` failed for
        # the first user of the service command.
        TUBECLI_CMD="tubecli"
        [[ -x "$HOME/.local/bin/tubecli" ]] && TUBECLI_CMD="$HOME/.local/bin/tubecli"
        echo -e "${YELLOW}[!] Server setup did not finish. Complete it with:${NC}"
        echo -e "      $TUBECLI_CMD init --server"
    fi
    # No hardcoded loopback dashboard URL here any more. On a server that URL
    # was wrong for the only browser the user has (their laptop's), and the old
    # "start it with the api command" advice described a foreground process that
    # dies with the SSH session. The finisher's summary — or `tubecli info` at
    # any later moment — is the authoritative version of this information.
else
    echo -e "${YELLOW}[!] TubeCLI installed, but the 'tubecli' command is not in your PATH.${NC}"
    echo -e "${YELLOW}Please restart your terminal or add ~/.local/bin to your PATH manually.${NC}"
    echo -e "${YELLOW}Then finish setup with:  tubecli init${NC}"
fi
