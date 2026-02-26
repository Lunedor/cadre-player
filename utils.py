import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlparse

VIDEO_EXTENSIONS = (
    ".3g2",
    ".3gp",
    ".amv",
    ".asf",
    ".avi",
    ".drc",
    ".dv",
    ".f4v",
    ".flv",
    ".gifv",
    ".m2t",
    ".m2ts",
    ".m2v",
    ".m4v",
    ".mjpeg",
    ".mjpg",
    ".mkv",
    ".mov",
    ".mp2v",
    ".mp4",
    ".mpe",
    ".mpeg",
    ".mpg",
    ".mpv",
    ".mts",
    ".mxf",
    ".nut",
    ".ogm",
    ".ogv",
    ".qt",
    ".rm",
    ".rmvb",
    ".roq",
    ".swf",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
    ".y4m",
)
AUDIO_EXTENSIONS = (
    ".aac",
    ".ac3",
    ".aif",
    ".aifc",
    ".aiff",
    ".alac",
    ".amr",
    ".ape",
    ".au",
    ".caf",
    ".dts",
    ".eac3",
    ".flac",
    ".m4a",
    ".m4b",
    ".mka",
    ".mp2",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".ra",
    ".spx",
    ".tta",
    ".wav",
    ".weba",
    ".wma",
    ".wv",
)
VIDEO_EXTENSION_SET = set(VIDEO_EXTENSIONS)
AUDIO_EXTENSION_SET = set(AUDIO_EXTENSIONS)
NON_MEDIA_EXTENSION_SET = {
    ".ass", ".bmp", ".doc", ".docx", ".gif", ".ico", ".ini", ".jpeg", ".jpg",
    ".json", ".log", ".lua", ".md", ".nfo", ".pdf", ".png", ".py", ".rtf",
    ".srt", ".ssa", ".sub", ".svg", ".toml", ".txt", ".vtt", ".xml", ".yaml",
    ".yml", ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".exe", ".dll",
}
_MEDIA_PROBE_CACHE: dict[str, bool] = {}


def _probe_is_media_file(path: Path) -> bool:
    cache_key = str(path.resolve())
    cached = _MEDIA_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        flags = 0
        if os.name == "nt":
            flags = 0x08000000  # CREATE_NO_WINDOW
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=2,
            check=False,
            text=True,
        )
        stream_types = {line.strip().lower() for line in (completed.stdout or "").splitlines()}
        is_media = bool({"audio", "video"} & stream_types)
    except Exception:
        is_media = False
    _MEDIA_PROBE_CACHE[cache_key] = is_media
    if len(_MEDIA_PROBE_CACHE) > 4096:
        _MEDIA_PROBE_CACHE.clear()
    return is_media


def is_media_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSION_SET or ext in AUDIO_EXTENSION_SET:
        return True
    if ext in NON_MEDIA_EXTENSION_SET:
        return False
    return _probe_is_media_file(path)


def is_audio_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in AUDIO_EXTENSION_SET:
        return True
    if ext in VIDEO_EXTENSION_SET or ext in NON_MEDIA_EXTENSION_SET:
        return False
    return _probe_is_media_file(path)
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


def get_user_data_dir() -> Path:
    """Get writable base directory for app-managed user files."""
    if getattr(sys, "frozen", False):
        app_data = Path(os.getenv("APPDATA")) / "CadrePlayer"
        app_data.mkdir(parents=True, exist_ok=True)
        return app_data
    return Path(__file__).parent


def is_stream_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return bool(parsed.scheme and parsed.netloc)

def format_duration(seconds: float) -> str:
    if seconds is None:
        return "--:--"
    
    import math
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"

    # Round to nearest second to reduce one-second jitter between probe/runtime sources.
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def is_video_file(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSION_SET:
        return True
    if ext in AUDIO_EXTENSION_SET or ext in NON_MEDIA_EXTENSION_SET:
        return False
    return _probe_is_media_file(path)

def list_folder_media(folder: Path, recursive: bool = False) -> list[str]:
    if not folder.exists() or not folder.is_dir():
        return []
    
    if recursive:
        all_media = []
        for root, dirs, filenames in os.walk(folder):
            dirs.sort(key=lambda d: d.lower())
            filenames.sort(key=lambda f: f.lower())
            for filename in filenames:
                full_path = Path(root) / filename
                if is_media_file(full_path):
                    all_media.append(str(full_path.resolve()))
        return all_media
    else:
        return [
            str(item.resolve())
            for item in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if item.is_file() and is_media_file(item)
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
        if resolved.is_file() and is_media_file(resolved):
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
                        if is_media_file(full_path):
                            files.append(str(full_path.resolve()))
                            pending_emit += 1
                            maybe_emit()
            else:
                for item in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file() and is_media_file(item):
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
