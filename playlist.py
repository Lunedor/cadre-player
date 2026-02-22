import os
import subprocess
from PySide6.QtCore import QThread, Signal
from .utils import format_duration

class DurationScanner(QThread):
    finished_item = Signal(str, str, float) # path, duration_str, seconds


    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        for path in self.paths:
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
                result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, creationflags=flags).decode().strip()
                if result:
                    seconds = float(result)
                    dur_str = format_duration(seconds)
                    self.finished_item.emit(path, dur_str, seconds)

            except Exception:
                continue
