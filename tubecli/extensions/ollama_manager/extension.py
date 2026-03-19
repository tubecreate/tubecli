"""
Ollama Manager Extension — Manage local Ollama models and agent assignments.
Provides model listing, pulling, removing, status checks, and agent-model mapping.
"""
import logging
import requests
from typing import Dict, List, Optional
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("OllamaExtension")

OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaModelManager:
    """Wrapper around the Ollama REST API for model management."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, timeout: int = 10) -> dict:
        try:
            resp = requests.get(f"{self.base_url}{path}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            return {"error": f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"}
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path: str, data: dict = None, timeout: int = 300) -> dict:
        try:
            resp = requests.post(f"{self.base_url}{path}", json=data or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError:
            return {"error": f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"}
        except Exception as e:
            return {"error": str(e)}

    def _delete(self, path: str, data: dict = None, timeout: int = 30) -> dict:
        try:
            resp = requests.delete(f"{self.base_url}{path}", json=data or {}, timeout=timeout)
            resp.raise_for_status()
            return {"status": "success"}
        except requests.ConnectionError:
            return {"error": f"Cannot connect to Ollama at {self.base_url}. Is Ollama running?"}
        except Exception as e:
            return {"error": str(e)}

    def is_running(self) -> bool:
        """Check if Ollama server is running."""
        try:
            resp = requests.get(f"{self.base_url}/", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> dict:
        """List all locally available models."""
        result = self._get("/api/tags")
        if "error" in result:
            return result
        models = result.get("models", [])
        return {
            "models": [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "size_human": self._format_size(m.get("size", 0)),
                    "modified_at": m.get("modified_at", ""),
                    "digest": m.get("digest", "")[:12],
                    "details": m.get("details", {}),
                }
                for m in models
            ],
            "count": len(models),
        }

    def list_running(self) -> dict:
        """List currently running/loaded models."""
        result = self._get("/api/ps")
        if "error" in result:
            return result
        models = result.get("models", [])
        return {
            "running": [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "size_human": self._format_size(m.get("size", 0)),
                    "expires_at": m.get("expires_at", ""),
                }
                for m in models
            ],
            "count": len(models),
        }

    def pull_model(self, model_name: str) -> dict:
        """Pull/download a model. Note: this can take a long time for large models."""
        result = self._post("/api/pull", {"name": model_name, "stream": False}, timeout=600)
        if "error" in result:
            return result
        return {"status": "success", "message": f"Model '{model_name}' pulled successfully.", "details": result}

    def remove_model(self, model_name: str) -> dict:
        """Remove a locally stored model."""
        result = self._delete("/api/delete", {"name": model_name})
        if "error" in result:
            return result
        return {"status": "success", "message": f"Model '{model_name}' removed."}

    def show_model(self, model_name: str) -> dict:
        """Show details about a specific model."""
        return self._post("/api/show", {"name": model_name}, timeout=10)

    def server_status(self) -> dict:
        """Get Ollama server status."""
        running = self.is_running()
        result = {
            "running": running,
            "base_url": self.base_url,
        }
        if running:
            models = self.list_models()
            loaded = self.list_running()
            result["model_count"] = models.get("count", 0)
            result["loaded_count"] = loaded.get("count", 0)
        return result

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f}KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / 1024 ** 2:.1f}MB"
        else:
            return f"{size_bytes / 1024 ** 3:.1f}GB"


# Global singleton
ollama_model_manager = OllamaModelManager()


class OllamaExtension(Extension):
    name = "ollama"
    version = "0.1.0"
    description = "Manage local Ollama AI models — list, pull, remove, status, and agent assignment"
    author = "TubeCreate"
    extension_type = "system"

    def get_commands(self):
        from tubecli.extensions.ollama_manager.commands import ollama_group
        return ollama_group

    def get_routes(self):
        from tubecli.extensions.ollama_manager.routes import router
        return router
