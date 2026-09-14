from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from .utils import get_user_data_path, get_user_data_dir
from .mpv_power_config import ensure_mpv_power_user_layout, save_mpv_video_overrides
import json
import os
import shutil
import time
from pathlib import Path

ORG_NAME = "Cadre"
APP_NAME = "Cadre Player"
VOLUME_KEY = "audio/volume"
MUTED_KEY = "audio/muted"
SHUFFLE_KEY = "player/shuffle"
REPEAT_KEY = "player/repeat"
LANGUAGE_KEY = "player/language"
EQUALIZER_ENABLED_KEY = "audio/equalizer_enabled"
EQUALIZER_GAINS_KEY = "audio/equalizer_gains"
STREAM_AUTH_ENABLED_KEY = "network/stream_auth_enabled"
STREAM_AUTH_USERNAME_KEY = "network/stream_auth_username"
STREAM_AUTH_PASSWORD_KEY = "network/stream_auth_password"
STREAM_QUALITY_KEY = "network/stream_quality"
SESSION_RESTORE_ON_STARTUP_KEY = "player/restore_session_on_startup"
IMPORT_INCLUDE_AUDIO_KEY = "player/import_include_audio"
OS_USERNAME_KEY = "opensubtitles/os_username"
OS_PASSWORD_KEY = "opensubtitles/os_password"
OS_DEFAULT_LANG_KEY = "opensubtitles/os_default_lang"

