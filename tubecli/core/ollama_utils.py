"""
Ollama Utilities
Helpers for detecting, installing, and managing Ollama models.
"""
import os
import sys
import json
import shutil
import urllib.request
import subprocess
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn

console = Console()

def is_ollama_installed() -> bool:
    """Check if 'ollama' is in the system PATH."""
    return shutil.which('ollama') is not None


def install_ollama():
    """Download and run the official Windows Ollama installer."""
    from tubecli.i18n import t

    if os.name != "nt":
        console.print(t("ollama.auto_install_windows_only"))
        console.print(t("ollama.manual_install"))
        return False

    installer_url = "https://ollama.com/download/OllamaSetup.exe"
    temp_dir = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
    installer_path = temp_dir / "OllamaSetup.exe"

    try:
        console.print(t("ollama.downloading"))
        
        # Download with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console
        ) as progress:
            task = progress.add_task(t("ollama.download_progress"), total=100)
            
            def report(count, block_size, total_size):
                if total_size > 0:
                    progress.update(task, total=total_size, completed=count * block_size)
            
            urllib.request.urlretrieve(installer_url, installer_path, reporthook=report)
        
        console.print(t("ollama.download_complete"))
        console.print(t("ollama.follow_prompts"))
        
        # Run installer
        subprocess.run([str(installer_path)], check=True)
        
        console.print(t("ollama.install_finished"))
        console.print(t("ollama.restart_note"))
        return True
        
    except Exception as e:
        console.print(t("ollama.install_failed", error=e))
        console.print(t("ollama.install_manual"))
        return False


def get_installed_models() -> list:
    """Run 'ollama list' and parse the output to get installed models."""
    if not is_ollama_installed():
        return []
        
    try:
        result = subprocess.run(
            ['ollama', 'list'], 
            capture_output=True, 
            text=True,
            check=False
        )
        if result.returncode != 0:
            return []
            
        models = []
        lines = result.stdout.strip().split('\n')
        # Skip header line
        for line in lines[1:]:
            parts = line.split()
            if parts:
                model_name = parts[0]
                models.append(model_name)
        return models
    except Exception:
        return []


def _get_system_ram_gb() -> float:
    """Get system RAM in GB (Windows primary support)."""
    try:
        if os.name == 'nt':
            # Use wmic to get total physical memory
            result = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"], 
                capture_output=True, text=True, check=False
            )
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                bytes_ram = int(lines[1].strip())
                return bytes_ram / (1024**3)
    except Exception:
        pass
    
    # Fallback to os module if possible, or just assume 8GB
    return 8.0


def get_recommended_models() -> list:
    """Return a list of dicts with model recommendations based on RAM."""
    from tubecli.i18n import t
    ram_gb = _get_system_ram_gb()
    
    # Base minimal models
    models = [
        {"name": "qwen2.5:0.5b", "desc": t("model.qwen_05b"), "ram_req": 2},
        {"name": "tinyllama", "desc": t("model.tinyllama"), "ram_req": 2},
    ]
    
    # 8GB+ RAM
    if ram_gb >= 6.5:
        models.extend([
            {"name": "deepseek-r1:1.5b", "desc": t("model.deepseek_15b"), "ram_req": 6},
            {"name": "qwen2.5:3b", "desc": t("model.qwen_3b"), "ram_req": 8},
            {"name": "llama3.2:3b", "desc": t("model.llama32_3b"), "ram_req": 8},
        ])
        
    # 16GB+ RAM
    if ram_gb >= 14:
        models.extend([
            {"name": "qwen2.5:7b", "desc": t("model.qwen_7b"), "ram_req": 16},
            {"name": "llama3.1:8b", "desc": t("model.llama31_8b"), "ram_req": 16},
            {"name": "deepseek-r1:8b", "desc": t("model.deepseek_8b"), "ram_req": 16},
        ])
        
    # 32GB+ RAM
    if ram_gb >= 28:
        models.extend([
            {"name": "qwen2.5:14b", "desc": t("model.qwen_14b"), "ram_req": 32},
            {"name": "deepseek-r1:14b", "desc": t("model.deepseek_14b"), "ram_req": 32},
        ])
        
    return models


def install_model(model_name: str) -> bool:
    """Run ollama pull to download a model."""
    from tubecli.i18n import t

    if not is_ollama_installed():
        console.print(t("ollama.not_installed"))
        return False
        
    console.print(t("ollama.pulling", name=model_name))
    try:
        # Run directly so user sees the native ollama progress bar
        result = subprocess.run(["ollama", "pull", model_name])
        
        if result.returncode != 0:
            console.print(t("ollama.pull_failed", name=model_name))
            console.print(t("ollama.pull_hint"))
            return False
            
        return True
    except Exception as e:
        console.print(t("ollama.pull_error", error=e))
        return False
