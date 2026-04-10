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
        """
        self._cache[provider] = {
            "channels": channels,
            "email": email,
            "updated_at": datetime.datetime.now().isoformat(),
        }
        self._save()
        print(f"[ChannelCache] Saved {len(channels)} {provider} channels")

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

    def format_channel_list(self, provider: str) -> str:
        """Format cached channel list with numbered indices for display."""
        channels = self.get_channels(provider)
        if not channels:
            return ""
        
        last_used_id = self._cache.get(provider, {}).get("last_used_id", "")
        provider_label = {"youtube": "YouTube", "facebook": "Facebook", "tiktok": "TikTok"}.get(provider, provider)
        
        lines = [f"📺 Danh sách Kênh {provider_label}:\n"]
        for i, ch in enumerate(channels, 1):
            title = ch.get("title", "Unknown")
            subs = ch.get("subscribers", 0)
            url = ch.get("url", "")
            email = ch.get("email", "")
            is_last = "⭐" if ch.get("id") == last_used_id else ""
            
            try:
                subs_int = int(subs)
                subs_str = f"{subs_int:,}" if subs_int else "0"
            except (ValueError, TypeError):
                subs_str = "0"
            
            lines.append(
                f"**{i}.** {is_last} {title}\n"
                f"   📧 {email} | 👥 {subs_str} subs\n"
                f"   🔗 {url}"
            )
        
        lines.append(f"\n💡 Dùng: 'upload lên kênh {1}' hoặc 'kênh thứ {2}' để chọn nhanh")
        return "\n".join(lines)

    def resolve_channel(self, provider: str, user_text: str) -> Optional[Dict]:
        """Smart resolve: try index first, then name, then last-used.
        
        Supports:
        - "kênh 2", "kênh thứ 3", "channel 1"
        - "kênh ABC" (partial name match)
        - No specific mention → last used channel
        """
        import re
        text_lower = user_text.lower()
        
        # 1. Try index: "kênh 2", "kênh thứ 3", "channel 1"
        idx_match = re.search(r'(?:kênh|channel)\s*(?:thứ\s*)?(\d+)', text_lower)
        if idx_match:
            idx = int(idx_match.group(1))
            ch = self.get_by_index(provider, idx)
            if ch:
                return ch
        
        # 2. Try name: "kênh ABC XYZ"
        name_match = re.search(r'(?:kênh|channel|page|fanpage|trang)\s+(?:youtube\s+|facebook\s+)?([^\d].+?)(?:\s+giúp|\s+video|\s*$)', text_lower)
        if name_match:
            name = name_match.group(1).strip()
            # Skip if it's just a number (already handled above)
            if name and not name.isdigit():
                ch = self.get_by_name(provider, name)
                if ch:
                    return ch
        
        # 3. Fallback: last used
        return self.get_last_used(provider)


# Global singleton
channel_cache = ChannelCache()
""", "Description": "Created a Channel Cache service that stores channel lists per provider and supports index-based selection ('kênh 2'), name search, and last-used memory."
<br>"""
