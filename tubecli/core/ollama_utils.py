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
    if os.name != "nt":
        console.print("[yellow]Auto-install is currently only supported on Windows.[/yellow]")
        console.print("Please install Ollama manually from: https://ollama.com/download")
        return False

    installer_url = "https://ollama.com/download/OllamaSetup.exe"
    temp_dir = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
    installer_path = temp_dir / "OllamaSetup.exe"

    try:
        console.print("\n[bold cyan]Downloading OllamaSetup.exe...[/bold cyan]")
        
        # Download with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Downloading...", total=100)
            
            def report(count, block_size, total_size):
                if total_size > 0:
                    progress.update(task, total=total_size, completed=count * block_size)
            
            urllib.request.urlretrieve(installer_url, installer_path, reporthook=report)
        
        console.print("\n[bold green]Download complete. Launching installer...[/bold green]")
        console.print("[yellow]Please follow the standard installer prompts to finish installation.[/yellow]")
        
        # Run installer
        subprocess.run([str(installer_path)], check=True)
        
        console.print("\n[bold green]✅ Ollama installation finished.[/bold green]")
        console.print("[yellow]Note: You might need to restart your terminal for 'ollama' command to be recognized.[/yellow]")
        return True
        
    except Exception as e:
        console.print(f"[bold red]Failed to download or run Ollama installer:[/bold red] {e}")
        console.print("Please install manually from: https://ollama.com/download")
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
    ram_gb = _get_system_ram_gb()
    
    # Base minimal models
    models = [
        {"name": "qwen2.5:0.5b", "desc": "Khoảng 400MB - Cực nhẹ, chạy tốt trên mọi máy", "ram_req": 2},
        {"name": "tinyllama", "desc": "Khoảng 650MB - Rất nhẹ, model 1.1B params", "ram_req": 2},
    ]
    
    # 8GB+ RAM
    if ram_gb >= 6.5:
        models.extend([
            {"name": "deepseek-r1:1.5b", "desc": "Khoảng 1.1GB - Model R1 nhẹ của DeepSeek", "ram_req": 6},
            {"name": "qwen2.5:3b", "desc": "Khoảng 1.9GB - Cân bằng tốc độ và độ thông minh", "ram_req": 8},
            {"name": "llama3.2:3b", "desc": "Khoảng 2.0GB - Model mới của Meta, rất tốt", "ram_req": 8},
        ])
        
    # 16GB+ RAM
    if ram_gb >= 14:
        models.extend([
            {"name": "qwen2.5:7b", "desc": "Khoảng 4.7GB - Cực kỳ thông minh, model mặc định tốt nhất", "ram_req": 16},
            {"name": "llama3.1:8b", "desc": "Khoảng 4.7GB - Standard 8B model của Meta", "ram_req": 16},
            {"name": "deepseek-r1:8b", "desc": "Khoảng 4.9GB - Model R1 mạnh nhưng vẫn nhẹ", "ram_req": 16},
        ])
        
    # 32GB+ RAM
    if ram_gb >= 28:
        models.extend([
            {"name": "qwen2.5:14b", "desc": "Khoảng 9.0GB - Model 14B cực manh mẽ", "ram_req": 32},
            {"name": "deepseek-r1:14b", "desc": "Khoảng 9.0GB - DeepSeek R1 14B", "ram_req": 32},
        ])
        
    return models


def install_model(model_name: str) -> bool:
    """Run ollama pull to download a model."""
    if not is_ollama_installed():
        console.print("[red]Ollama is not installed. Cannot pull model.[/red]")
        return False
        
    console.print(f"\n[bold cyan]Pulling model '{model_name}'... (This may take a while)[/bold cyan]")
    try:
        # Run directly so user sees the native ollama progress bar
        result = subprocess.run(["ollama", "pull", model_name])
        return result.returncode == 0
    except Exception as e:
        console.print(f"[bold red]Failed to pull model:[/bold red] {e}")
        return False
