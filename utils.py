import os
import sys
import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".alac", ".aiff")
def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS
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

def list_folder_media(folder: Path, recursive: bool = False) -> list[str]:
    if not folder.exists() or not folder.is_dir():
        return []
    
    if recursive:
        all_media = []
        for ext in VIDEO_EXTENSIONS + AUDIO_EXTENSIONS:
            all_media.extend(folder.rglob(f"*{ext}"))
            all_media.extend(folder.rglob(f"*{ext.upper()}"))
        return [str(p.resolve()) for p in sorted(all_media, key=lambda p: str(p).lower())]
    else:
        return [
            str(item.resolve())
            for item in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if item.is_file() and (is_video_file(item) or is_audio_file(item))
        ]

def collect_paths(
    paths: list[Path],
    recursive: bool = False,
    progress_cb=None,
    progress_step: int = 100,
) -> list[str]:
    files = []
    pending_emit = 0

    def maybe_emit(force: bool = False):
        nonlocal pending_emit
        if progress_cb is None:
            return
        if force or pending_emit >= max(1, int(progress_step)):
            progress_cb(len(files))
            pending_emit = 0

    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and (is_video_file(resolved) or is_audio_file(resolved)):
            files.append(str(resolved))
            pending_emit += 1
            maybe_emit()
        elif resolved.is_dir():
            if recursive:
                for root, dirs, filenames in os.walk(resolved):
                    dirs.sort(key=lambda d: d.lower())
                    filenames.sort(key=lambda f: f.lower())
                    for filename in filenames:
                        full_path = Path(root) / filename
                        if is_video_file(full_path) or is_audio_file(full_path):
                            files.append(str(full_path.resolve()))
                            pending_emit += 1
                            maybe_emit()
            else:
                for item in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file() and (is_video_file(item) or is_audio_file(item)):
                        files.append(str(item.resolve()))
                        pending_emit += 1
                        maybe_emit()
    maybe_emit(force=True)
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
