import ctypes
import os
import sys
from pathlib import Path


def configure_windows_dlls(project_dir: Path) -> None:
    """Ensure local MPV DLLs can be discovered on Windows."""
    if os.name != "nt":
        return

    candidate_dirs = [
        project_dir.resolve(),
        (project_dir / "py_video").resolve(),
        Path.cwd().resolve(),
    ]

    # If running as compiled EXE, also check the executable's directory
    if getattr(sys, 'frozen', False):
        candidate_dirs.insert(0, Path(sys.executable).parent.resolve())

    # Preserve order and avoid duplicates.
    unique_dirs = []
    seen = set()
    for directory in candidate_dirs:
        key = str(directory).lower()
        if key in seen or not directory.exists():
            continue
        seen.add(key)
        unique_dirs.append(directory)

    if hasattr(os, "add_dll_directory"):
        for directory in unique_dirs:
            os.add_dll_directory(str(directory))

    os.environ["PATH"] = os.pathsep.join([*(str(d) for d in unique_dirs), os.environ.get("PATH", "")])

    # Best effort: pre-load bundled mpv dll variants if present.
    dll_names = ("libmpv-2.dll", "mpv-1.dll", "mpv.dll")
    for directory in unique_dirs:
        for dll_name in dll_names:
            dll_path = directory / dll_name
            if not dll_path.exists():
                continue
            try:
                ctypes.CDLL(str(dll_path))
                return
            except Exception:
                continue
