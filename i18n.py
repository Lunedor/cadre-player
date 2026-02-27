import json
import locale
from pathlib import Path
from .utils import get_resource_path

# Fallback English dictionary
_default_en = {
    # Generic / Mixed
    "Play / Pause": "Play / Pause",
    "Stop": "Stop",
    "Previous": "Previous",
    "Next": "Next",
    "Mute / Unmute": "Mute / Unmute",
    "Playback Speed": "Playback Speed",
    "Playback Settings": "Playback Settings",
    "{}x (Normal)": "{}x (Normal)",
    "Subtitles": "Subtitles",
    "Audio Tracks": "Audio Tracks",
    "Video Quality": "Video Quality",
    "Auto (Best)": "Auto (Best)",
    "Quality: {} (reloaded)": "Quality: {} (reloaded)",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "360p": "360p",
    "Quality: {}": "Quality: {}",
    "No quality options": "No quality options",
    "Renderer": "Renderer",
    "GPU (Legacy)": "GPU (Legacy)",
    "GPU Next (Recommended for DV)": "GPU Next (Recommended for DV)",
    "Subtitle Tracks": "Subtitle Tracks",
    "No Subtitles": "No Subtitles",
    "Add Subtitle File": "Add Subtitle File",
    "Subtitle Settings": "Subtitle Settings",
    "Video Settings": "Video Settings",
    "Screenshot": "Screenshot",
    "Toggle Playlist": "Toggle Playlist",
    "Delete File": "Delete File",
    "Fullscreen": "Fullscreen",
    "Always On Top": "Always On Top",
    "Pin Controls": "Pin Controls",
    "Pin Playlist": "Pin Playlist",
    "Quit": "Quit",
    "Video Options": "Video Options",
    "Audio Options": "Audio Options",
    "Subtitle Options": "Subtitle Options",
    "View Interface": "View Interface",
    
    # Playlist Context
    "Play": "Play",
    "Remove": "Remove",
    "Delete file": "Delete file",
    "Reveal in Explorer": "Reveal in Explorer",
    "Copy path": "Copy path",
    "Remove {} items": "Remove {} items",
    "Delete {} files from disk": "Delete {} files from disk",
    "Copy paths": "Copy paths",
    "Show": "Show",
    "Add content": "Add content",
    "Open URL": "Open URL",
    "Enter URL:": "Enter URL:",
    "URL": "URL",
    "Use SSL": "Use SSL",
    "Port": "Port",
    "Use authentication": "Use authentication",
    "Username": "Username",
    "Password": "Password",
    "File": "File",
    "Folder": "Folder",
    "Open": "Open",
    "Cancel": "Cancel",
    "Reset": "Reset",
    "OK": "OK",

    # Status Overlays
    "Volume: {}%": "Volume: {}%",
    "Added {count}": "Added {count}",
    "Adding files... {}": "Adding files... {}",
    "including": "including",
    "excluding": "excluding",
    "Sort {} folders": "Sort {} folders",
    "Sorted: {} {}": "Sorted: {} {}",
    "Playlist Saved": "Playlist Saved",
    "Loaded {} items": "Loaded {} items",
    "No valid files in playlist": "No valid files in playlist",
    "Resolving stream URLs...": "Resolving stream URLs...",
    "Resolving stream URLs... {}": "Resolving stream URLs... {}",
    "Imported {} stream items": "Imported {} stream items",
    "No stream URLs found": "No stream URLs found",
    "No new items imported": "No new items imported",
    "Stream import failed: {}": "Stream import failed: {}",
    "Imported 0, failed {}": "Imported 0, failed {}",
    "Imported {}, failed {}": "Imported {}, failed {}",
    "{}x": "{}x",
    "Shuffle On": "Shuffle On",
    "Shuffle Off": "Shuffle Off",
    "Repeat Off": "Repeat Off",
    "Repeat One": "Repeat One",
    "Repeat All": "Repeat All",
    "Resumed from {}": "Resumed from {}",
    "Zoom Reset": "Zoom Reset",
    "Pan Left": "Pan Left",
    "Pan Right": "Pan Right",
    "Pan Up": "Pan Up",
    "Pan Down": "Pan Down",
    "Controls Pinned": "Controls Pinned",
    "Controls Unpinned": "Controls Unpinned",
    "Playlist Pinned": "Playlist Pinned",
    "Playlist Unpinned": "Playlist Unpinned",
    "Aspect: {}": "Aspect: {}",
    "Seek: {} / {}": "Seek: {} / {}",
    "Paused": "Paused",
    "Playing": "Playing",
    "Muted": "Muted",
    "Unmuted": "Unmuted",
    "Zoom: {}": "Zoom: {}",
    "Rotate: {}": "Rotate: {}",
    "Rotate: {}°": "Rotate: {}°",
    "Rotate reset": "Rotate reset",
    "Mirror Horizontal": "Mirror Horizontal",
    "Mirror Vertical": "Mirror Vertical",
    "Mirror Horizontal: {}": "Mirror Horizontal: {}",
    "Mirror Vertical: {}": "Mirror Vertical: {}",
    "Seek Thumbnail Preview": "Seek Thumbnail Preview",
    "On": "On",
    "Off": "Off",
    "Brightness: {}": "Brightness: {}",
    "Delay: {}s": "Delay: {}s",
    "Size: {}": "Size: {}",
    "Pos: {}": "Pos: {}",

    # Dialogs & Prompts
    "Select files to open": "Select files to open",
    "Video Files ({})": "Video Files ({})",
    "All files (*.*)": "All files (*.*)",
    "Select folder to open": "Select folder to open",
    "Include Subfolders": "Include Subfolders",
    "Do you want to include media from subfolders as well?": "Do you want to include media from subfolders as well?",
    "Select Save Location": "Select Save Location",
    "M3U files (*.m3u *.m3u8);;All files (*.*)": "M3U files (*.m3u *.m3u8);;All files (*.*)",
    "Select M3U Playlist": "Select M3U Playlist",
    "Recycle:\n{}?": "Recycle:\n{}?",
    "Recycle {} selected files?": "Recycle {} selected files?",
    "Recycle Bin": "Recycle Bin",
    "Deleted {} files": "Deleted {} files",
    "Add Subtitle": "Add Subtitle",
    "Subtitles (*.srt *.ass *.ssa *.sub *.vtt)": "Subtitles (*.srt *.ass *.ssa *.sub *.vtt)",
    "Save screenshot": "Save screenshot",
    "Include folder name in sort": "Include folder name in sort",
    "Name (A-Z)": "Name (A-Z)",
    "Name (Z-A)": "Name (Z-A)",
    "Duration (Shortest first)": "Duration (Shortest first)",
    "Duration (Longest first)": "Duration (Longest first)",
    "Error": "Error",
    "Could not save playlist: {}": "Could not save playlist: {}",
    "Could not load playlist: {}": "Could not load playlist: {}",
    "Path": "Path",
    "Duration": "Duration",
    "DESC": "DESC",
    "ASC": "ASC",
    "Modern desktop media player powered by MPV.": "Modern desktop media player powered by MPV.",
    "• MPV backend\n• Playlist and stream support\n• Subtitle, video and equalizer controls": "• MPV backend\n• Playlist and stream support\n• Subtitle, video and equalizer controls",
    "Scan All Durations": "Scan All Durations",
    "Cancel Duration Scan": "Cancel Duration Scan",
    "Scanning durations... {}/{}": "Scanning durations... {}/{}",
    "Duration scan complete ({}/{})": "Duration scan complete ({}/{})",
    "Duration scan cancelled ({}/{})": "Duration scan cancelled ({}/{})",
    "All local item durations are already known": "All local item durations are already known",
    "Scan {} local playlist items for duration now?\nPlayback will stay paused until scan finishes or is cancelled.": "{} local playlist items for duration now?\nPlayback will stay paused until scan finishes or is cancelled.",

    # Settings Dialogs
    "Appearance": "Appearance",
    "Font Size": "Font Size",
    "Color": "Color",
    "Background": "Background",
    "Vertical Pos": "Vertical Pos",
    "Timing": "Timing",
    "Sync Delay": "Sync Delay",
    "Done": "Done",
    "None": "None",
    "Shadow": "Shadow",
    "Outline": "Outline",
    "Opaque Box": "Opaque Box",
    "White": "White",
    "Yellow": "Yellow",
    "Cyan": "Cyan",
    "Green": "Green",
    "Red": "Red",
    "Performance": "Performance",
    "Hardware Decoding": "Hardware Decoding",
    "Image Adjustments": "Image Adjustments",
    "Brightness": "Brightness",
    "Contrast": "Contrast",
    "Saturation": "Saturation",
    "Gamma": "Gamma",
    "Geometry": "Geometry",
    "Video Zoom": "Video Zoom",
    "Aspect Ratio": "Aspect Ratio",
    "Rotation": "Rotation",
    "Rotate 90": "Rotate 90",
    "Reset Rotation": "Reset Rotation",
    "Reset All": "Reset All",
    "auto": "auto",

    # Tooltips
    "Shuffle": "Shuffle",
    "Repeat mode": "Repeat mode",
    "Add files": "Add files",
    "Add folder": "Add folder",
    "Open M3U Playlist": "Open M3U Playlist",
    "Save M3U Playlist": "Save M3U Playlist",
    "Restore last session playlist": "Restore last session playlist",
    "Remove from playlist": "Remove from playlist",
    "Sort Playlist": "Sort Playlist",
    "Delete file to recycle bin": "Delete file to recycle bin",
    "Toggle playlist": "Toggle playlist",
    "Search playlist": "Search playlist",
    "Hide search": "Hide search",
    "Search in playlist...": "Search in playlist...",
    "Open Advanced Config (mpv.conf)": "Open Advanced Config (mpv.conf)",
    "Open Scripts Folder": "Open Scripts Folder",
    "Could not open mpv.conf": "Could not open mpv.conf",
    "Could not open scripts folder": "Could not open scripts folder",
    "Stats overlay unavailable": "Stats overlay unavailable",
    "No saved session playlist": "No saved session playlist",
    "Restored {} session items": "Restored {} session items",
    "Saved session playlist is empty": "Saved session playlist is empty",
    "Could not restore session playlist": "Could not restore session playlist",
    "Open file(s)": "Open file(s)",
    "Open folder": "Open folder",
    "Open URL dialog": "Open URL dialog",
}

