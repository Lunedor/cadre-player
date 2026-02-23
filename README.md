[![If you are a good person...](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/lunedor)

# Cadre Player

Cadre Player is a desktop media player built with Python, PySide6 (Qt), and libmpv.
It focuses on a clean frameless UI, playlist workflows, and practical controls for local and URL-based media.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)
![Framework](https://img.shields.io/badge/framework-PySide6-orange.svg)

## Features

- Frameless window with custom title bar
- Playlist panel with drag and drop, search, sort, and multi-select actions
- File, folder, URL, and WebDAV import support
- Audio and video playback through mpv
- Repeat and shuffle modes
- Playback speed control
- Subtitle and video settings dialogs
- Equalizer dialog
- Resume position per media item
- M3U save/load support
- YouTube and stream URL import (yt-dlp based)
- App logging to `logs.txt`

## Requirements

- Python 3.8+
- Windows, Linux, or macOS (Windows is the primary tested environment)
- `libmpv` runtime available

Python dependencies are listed in `requirements.txt`:

- `PySide6`
- `python-mpv`
- `Send2Trash`
- `yt-dlp`

## Installation

1. Get the source:

```bash
git clone https://github.com/<your-user-or-org>/cadre-player.git
cd cadre-player
```


2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Ensure mpv runtime is available:

Cadre Player requires `libmpv-2.dll` or `mpv-1.dll`. 
- If it is missing, download the DLL from [mpv.io](https://mpv.io/installation/).
- Place the DLL in the root of the project folder or inside the `py_video` directory and rename it to 'mpv-1.dll' if it has a different name.

## Run

```bash
python main.pyw
```

Or:

```bash
python main.py
```

## Keyboard Shortcuts

| Key | Action |
| --- | --- |
| `Space` | Play / Pause |
| `Left` / `Right` | Seek backward / forward |
| `Up` / `Down` | Volume up / down |
| `PageUp` | Previous item |
| `PageDown` | Next item |
| `Enter` (playlist) | Play selected item |
| `Delete` | Remove selected playlist items |
| `Shift+Delete` | Delete selected file(s) to recycle bin |
| `P` | Toggle playlist |
| `F` | Fullscreen |
| `M` | Mute / Unmute |
| `Esc` | Exit fullscreen or hide unpinned playlist |

## Logging and Diagnostics

- Runtime log file: `logs.txt`
- Settings and resume data: `settings.ini`
- If you hit a crash, clear `logs.txt`, reproduce once, then share the newest tail section.

## Project Structure

- `main.py`, `main.pyw`: entry points
- `player_window.py`: main window and playback flow
- `playlist.py`: background duration scanning
- `logic.py`: repeat/shuffle navigation logic
- `ui/`: widgets, dialogs, icons, styles, menus
- `locales/`: translation files
- `settings.py`: persistent app settings helpers
- `app_logging.py`: logging setup and exception hooks

## Current Notes

- Large playlists are handled with progressive updates and lazy duration scanning.
- Duration filling is intentionally safer under heavy playback switching.
- WebDAV URLs can be added from the URL import flow and resolved into playable entries.
- Stream extraction quality and completeness can depend on your local yt-dlp runtime setup.

## License

MIT. See `LICENSE`.
er the MIT License - see the [LICENSE](LICENSE) file for details.
