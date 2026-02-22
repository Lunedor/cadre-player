# Cadre Player

A modern, sleek, and feature-rich video player built with **Python**, **PySide6 (Qt)**, and the **MPV** engine. Cadre Player offers a premium desktop experience with a frameless UI, customizable controls, and a focus on performance.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-brightgreen.svg)
![Qt](https://img.shields.io/badge/framework-PySide6-orange.svg)

## ✨ Features

- 🖼️ **Frameless Window**: Modern, immersive design with custom title bar controls.
- 📋 **Integrated Playlist**: Easily manage your queue with drag-and-drop support, pinned drawer, and search/sort functionality.
- 🎮 **Premium Controls**: Hover-activated transport bar with a complete set of playback tools (Shuffle, Repeat, Speed Control, etc.).
- 🚀 **MPV Powered**: High-performance video rendering with hardware acceleration support.
- 🌍 **Internationalization**: Full support for multiple languages (current: English, Turkish).
- ⚙️ **Smart Resume**: Automatically remembers your playback position for every video.
- 🎨 **Rich Aesthetics**: Vibrant colors, smooth gradients, and glassmorphism-inspired UI components.

## 🛠️ Installation

### 1. Prerequisites
- Python 3.8 or higher.
- `libmpv` shared library (see below).

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. MPV Setup (Windows)
Cadre Player requires `libmpv-2.dll` or `mpv-1.dll`. 
- If it is missing, download the DLL from [mpv.io](https://mpv.io/installation/) or [shinchiro's builds](https://mpv.splayer.info/).
- Place the DLL in the root of the project folder or inside the `py_video` directory.

## 🚀 Usage

Run the application using the launcher:

```bash
python main.pyw
```

## ⌨️ Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `S` | Stop |
| `F` / `Double Click` | Toggle Fullscreen |
| `P` | Toggle Playlist |
| `←` / `→` | Seek -5s / +5s |
| `↑` / `↓` | Volume +/- 5% |
| `+` / `-` | Zoom In / Out |
| `[` / `]` | Speed Down / Up |
| `M` | Mute |
| `Esc` | Exit Fullscreen / Hide Playlist |

## 🏗️ Project Structure
- `py_video/`: Main package directory.
  - `ui/`: Custom widgets, icons, and CSS styles.
  - `locales/`: Translation files (i18n).
  - `logic.py`: Core application state and player logic.
  - `player_window.py`: Main window implementation and event handling.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