_translations = {}

def get_system_language():
    try:
        lang, _ = locale.getlocale()
        if lang:
            return lang.split('_')[0].lower()
    except:
        pass
    return "en"

def load_language(lang_code):
    global _translations
    translations_dir = get_resource_path("locales")
    translations_dir.mkdir(exist_ok=True)
    
    lang_file = translations_dir / f"{lang_code}.json"
    if lang_file.exists():
        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                _translations = json.load(f)
        except Exception as e:
            print(f"Failed to load language '{lang_code}': {e}")
            _translations = {}
    else:
        _translations = {}
        # If the file doesn't exist, we can optionally create a template
        if lang_code == "en":
            try:
                with open(lang_file, "w", encoding="utf-8") as f:
                    json.dump(_default_en, f, indent=4, ensure_ascii=False)
            except:
                pass

def setup_i18n(lang_code=None):
    if not lang_code:
        # Check settings first, then fall back to system
        from .settings import load_language_setting
        lang_code = load_language_setting("")
        if not lang_code:
            lang_code = get_system_language()
    load_language(lang_code)

def get_supported_languages():
    """Returns a list of (code, name) tuples for available locales."""
    locales_dir = get_resource_path("locales")
    langs = [("en", "English")] # English is always supported
    
    # Map of codes to display names (could be expanded)
    names = {
        "tr": "Türkçe",
        "en": "English",
        "de": "Deutsch",
        "fr": "Français",
        "es": "Español",
        "pt": "Português",
        "it": "Italiano",
        "ja": "日本語",
        "uk": "Українська",
        "ru": "Русский",
        "zh": "中文",
        "ar": "العربية"
    }
    
    if locales_dir.exists():
        for f in locales_dir.glob("*.json"):
            code = f.stem
            if code == "en": continue
            name = names.get(code, code.upper())
            langs.append((code, name))
            
    return sorted(langs, key=lambda x: x[1])

def tr(text, *args):
    """Translate function. Takes a format string and optional positional arguments."""
    translated = _translations.get(text, _default_en.get(text, text))
    if args:
        try:
            return translated.format(*args)
        except Exception:
            return translated
    return translated
