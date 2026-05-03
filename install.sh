#!/bin/bash
set -euo pipefail

# Usage: curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash

REPO_URL="https://github.com/tubecreate/tubecli.git"
BRANCH="main"
INSTALL_DIR="${HOME}/tubecli"

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
    echo "Please install Python 3.9+ and Git manually, then run: pip install -e ."
    exit 1
fi
echo -e "${GREEN}[OK] Detected OS: $OS${NC}"

# --- Helper Functions ---

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# --- Install Dependencies ---

install_deps_linux() {
    if command_exists apt-get; then
        echo -e "${YELLOW}[*] Installing dependencies via apt...${NC}"
        sudo apt-get update -qq
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3 python3-pip python3-venv >/dev/null 2>&1
        return 0
    elif command_exists dnf; then
        echo -e "${YELLOW}[*] Installing dependencies via dnf...${NC}"
        sudo dnf install -y -q git python3 python3-pip >/dev/null 2>&1
        return 0
    elif command_exists yum; then
        echo -e "${YELLOW}[*] Installing dependencies via yum...${NC}"
        sudo yum install -y -q git python3 python3-pip >/dev/null 2>&1
        return 0
    elif command_exists pacman; then
        echo -e "${YELLOW}[*] Installing dependencies via pacman...${NC}"
        sudo pacman -Sy --noconfirm git python python-pip >/dev/null 2>&1
        return 0
    fi
    return 1
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
        # Check version >= 3.9
        local py_version
        py_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        local major
        local minor
        major=$(echo "$py_version" | cut -d. -f1)
        minor=$(echo "$py_version" | cut -d. -f2)
        if [[ "$major" -eq 3 && "$minor" -ge 9 ]]; then
            echo -e "${GREEN}[OK] Python $py_version found${NC}"
            return 0
        fi
    fi
    return 1
}

# Ensure Git and Python
if ! command_exists git || ! check_python; then
    echo -e "${YELLOW}[*] Missing Git or Python 3.9+. Attempting to install...${NC}"
    if [[ "$OS" == "linux" ]]; then
        install_deps_linux || { echo -e "${RED}[!] Failed to install dependencies via package manager.${NC}"; exit 1; }
    elif [[ "$OS" == "macos" ]]; then
        install_deps_macos || { exit 1; }
    fi
    
    # Check again
    if ! command_exists git || ! check_python; then
        echo -e "${RED}[!] Failed to ensure Python 3.9+ and Git are installed.${NC}"
        exit 1
    fi
fi

# --- Install TubeCLI ---

TARGET_DIR=""

if [[ -f "./setup.py" && -d "./tubecli" ]]; then
    echo -e "${GREEN}[*] Local setup.py detected, installing from current directory.${NC}"
    TARGET_DIR="$PWD"
else
    echo -e "${YELLOW}[*] Cloning TubeCLI repository to $INSTALL_DIR...${NC}"
    if [[ ! -d "$INSTALL_DIR" ]]; then
        git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    else
        echo -e "  Directory exists, pulling latest changes..."
        git -C "$INSTALL_DIR" pull origin "$BRANCH"
    fi
    TARGET_DIR="$INSTALL_DIR"
fi

echo -e "${YELLOW}[*] Upgrading pip...${NC}"
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true

echo -e "${YELLOW}[*] Installing TubeCLI (this may take a few minutes)...${NC}"
cd "$TARGET_DIR"

# Install in development mode
if ! python3 -m pip install -e . ; then
    echo -e "${RED}[!] pip install failed.${NC}"
    exit 1
fi

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

# --- Initialize ---

if command_exists tubecli; then
    echo -e "${GREEN}[OK] TubeCLI installed successfully!${NC}"
    echo -e "${YELLOW}[*] Initializing TubeCLI Workspace...${NC}"
    if tubecli init --lang en --port 5295; then
        echo -e "${GREEN}[OK] Workspace Initialized.${NC}"
    else
        echo -e "${YELLOW}[!] Failed to run 'tubecli init'. You may need to run it manually.${NC}"
    fi
    
    echo -e "\n${CYAN}Installation Complete! You can now use the 'tubecli' command.${NC}"
    echo -e "${YELLOW}Note: You may need to restart your terminal or run 'source ~/.bashrc' (or ~/.zshrc) for the 'tubecli' command to be available.${NC}"
else
    echo -e "${YELLOW}[!] TubeCLI installed, but the 'tubecli' command is not in your PATH.${NC}"
    echo -e "${YELLOW}Please restart your terminal or add ~/.local/bin to your PATH manually.${NC}"
fi
