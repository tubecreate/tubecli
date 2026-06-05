"""
Rollback script for TubeCLI Extension Data Refactoring.
Moves all migrated extension data back to data/ and removes junctions/links.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

# Force UTF-8 encoding for stdout to prevent UnicodeEncodeError with emojis on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.parent  # tubecli/ root
DATA_DIR = BASE_DIR / "data"
EXTENSIONS_DATA_DIR = DATA_DIR / "extensions_data"
EXTENSIONS_EXTERNAL_DIR = DATA_DIR / "extensions_external"


def unhide_path(path: Path):
    """Remove hidden attribute on Windows."""
    if os.name == 'nt' and path.exists():
        import ctypes
        try:
            # FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)
        except Exception:
            pass


def is_junction(path: Path) -> bool:
    try:
        return path.is_dir() and os.path.abspath(path) != os.path.realpath(path)
    except Exception:
        return False


def remove_link(path: Path):
    """Remove directory junction, symlink, or file link."""
    if not path.exists() and not os.path.islink(str(path)) and not (os.name == 'nt' and is_junction(path)):
        return

    unhide_path(path)
    try:
        if path.is_dir():
            if os.name == 'nt':
                # On Windows, rmdir on a junction deletes the link, not the contents.
                os.rmdir(str(path))
            else:
                os.unlink(str(path))
        else:
            os.remove(str(path))
        print(f"Removed legacy link: {path}")
    except Exception as e:
        print(f"Error removing link {path}: {e}")


def rollback():
    print("🔄 Starting rollback of TubeCLI extension data refactoring...")

    if not EXTENSIONS_DATA_DIR.exists():
        print("❌ extensions_data directory not found. Nothing to rollback.")
        return

    # --- A. Rollback Directories ---
    ext_names = set([
        "ai_arena", "content_studio", "edu_video_studio", "graphic_studio",
        "livestream", "news_intel", "pod_studio", "remix_studio",
        "subtitle_extractor", "template_designer", "tts_vibevoice", "video_editor",
        "web_crawler", "video_downloader", "browser"
    ])

    # Auto-discover external extensions in extensions_data
    try:
        for entry in os.listdir(EXTENSIONS_DATA_DIR):
            if (EXTENSIONS_DATA_DIR / entry).is_dir() and not entry.startswith('.'):
                ext_names.add(entry)
    except Exception:
        pass

    # Mapping of folders that have a different name in DATA_DIR
    folder_mapping = {
        "web_crawler": ["web_crawler_exports"],
        "video_downloader": ["ytdl_downloads"],
        "browser": ["browser_profiles"]
    }

    for ext_name in ext_names:
        folders = folder_mapping.get(ext_name, [ext_name])
        for folder_name in folders:
            old_folder_path = DATA_DIR / folder_name
            new_folder_path = EXTENSIONS_DATA_DIR / ext_name / folder_name

            # 1. Remove junction / symlink at old path
            remove_link(old_folder_path)

            # 2. Move files back from extensions_data to data/
            if new_folder_path.exists() and new_folder_path.is_dir():
                try:
                    shutil.move(str(new_folder_path), str(old_folder_path))
                    unhide_path(old_folder_path)
                    print(f"Restored folder: {new_folder_path} -> {old_folder_path}")
                except Exception as e:
                    print(f"Error restoring folder {folder_name}: {e}")

    # --- B. Rollback Files ---
    file_mapping = {
        "web_crawler": ["watches.json", "watch_logs.json", "yt_watches.json", "yt_watch_logs.json", "wp_sites.json"],
        "video_downloader": ["downloader_settings.json", "ytdl_cookies.txt"],
        "studio3d": ["studio3d_scenes.json"],
        "universal_tracker": ["universal_tracker_jobs.json"],
        "auth_manager": ["auth_manager.json"],
        "calendar_manager": ["calendar_manager.json"],
        "content_studio": ["content_studio.db"],
    }

    for ext_name, filenames in file_mapping.items():
        for filename in filenames:
            old_file_path = DATA_DIR / filename
            new_file_path = EXTENSIONS_DATA_DIR / ext_name / filename

            # 1. Remove hardlink at old path
            remove_link(old_file_path)

            # 2. Move file back from extensions_data to data/
            if new_file_path.exists() and new_file_path.is_file():
                try:
                    shutil.move(str(new_file_path), str(old_file_path))
                    unhide_path(old_file_path)
                    print(f"Restored file: {new_file_path} -> {old_file_path}")
                except Exception as e:
                    print(f"Error restoring file {filename}: {e}")

    # --- C. Cleanup empty directories ---
    # Delete subdirectories of extensions_data if they are empty
    try:
        for ext_name in os.listdir(EXTENSIONS_DATA_DIR):
            ext_dir = EXTENSIONS_DATA_DIR / ext_name
            if ext_dir.is_dir():
                # Remove empty subfolders
                for root, dirs, files in os.walk(str(ext_dir), topdown=False):
                    for d in dirs:
                        try:
                            os.rmdir(os.path.join(root, d))
                        except OSError:
                            pass
                # Remove empty extension folder
                try:
                    os.rmdir(str(ext_dir))
                except OSError:
                    pass
    except Exception:
        pass

    # Remove extensions_data folder if empty
    try:
        os.rmdir(str(EXTENSIONS_DATA_DIR))
        print("Removed extensions_data directory.")
    except OSError:
        pass

    print("✅ Rollback completed successfully.")


if __name__ == "__main__":
    rollback()
