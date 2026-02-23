import os
import subprocess
import tempfile
from PySide6.QtCore import QThread, Signal
from .utils import format_duration

class DurationScanner(QThread):
    finished_item = Signal(str, str, float) # path, duration_str, seconds


    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        for path in self.paths:
            if self.isInterruptionRequested():
                break
            try:
                flags = 0
                if os.name == "nt":
                    flags = 0x08000000 # CREATE_NO_WINDOW
                
                cmd = [
                    "ffprobe", 
                    "-v", "error", 
                    "-show_entries", "format=duration", 
                    "-of", "default=noprint_wrappers=1:nokey=1", 
                    path
                ]
                fd, out_path = tempfile.mkstemp(prefix="cadre_ffprobe_", suffix=".txt")
                os.close(fd)
                try:
                    with open(out_path, "wb") as out_f:
                        subprocess.run(
                            cmd,
                            stdout=out_f,
                            stderr=subprocess.DEVNULL,
                            creationflags=flags,
                            timeout=8,
                            check=False,
                        )
                    with open(out_path, "r", encoding="utf-8", errors="ignore") as in_f:
                        result = in_f.read().strip()
                finally:
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                if result:
                    seconds = float(result)
                    dur_str = format_duration(seconds)
                    self.finished_item.emit(path, dur_str, seconds)

            except Exception:
                continue
