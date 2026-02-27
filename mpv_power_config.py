from pathlib import Path

from .utils import get_user_data_dir


_MPV_CONF_TEMPLATE = """# Cadre Player - advanced libmpv configuration
# Add raw libmpv properties here.
# Examples:
# vo=gpu-next
# hwdec=auto-safe
# profile=high-quality
"""

_SCRIPTS_README_TEMPLATE = """Cadre Player - mpv scripts folder

Drop native mpv scripts here to extend playback behavior.
Supported formats include:
- .lua
- .js

libmpv will auto-load scripts from this folder at startup.
"""


def _clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(min_value, min(max_value, number))


def _clamp_float(value, default: float, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(min_value, min(max_value, number))


def _normalize_rotate(value) -> int:
    try:
        deg = int(value)
    except (TypeError, ValueError):
        return 0
    deg %= 360
    if deg in {0, 90, 180, 270}:
        return deg
    return 0


def load_mpv_video_overrides(mpv_conf_path: str) -> dict:
    overrides: dict = {}
    try:
        conf_path = Path(mpv_conf_path)
        if not conf_path.exists():
            return overrides

        for raw_line in conf_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "vo" and value in {"gpu", "gpu-next"}:
                overrides["renderer"] = value
            elif key == "gpu-api" and value in {"auto", "vulkan", "d3d11", "opengl"}:
                overrides["gpu_api"] = value
            elif key == "hwdec" and value in {"no", "auto", "auto-safe", "d3d11va", "nvdec"}:
                overrides["hwdec"] = value
            elif key == "brightness":
                overrides["brightness"] = _clamp_int(value, 0, -100, 100)
            elif key == "contrast":
                overrides["contrast"] = _clamp_int(value, 0, -100, 100)
            elif key == "saturation":
                overrides["saturation"] = _clamp_int(value, 0, -100, 100)
            elif key == "gamma":
                overrides["gamma"] = _clamp_int(value, 0, -100, 100)
            elif key == "video-zoom":
                overrides["zoom"] = _clamp_float(value, 0.0, -2.0, 10.0)
            elif key == "video-rotate":
                overrides["rotate"] = _normalize_rotate(value)
    except (OSError, UnicodeDecodeError):
        return {}
    return overrides

def ensure_mpv_power_user_layout() -> dict:
    config_dir = Path(get_user_data_dir())
    config_dir.mkdir(parents=True, exist_ok=True)

    mpv_conf_path = config_dir / "mpv.conf"
    if not mpv_conf_path.exists():
        mpv_conf_path.write_text(_MPV_CONF_TEMPLATE, encoding="utf-8")

    scripts_dir = config_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    readme_path = scripts_dir / "_README.txt"
    if not readme_path.exists():
        readme_path.write_text(_SCRIPTS_README_TEMPLATE, encoding="utf-8")

    return {
        "config_dir": str(config_dir),
        "mpv_conf_path": str(mpv_conf_path),
        "scripts_dir": str(scripts_dir),
    }
