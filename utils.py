import os
import sys
import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
SPEED_STEPS = (0.5, 0.75, 1.0, 1.5, 2.0)
REPEAT_OFF = 0
REPEAT_ONE = 1
REPEAT_ALL = 2

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
    
    return base_path / relative_path

def get_user_data_path(filename: str) -> str:
    """Get path for writable user data (settings, resume info)."""
    if getattr(sys, 'frozen', False):
        # In installed mode, use %APPDATA%/CadrePlayer
        app_data = Path(os.getenv('APPDATA')) / "CadrePlayer"
        app_data.mkdir(parents=True, exist_ok=True)
        return str(app_data / filename)
    else:
        # In dev mode, keep it local for easy access
        return str(Path(__file__).parent / filename)

def format_duration(seconds: float) -> str:
    if seconds is None:
        return "--:--"
    
    import math
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"

    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS

def list_folder_videos(folder: Path, recursive: bool = False) -> list[str]:
    if not folder.exists() or not folder.is_dir():
        return []
    
    if recursive:
        # Recursive search using glob patterns
        all_videos = []
        for ext in VIDEO_EXTENSIONS:
            all_videos.extend(folder.rglob(f"*{ext}"))
            all_videos.extend(folder.rglob(f"*{ext.upper()}"))
        # Sort by path for a consistent experience
        return [str(p.resolve()) for p in sorted(all_videos, key=lambda p: str(p).lower())]
    else:
        # Non-recursive (shallow) search
        return [
            str(item.resolve())
            for item in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if item.is_file() and is_video_file(item)
        ]

def collect_paths(paths: list[Path], recursive: bool = False) -> list[str]:
    files = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and is_video_file(resolved):
            files.append(str(resolved))
        elif resolved.is_dir():
            files.extend(list_folder_videos(resolved, recursive=recursive))
    return files

def reveal_path(path: str):
    path_obj = Path(path)
    if not path_obj.exists():
        return
    
    if os.name == "nt":
        # Windows-specific: select the file in explorer
        subprocess.run(["explorer", "/select,", str(path_obj.resolve())])
    else:
        # Standard open folder for other OS
        folder = str(path_obj.parent.resolve())
        os.startfile(folder) if hasattr(os, "startfile") else subprocess.run(["open", folder])

def delete_to_trash(path: str) -> bool:
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except Exception:
        return False
