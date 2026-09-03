"""Content Video — turn what an agent read and watched into a rendered video, on codex."""
from tubecli.extensions.content_video.extension import (
    ContentVideoExtension, extension_instance,
)

__all__ = ["ContentVideoExtension", "extension_instance"]
