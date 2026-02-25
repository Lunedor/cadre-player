from PySide6.QtCore import QSettings
from .utils import get_user_data_path
import os

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


def _to_choice(value, default: str, allowed: set[str]) -> str:
    token = str(value or "").strip()
    if token in allowed:
        return token
    return default

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
RESUME_POS_PREFIX = "resume/"
PIN_CONTROLS_KEY = "player/pin_controls"
PIN_PLAYLIST_KEY = "player/pin_playlist"


def load_repeat(default: int = 0) -> int:
    settings = get_settings()
    value = settings.value(REPEAT_KEY, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
        "hwdec": _to_choice(
            settings.value(VIDEO_HWDEC_KEY, "auto-safe"),
            "auto-safe",
            {"no", "auto", "auto-safe", "d3d11va", "nvdec"},
        ),
        "renderer": _to_choice(
            settings.value(VIDEO_RENDERER_KEY, "gpu"),
            "gpu",
            {"gpu", "gpu-next"},
        ),
        "gpu_api": _to_choice(
            settings.value(VIDEO_GPU_API_KEY, "auto"),
            "auto",
            {"auto", "vulkan", "d3d11", "opengl"},
        ),
    }


def save_video_settings(config: dict):
    settings = get_settings()
    if "brightness" in config: settings.setValue(VIDEO_BRIGHTNESS_KEY, int(config["brightness"]))
    if "contrast" in config: settings.setValue(VIDEO_CONTRAST_KEY, int(config["contrast"]))
    if "saturation" in config: settings.setValue(VIDEO_SATURATION_KEY, int(config["saturation"]))
    if "gamma" in config: settings.setValue(VIDEO_GAMMA_KEY, int(config["gamma"]))
    if "zoom" in config: settings.setValue(VIDEO_ZOOM_KEY, float(config["zoom"]))
    if "rotate" in config: settings.setValue(VIDEO_ROTATE_KEY, int(config["rotate"]))
    if "hwdec" in config: settings.setValue(VIDEO_HWDEC_KEY, config["hwdec"])
    if "renderer" in config: settings.setValue(VIDEO_RENDERER_KEY, config["renderer"])
    if "gpu_api" in config: settings.setValue(VIDEO_GPU_API_KEY, config["gpu_api"])
    settings.sync()


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
    settings = get_settings()
    # Using path as key might have issues with some characters, but QSettings usually handles it
    # Better to use a hash or a safe string if we are worried, but let's try direct first.
    settings.setValue(f"{RESUME_POS_PREFIX}{file_path}", float(seconds))
    settings.sync()


def load_resume_position(file_path: str) -> float:
    if not file_path:
        return 0.0
    settings = get_settings()
    val = settings.value(f"{RESUME_POS_PREFIX}{file_path}", 0.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


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