def _to_int(value, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _to_float(value, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _to_choice(value, default: str, allowed: set[str], allow_custom: bool = False) -> str:
    token = str(value or "").strip()
    if token in allowed:
        return token
    if allow_custom and token:
        return token
    return default


def _get_default_screenshot_dir() -> str:
    path = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    if path:
        return path
    return str(Path.home() / "Pictures")


def _to_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return bool(default)
    return bool(value)

def get_settings() -> QSettings:
    """Returns a QSettings object pointing to a visible .ini file."""
    path = get_user_data_path("settings.ini")
    return QSettings(path, QSettings.IniFormat)

def load_volume(default: int = 70) -> int:
    settings = get_settings()
    value = settings.value(VOLUME_KEY, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, number))


def save_volume(value: int) -> None:
    settings = get_settings()
    settings.setValue(VOLUME_KEY, max(0, min(100, int(value))))
    settings.sync()


def load_muted(default: bool = False) -> bool:
    settings = get_settings()
    value = settings.value(MUTED_KEY, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def save_muted(value: bool) -> None:
    settings = get_settings()
    settings.setValue(MUTED_KEY, bool(value))
    settings.sync()


def load_shuffle(default: bool = False) -> bool:
    settings = get_settings()
    value = settings.value(SHUFFLE_KEY, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def save_shuffle(value: bool) -> None:
    settings = get_settings()
    settings.setValue(SHUFFLE_KEY, bool(value))
    settings.sync()



SUB_FONT_SIZE_KEY = "sub/font_size"
SUB_COLOR_KEY = "sub/color"
SUB_POS_KEY = "sub/pos"
SUB_DELAY_KEY = "sub/delay"
SUB_BACK_STYLE_KEY = "sub/back_style"
ASPECT_RATIO_KEY = "video/aspect_ratio"
VIDEO_SCALE_KEY = "video/scale"
VIDEO_CSCALE_KEY = "video/cscale"
VIDEO_DSCALE_KEY = "video/dscale"
VIDEO_DEBAND_KEY = "video/deband"
VIDEO_DEBAND_ITERATIONS_KEY = "video/deband_iterations"
VIDEO_DEBAND_THRESHOLD_KEY = "video/deband_threshold"
VIDEO_DEBAND_RANGE_KEY = "video/deband_range"
VIDEO_TONE_MAPPING_KEY = "video/tone_mapping"
SCREENSHOT_DIR_KEY = "video/screenshot_dir"
SCREENSHOT_USE_DEFAULT_DIR_KEY = "video/screenshot_use_default_dir"
SCREENSHOT_FORMAT_KEY = "video/screenshot_format"
SCREENSHOT_MODE_KEY = "video/screenshot_mode"
AUDIO_NORMALIZE_KEY = "audio/normalize"
RESUME_POS_PREFIX = "resume/"
SUB_DELAY_PER_FILE_PREFIX = "sub_delay/"
AUDIO_DELAY_KEY = "audio/delay"
AUDIO_DELAY_PER_FILE_PREFIX = "audio_delay/"
PIN_CONTROLS_KEY = "player/pin_controls"
PIN_PLAYLIST_KEY = "player/pin_playlist"

# Per-file playback history (resume position, sub/audio delay) is kept out of
# settings.ini in its own bounded JSON file so it doesn't grow forever.
PLAYBACK_HISTORY_FILE = "playback_history.json"
PLAYBACK_HISTORY_MAX_ENTRIES = 500
# Shared by the store and apply sides so a saved resume point is never below what actually gets used.
MIN_RESUME_SECONDS = 5.0

_playback_history_cache: dict | None = None
_legacy_playback_history_migrated = False


def _playback_history_path() -> str:
    return get_user_data_path(PLAYBACK_HISTORY_FILE)


def _read_playback_history_file() -> dict:
    path = _playback_history_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_playback_history_file(data: dict) -> None:
    path = _playback_history_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def _migrate_legacy_playback_history(data: dict) -> bool:
    """One-time move of resume/sub_delay/audio_delay entries out of settings.ini."""
    global _legacy_playback_history_migrated
    if _legacy_playback_history_migrated:
        return False
    _legacy_playback_history_migrated = True

    settings = get_settings()
    prefixes = {
        RESUME_POS_PREFIX: "resume",
        SUB_DELAY_PER_FILE_PREFIX: "sub_delay",
        AUDIO_DELAY_PER_FILE_PREFIX: "audio_delay",
    }
    migrated = False
    for key in settings.allKeys():
        for prefix, field in prefixes.items():
            if not key.startswith(prefix):
                continue
            file_path = key[len(prefix):]
            if not file_path:
                continue
            try:
                value = float(settings.value(key, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            entry = data.setdefault(file_path, {})
            entry[field] = value
            entry.setdefault("ts", time.time())
            settings.remove(key)
            migrated = True
            break
    if migrated:
        settings.sync()
    return migrated


def _load_playback_history() -> dict:
    global _playback_history_cache
    if _playback_history_cache is None:
        data = _read_playback_history_file()
        if _migrate_legacy_playback_history(data):
            _prune_playback_history(data)
            _write_playback_history_file(data)
        _playback_history_cache = data
    return _playback_history_cache


def _save_playback_history(data: dict) -> None:
    global _playback_history_cache
    _playback_history_cache = data
    _write_playback_history_file(data)


def _prune_playback_history(data: dict) -> None:
    if len(data) <= PLAYBACK_HISTORY_MAX_ENTRIES:
        return
    ordered = sorted(data.items(), key=lambda kv: kv[1].get("ts", 0) if isinstance(kv[1], dict) else 0)
    excess = len(ordered) - PLAYBACK_HISTORY_MAX_ENTRIES
    for file_path, _ in ordered[:excess]:
        data.pop(file_path, None)


def _touch_playback_entry(data: dict, file_path: str) -> dict:
    entry = data.setdefault(file_path, {})
    entry["ts"] = time.time()
    return entry


def _remove_playback_field(data: dict, file_path: str, field: str) -> None:
    entry = data.get(file_path)
    if not entry:
        return
    entry.pop(field, None)
    if any(k in entry for k in ("resume", "sub_delay", "audio_delay")):
        entry["ts"] = time.time()
    else:
        data.pop(file_path, None)


def clear_playback_history() -> None:
    """Clears all stored resume positions and per-file sub/audio delays."""
    global _playback_history_cache, _legacy_playback_history_migrated
    _playback_history_cache = {}
    _legacy_playback_history_migrated = True
    path = _playback_history_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    # Also clean up any lingering legacy keys still in settings.ini.
    settings = get_settings()
    for key in settings.allKeys():
        if key.startswith(RESUME_POS_PREFIX) or key.startswith(SUB_DELAY_PER_FILE_PREFIX) or key.startswith(AUDIO_DELAY_PER_FILE_PREFIX):
            settings.remove(key)
    settings.sync()


def clear_downloaded_subtitles_cache() -> None:
    """Deletes locally cached subtitle files downloaded from OpenSubtitles."""
    subs_dir = get_user_data_dir() / "subtitles"
    if subs_dir.exists():
        shutil.rmtree(subs_dir, ignore_errors=True)

VALID_MPV_SCALES = {
    "bilinear",
    "bicubic",
    "lanczos",
    "lanczos2",
    "lanczos3",
    "lanczos4",
    "spline16",
    "spline36",
    "spline64",
    "ewa_lanczos",
    "ewa_lanczossharp",
    "ewa_lanczos4",
    "ewa_lanczos4sharpest",
    "mitchell",
    "hermite",
    "robidoux",
    "catmullrom",
    "gauss",
}

VALID_MPV_TONE_MAPPINGS = {
    "auto",
    "spline",
    "bt.2390",
    "bt.2446a",
    "st2094_40",
    "mobius",
    "hable",
    "reinhard",
    "drago",
    "clip",
    "gamma",
    "linear",
}

VALID_SCREENSHOT_FORMATS = {"png", "jpg", "jpeg", "webp", "jxl", "avif"}
VALID_SCREENSHOT_MODES = {"video", "subtitles", "window"}


def _normalize_screenshot_format(value) -> str:
    screenshot_format = _to_choice(value, "png", VALID_SCREENSHOT_FORMATS)
    return "jpg" if screenshot_format == "jpeg" else screenshot_format


def load_repeat(default: int = 0) -> int:
    """Load the repeat mode (0=off,1=one,2=all) from settings."""
    settings = get_settings()
    val = settings.value(REPEAT_KEY, default)
    try:
        num = int(val)
    except (TypeError, ValueError):
        return default
    if num not in {0, 1, 2}:
        return default
    return num


def save_repeat(value: int) -> None:
    settings = get_settings()
    settings.setValue(REPEAT_KEY, int(value))
    settings.sync()


def load_sub_settings():
    settings = get_settings()
    return {
        "font_size": _to_int(settings.value(SUB_FONT_SIZE_KEY, 55), 55, 1, 120),
        "color": str(settings.value(SUB_COLOR_KEY, "#FFFFFF")),
        "pos": _to_int(settings.value(SUB_POS_KEY, 100), 100, 0, 100),
        "delay": _to_float(settings.value(SUB_DELAY_KEY, 0.0), 0.0, -600.0, 600.0),
        "back_style": _to_choice(
            settings.value(SUB_BACK_STYLE_KEY, "Shadow"),
            "Shadow",
            {"None", "Shadow", "Outline", "Opaque Box"},
        ),
    }


def save_sub_settings(config: dict):
    settings = get_settings()
    if "font_size" in config: settings.setValue(SUB_FONT_SIZE_KEY, int(config["font_size"]))
    if "color" in config: settings.setValue(SUB_COLOR_KEY, str(config["color"]))
    if "pos" in config: settings.setValue(SUB_POS_KEY, int(config["pos"]))
    if "delay" in config: settings.setValue(SUB_DELAY_KEY, float(config["delay"]))
    if "back_style" in config: settings.setValue(SUB_BACK_STYLE_KEY, str(config["back_style"]))
    settings.sync()


# Video Adjustments
VIDEO_BRIGHTNESS_KEY = "video/brightness"
VIDEO_CONTRAST_KEY = "video/contrast"
VIDEO_SATURATION_KEY = "video/saturation"
VIDEO_GAMMA_KEY = "video/gamma"
VIDEO_ZOOM_KEY = "video/zoom"
VIDEO_ROTATE_KEY = "video/rotate"
VIDEO_MIRROR_HORIZONTAL_KEY = "video/mirror_horizontal"
VIDEO_MIRROR_VERTICAL_KEY = "video/mirror_vertical"
SEEK_THUMBNAIL_PREVIEW_KEY = "video/seek_thumbnail_preview"
VIDEO_HWDEC_KEY = "video/hwdec"
VIDEO_RENDERER_KEY = "video/renderer"
VIDEO_GPU_API_KEY = "video/gpu_api"


def load_video_settings():
    settings = get_settings()
    rotate = _to_int(settings.value(VIDEO_ROTATE_KEY, 0), 0)
    if rotate not in {0, 90, 180, 270}:
        rotate = 0
    return {
        "brightness": _to_int(settings.value(VIDEO_BRIGHTNESS_KEY, 0), 0, -100, 100),
        "contrast": _to_int(settings.value(VIDEO_CONTRAST_KEY, 0), 0, -100, 100),
        "saturation": _to_int(settings.value(VIDEO_SATURATION_KEY, 0), 0, -100, 100),
        "gamma": _to_int(settings.value(VIDEO_GAMMA_KEY, 0), 0, -100, 100),
        "zoom": _to_float(settings.value(VIDEO_ZOOM_KEY, 0.0), 0.0, -2.0, 10.0),
        "rotate": rotate,
        "mirror_horizontal": _to_bool(settings.value(VIDEO_MIRROR_HORIZONTAL_KEY, False), False),
        "mirror_vertical": _to_bool(settings.value(VIDEO_MIRROR_VERTICAL_KEY, False), False),
        "seek_thumbnail_preview": _to_bool(settings.value(SEEK_THUMBNAIL_PREVIEW_KEY, False), False),
        "hwdec": _to_choice(
            settings.value(VIDEO_HWDEC_KEY, "auto-safe"),
            "auto-safe",
            {"no", "auto", "auto-safe", "d3d11va", "nvdec"},
            allow_custom=True,
        ),
        "renderer": _to_choice(
            settings.value(VIDEO_RENDERER_KEY, "gpu"),
            "gpu",
            {"gpu", "gpu-next"},
            allow_custom=True,
        ),
        "gpu_api": _to_choice(
            settings.value(VIDEO_GPU_API_KEY, "auto"),
            "auto",
            {"auto", "vulkan", "d3d11", "opengl"},
            allow_custom=True,
        ),
        "scale": _to_choice(
            settings.value(VIDEO_SCALE_KEY, "ewa_lanczossharp"),
            "ewa_lanczossharp",
            VALID_MPV_SCALES,
            allow_custom=True,
        ),
        "cscale": _to_choice(
            settings.value(VIDEO_CSCALE_KEY, "ewa_lanczossharp"),
            "ewa_lanczossharp",
            VALID_MPV_SCALES,
            allow_custom=True,
        ),
        "dscale": _to_choice(
            settings.value(VIDEO_DSCALE_KEY, "mitchell"),
            "mitchell",
            VALID_MPV_SCALES,
            allow_custom=True,
        ),
        "deband": _to_bool(settings.value(VIDEO_DEBAND_KEY, True), True),
        "deband_iterations": _to_int(settings.value(VIDEO_DEBAND_ITERATIONS_KEY, 2), 2, 1, 4),
        "deband_threshold": _to_int(settings.value(VIDEO_DEBAND_THRESHOLD_KEY, 48), 48, 0, 128),
        "deband_range": _to_int(settings.value(VIDEO_DEBAND_RANGE_KEY, 16), 16, 1, 64),
        "tone_mapping": _to_choice(
            settings.value(VIDEO_TONE_MAPPING_KEY, "auto"),
            "auto",
            VALID_MPV_TONE_MAPPINGS,
            allow_custom=True,
        ),
        "screenshot_dir": str(settings.value(SCREENSHOT_DIR_KEY, _get_default_screenshot_dir())),
        "screenshot_use_default_dir": _to_bool(settings.value(SCREENSHOT_USE_DEFAULT_DIR_KEY, False), False),
        "screenshot_format": _normalize_screenshot_format(settings.value(SCREENSHOT_FORMAT_KEY, "png")),
        "screenshot_mode": _to_choice(
            settings.value(SCREENSHOT_MODE_KEY, "video"),
            "video",
            VALID_SCREENSHOT_MODES,
        ),
        "audio_normalize": load_audio_normalize(False),
    }


def save_video_settings(config: dict,
    changed_keys: set[str] | None = None,
    write_mpv_conf: bool = True,):
    settings = get_settings()
    if "brightness" in config: settings.setValue(VIDEO_BRIGHTNESS_KEY, int(config["brightness"]))
    if "contrast" in config: settings.setValue(VIDEO_CONTRAST_KEY, int(config["contrast"]))
    if "saturation" in config: settings.setValue(VIDEO_SATURATION_KEY, int(config["saturation"]))
    if "gamma" in config: settings.setValue(VIDEO_GAMMA_KEY, int(config["gamma"]))
    if "zoom" in config: settings.setValue(VIDEO_ZOOM_KEY, float(config["zoom"]))
    if "rotate" in config: settings.setValue(VIDEO_ROTATE_KEY, int(config["rotate"]))
    if "mirror_horizontal" in config: settings.setValue(VIDEO_MIRROR_HORIZONTAL_KEY, bool(config["mirror_horizontal"]))
    if "mirror_vertical" in config: settings.setValue(VIDEO_MIRROR_VERTICAL_KEY, bool(config["mirror_vertical"]))
    if "seek_thumbnail_preview" in config: settings.setValue(SEEK_THUMBNAIL_PREVIEW_KEY, bool(config["seek_thumbnail_preview"]))
    if "hwdec" in config: settings.setValue(VIDEO_HWDEC_KEY, config["hwdec"])
    if "renderer" in config: settings.setValue(VIDEO_RENDERER_KEY, config["renderer"])
    if "gpu_api" in config: settings.setValue(VIDEO_GPU_API_KEY, config["gpu_api"])
    if "scale" in config: settings.setValue(VIDEO_SCALE_KEY, str(config["scale"]))
    if "cscale" in config: settings.setValue(VIDEO_CSCALE_KEY, str(config["cscale"]))
    if "dscale" in config: settings.setValue(VIDEO_DSCALE_KEY, str(config["dscale"]))
    if "deband" in config: settings.setValue(VIDEO_DEBAND_KEY, bool(config["deband"]))
    if "deband_iterations" in config: settings.setValue(VIDEO_DEBAND_ITERATIONS_KEY, int(config["deband_iterations"]))
    if "deband_threshold" in config: settings.setValue(VIDEO_DEBAND_THRESHOLD_KEY, int(config["deband_threshold"]))
    if "deband_range" in config: settings.setValue(VIDEO_DEBAND_RANGE_KEY, int(config["deband_range"]))
    if "tone_mapping" in config: settings.setValue(VIDEO_TONE_MAPPING_KEY, str(config["tone_mapping"]))
    if "screenshot_dir" in config: settings.setValue(SCREENSHOT_DIR_KEY, str(config["screenshot_dir"]))
    if "screenshot_use_default_dir" in config: settings.setValue(SCREENSHOT_USE_DEFAULT_DIR_KEY, bool(config["screenshot_use_default_dir"]))
    if "screenshot_format" in config: settings.setValue(SCREENSHOT_FORMAT_KEY, str(config["screenshot_format"]))
    if "screenshot_mode" in config: settings.setValue(SCREENSHOT_MODE_KEY, str(config["screenshot_mode"]))
    if "audio_normalize" in config: save_audio_normalize(bool(config["audio_normalize"]))
    settings.sync()

    if not write_mpv_conf:
        return

    try:
        mpv_paths = ensure_mpv_power_user_layout()

        if changed_keys is None:
            mpv_config_patch = config
        else:
            mpv_config_patch = {
                key: config[key]
                for key in changed_keys
                if key in config
            }

        if mpv_config_patch:
            save_mpv_video_overrides(
                mpv_paths["mpv_conf_path"],
                mpv_config_patch,
            )

    except Exception:
        pass


def load_aspect_ratio(default: str = "auto") -> str:
    settings = get_settings()
    return str(settings.value(ASPECT_RATIO_KEY, default))


def save_aspect_ratio(ratio: str) -> None:
    settings = get_settings()
    settings.setValue(ASPECT_RATIO_KEY, ratio)
    settings.sync()


def save_resume_position(file_path: str, seconds: float) -> None:
    if not file_path:
        return
    data = _load_playback_history()
    seconds = float(seconds)
    if seconds <= MIN_RESUME_SECONDS:
        # Not worth resuming; drop any stale value instead of storing a useless one.
        _remove_playback_field(data, file_path, "resume")
    else:
        entry = _touch_playback_entry(data, file_path)
        entry["resume"] = seconds
    _prune_playback_history(data)
    _save_playback_history(data)


def load_resume_position(file_path: str) -> float:
    if not file_path:
        return 0.0
    entry = _load_playback_history().get(file_path)
    if not entry:
        return 0.0
    try:
        return float(entry.get("resume", 0.0))
    except (TypeError, ValueError):
        return 0.0


def save_sub_delay_for_file(file_path: str, seconds: float) -> None:
    if not file_path:
        return
    data = _load_playback_history()
    entry = _touch_playback_entry(data, file_path)
    entry["sub_delay"] = float(seconds)
    _prune_playback_history(data)
    _save_playback_history(data)


def load_sub_delay_for_file(file_path: str, default: float = 0.0) -> float:
    if not file_path:
        return float(default)
    entry = _load_playback_history().get(file_path)
    if not entry:
        return float(default)
    try:
        return float(entry.get("sub_delay", default))
    except (TypeError, ValueError):
        return float(default)


def load_audio_delay(default: float = 0.0) -> float:
    settings = get_settings()
    return _to_float(settings.value(AUDIO_DELAY_KEY, default), default, -600.0, 600.0)


def save_audio_delay(value: float) -> None:
    settings = get_settings()
    settings.setValue(AUDIO_DELAY_KEY, float(value))
    settings.sync()


def load_audio_normalize(default: bool = False) -> bool:
    settings = get_settings()
    return _to_bool(settings.value(AUDIO_NORMALIZE_KEY, default), default)


def save_audio_normalize(value: bool) -> None:
    settings = get_settings()
    settings.setValue(AUDIO_NORMALIZE_KEY, bool(value))
    settings.sync()


def save_audio_delay_for_file(file_path: str, seconds: float) -> None:
    if not file_path:
        return
    data = _load_playback_history()
    entry = _touch_playback_entry(data, file_path)
    entry["audio_delay"] = float(seconds)
    _prune_playback_history(data)
    _save_playback_history(data)


def load_audio_delay_for_file(file_path: str, default: float = 0.0) -> float:
    if not file_path:
        return float(default)
    entry = _load_playback_history().get(file_path)
    if not entry:
        return float(default)
    try:
        return float(entry.get("audio_delay", default))
    except (TypeError, ValueError):
        return float(default)


def load_language_setting(default: str = "") -> str:
    """Loads saved language code, returns empty string if none (auto-detect)."""
    settings = get_settings()
    return str(settings.value(LANGUAGE_KEY, default))


def save_language_setting(lang_code: str) -> None:
    settings = get_settings()
    settings.setValue(LANGUAGE_KEY, lang_code)
    settings.sync()


def load_pinned_settings():
    settings = get_settings()
    return {
        "controls": settings.value(PIN_CONTROLS_KEY, False, type=bool),
        "playlist": settings.value(PIN_PLAYLIST_KEY, False, type=bool)
    }


def save_pinned_settings(name: str, value: bool):
    settings = get_settings()
    if name == "controls":
        settings.setValue(PIN_CONTROLS_KEY, bool(value))
    elif name == "playlist":
        settings.setValue(PIN_PLAYLIST_KEY, bool(value))
    settings.sync()


def load_equalizer_settings():
    settings = get_settings()
    default_gains = [0] * 10
    enabled = settings.value(EQUALIZER_ENABLED_KEY, False, type=bool)
    gains_str = settings.value(EQUALIZER_GAINS_KEY, "")
    gains = default_gains
    if gains_str:
        try:
            parts = str(gains_str).split(",")
            if len(parts) == 10:
                gains = [int(p) for p in parts]
        except:
            pass
    return {"enabled": enabled, "gains": gains}

def save_equalizer_settings(enabled: bool, gains: list[int]):
    settings = get_settings()
    settings.setValue(EQUALIZER_ENABLED_KEY, enabled)
    settings.setValue(EQUALIZER_GAINS_KEY, ",".join(map(str, gains)))
    settings.sync()


def load_stream_auth_settings():
    settings = get_settings()
    return {
        "enabled": settings.value(STREAM_AUTH_ENABLED_KEY, False, type=bool),
        "username": str(settings.value(STREAM_AUTH_USERNAME_KEY, "")),
        "password": str(settings.value(STREAM_AUTH_PASSWORD_KEY, "")),
    }


def save_stream_auth_settings(enabled: bool, username: str, password: str):
    settings = get_settings()
    settings.setValue(STREAM_AUTH_ENABLED_KEY, bool(enabled))
    settings.setValue(STREAM_AUTH_USERNAME_KEY, str(username or ""))
    settings.setValue(STREAM_AUTH_PASSWORD_KEY, str(password or ""))
    settings.sync()


def load_stream_quality(default: str = "best") -> str:
    settings = get_settings()
    return str(settings.value(STREAM_QUALITY_KEY, default))


def save_stream_quality(value: str):
    settings = get_settings()
    settings.setValue(STREAM_QUALITY_KEY, str(value or "best"))
    settings.sync()


def load_restore_session_on_startup(default: bool = False) -> bool:
    settings = get_settings()
    return settings.value(SESSION_RESTORE_ON_STARTUP_KEY, default, type=bool)


def save_restore_session_on_startup(value: bool):
    settings = get_settings()
    settings.setValue(SESSION_RESTORE_ON_STARTUP_KEY, bool(value))
    settings.sync()


def load_import_include_audio(default: bool = True) -> bool:
    settings = get_settings()
    return settings.value(IMPORT_INCLUDE_AUDIO_KEY, default, type=bool)


def save_import_include_audio(value: bool):
    settings = get_settings()
    settings.setValue(IMPORT_INCLUDE_AUDIO_KEY, bool(value))
    settings.sync()


def load_opensubtitles_settings():
    settings = get_settings()
    default_lang = str(settings.value(OS_DEFAULT_LANG_KEY, "en") or "en").strip().lower()
    if not default_lang:
        default_lang = "en"
    return {
        "os_username": str(settings.value(OS_USERNAME_KEY, "")),
        "os_password": str(settings.value(OS_PASSWORD_KEY, "")),
        "os_default_lang": default_lang,
    }


def save_opensubtitles_settings(config: dict):
    settings = get_settings()
    if "os_username" in config:
        settings.setValue(OS_USERNAME_KEY, str(config["os_username"] or ""))
    if "os_password" in config:
        settings.setValue(OS_PASSWORD_KEY, str(config["os_password"] or ""))
    if "os_default_lang" in config:
        default_lang = str(config["os_default_lang"] or "en").strip().lower() or "en"
        settings.setValue(OS_DEFAULT_LANG_KEY, default_lang)
    settings.sync()
