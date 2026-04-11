"""
Channel Cache — Remembers channel lists per provider for index-based selection.

Allows users to say "kênh 2", "kênh thứ 3" instead of remembering channel names.
Persists to disk so memory survives restarts.

Usage:
    from tubecli.core.channel_cache import channel_cache
    channel_cache.save_channels("youtube", channels_list)
    ch = channel_cache.get_by_index("youtube", 2)  # "kênh 2"
    ch = channel_cache.get_last_used("youtube")     # most recent upload target
"""
import json
import os
import re
import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from tubecli.config import DATA_DIR


CACHE_FILE = DATA_DIR / "channel_cache.json"


class ChannelCache:
    """In-memory + file-persisted channel list cache per provider."""

    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def _save(self):
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ChannelCache] Save error: {e}")

    # ── Public API ────────────────────────────────────────────

    def save_channels(self, provider: str, channels: List[Dict], email: str = ""):
        """Cache a channel list (called after list_channels action).
        
        Each channel dict should have: id, title, email, subscribers, url, etc.
        Also records this provider as the 'last listed' for context-aware routing.
        """
        self._cache[provider] = {
            "channels": channels,
            "email": email,
            "updated_at": datetime.datetime.now().isoformat(),
        }
        # Track which provider was listed most recently
        self._cache["_last_listed_provider"] = provider
        self._cache["_last_listed_at"] = datetime.datetime.now().isoformat()
        self._save()
        print(f"[ChannelCache] Saved {len(channels)} {provider} channels (last_listed={provider})")

    def get_channels(self, provider: str) -> List[Dict]:
        """Get cached channel list for a provider."""
        entry = self._cache.get(provider, {})
        return entry.get("channels", [])

    def get_by_index(self, provider: str, index: int) -> Optional[Dict]:
        """Get channel by 1-based index (e.g. 'kênh 2' → index=2)."""
        channels = self.get_channels(provider)
        if 1 <= index <= len(channels):
            return channels[index - 1]
        return None

    def get_by_name(self, provider: str, name: str) -> Optional[Dict]:
        """Find channel by partial name match (case-insensitive)."""
        name_lower = name.lower().strip()
        for ch in self.get_channels(provider):
            ch_title = (ch.get("title") or "").lower()
            if name_lower in ch_title or ch_title in name_lower:
                return ch
        return None

    def get_last_used(self, provider: str) -> Optional[Dict]:
        """Get the most recently used channel for upload."""
        entry = self._cache.get(provider, {})
        last_id = entry.get("last_used_id")
        if last_id:
            for ch in entry.get("channels", []):
                if ch.get("id") == last_id:
                    return ch
        # Fallback: first channel
        channels = entry.get("channels", [])
        return channels[0] if channels else None

    def set_last_used(self, provider: str, channel_id: str):
        """Mark a channel as the most recently used for uploads."""
        if provider not in self._cache:
            self._cache[provider] = {"channels": []}
        self._cache[provider]["last_used_id"] = channel_id
        self._cache[provider]["last_used_at"] = datetime.datetime.now().isoformat()
        self._save()

    def get_last_listed_provider(self) -> Optional[str]:
        """Get the provider that was most recently listed by user.
        
        This is critical for context-aware routing:
        If user just listed Facebook pages then says 'upload lên kênh 1',
        the system should know they mean Facebook, not YouTube.
        
        Returns None if stale (> 30 minutes old) to avoid wrong context.
        """
        provider = self._cache.get("_last_listed_provider")
        listed_at = self._cache.get("_last_listed_at")
        if not provider or not listed_at:
            return None
        
        # Check freshness (30 minute window)
        try:
            listed_time = datetime.datetime.fromisoformat(listed_at)
            now = datetime.datetime.now()
            if (now - listed_time).total_seconds() > 1800:  # 30 minutes
                return None
        except Exception:
            pass
        
        return provider

    def infer_provider(self, user_text: str) -> str:
        """Infer the target provider from user text + context.
        
        Priority:
        1. Explicit keyword: "facebook", "fanpage", "tiktok"
        2. "kênh N" + last listed provider context
        3. Default: "youtube"
        """
        text_lower = user_text.lower()
        
        # 1. Explicit mention
        if any(k in text_lower for k in ["facebook", "fanpage", "fb"]):
            return "facebook"
        if "tiktok" in text_lower:
            return "tiktok"
        if any(k in text_lower for k in ["youtube", "yt"]):
            return "youtube"
        
        # 2. "kênh N" without provider → use last listed context
        has_channel_index = bool(re.search(r'(?:kênh|channel)\s*(?:thứ\s*)?(\d+)', text_lower))
        if has_channel_index:
            last_listed = self.get_last_listed_provider()
            if last_listed:
                print(f"[ChannelCache] Inferred provider={last_listed} from last listed context")
                return last_listed
        
        # 3. Default
        return "youtube"

    def resolve_channel(self, provider: str, user_text: str) -> Optional[Dict]:
        """Smart resolve: try index first, then name, then last-used.
        
        Supports:
        - "kênh 2", "kênh thứ 3", "channel 1"
        - "kênh ABC" (partial name match)
        - No specific mention → last used channel
        """
        text_lower = user_text.lower()
        
        # 1. Try index: "kênh 2", "kênh thứ 3", "channel 1", "số 2"
        idx_match = re.search(r'(?:kênh|channel|số)\s*(?:thứ\s*)?(\d+)', text_lower)
        if idx_match:
            idx = int(idx_match.group(1))
            ch = self.get_by_index(provider, idx)
            if ch:
                return ch
        
        # 2. Try name: "kênh ABC XYZ"
        name_match = re.search(r'(?:kênh|channel|page|fanpage|trang)\s+(?:youtube\s+|facebook\s+)?([^\d].+?)(?:\s+giúp|\s+video|\s*$)', text_lower)
        if name_match:
            name = name_match.group(1).strip()
            if name and not name.isdigit():
                ch = self.get_by_name(provider, name)
                if ch:
                    return ch
        
        # 3. Fallback: last used
        return self.get_last_used(provider)


# Global singleton
channel_cache = ChannelCache()
