from pathlib import Path

from .utils import get_user_data_dir


_MPV_CONF_TEMPLATE = """# Cadre Player - advanced libmpv configuration
# Add raw libmpv properties here.
# Examples:
# vo=gpu-next
# hwdec=auto-safe
# profile=high-quality
vo=gpu-next
gpu-api=vulkan
hwdec=auto
brightness=0
contrast=0
saturation=0
gamma=0
video-zoom=0.0
video-rotate=0
scale=ewa_lanczossharp
dscale=mitchell
cscale=ewa_lanczossharp
dither-depth=auto
deband=yes
deband-iterations=2
deband-threshold=48
deband-range=16
screenshot-format=png
screenshot-high-bit-depth=yes
tone-mapping=auto
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


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        return token in {"1", "true", "yes", "on"}
    return bool(value)


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
            elif key == "scale":
                overrides["scale"] = value
            elif key == "cscale":
                overrides["cscale"] = value
            elif key == "dscale":
                overrides["dscale"] = value
            elif key == "deband":
                overrides["deband"] = _to_bool(value)
            elif key == "deband-iterations":
                overrides["deband_iterations"] = _clamp_int(value, 2, 1, 16)
            elif key == "deband-threshold":
                overrides["deband_threshold"] = _clamp_int(value, 48, 0, 256)
            elif key == "deband-range":
                overrides["deband_range"] = _clamp_int(value, 16, 1, 256)
            elif key == "af":
                overrides["audio_filter"] = value
                if value.strip().lower() == "loudnorm":
                    overrides["audio_normalize"] = True
            elif key == "tone-mapping":
                overrides["tone_mapping"] = value
    except (OSError, UnicodeDecodeError):
        return {}
    return overrides


def _format_mpv_video_override_value(key: str, value):
    if key in {"brightness", "contrast", "saturation", "gamma", "rotate"}:
        return str(int(value))
    if key == "zoom":
        return str(float(value))
    if key == "deband":
        return "yes" if bool(value) else "no"
    if key in {"deband_iterations", "deband_threshold", "deband_range"}:
        return str(int(value))
    if key == "af":
        return str(value)
    return str(value)


def save_mpv_video_overrides(mpv_conf_path: str, config: dict) -> None:
    key_map = {
        "renderer": "vo",
        "gpu_api": "gpu-api",
        "hwdec": "hwdec",
        "brightness": "brightness",
        "contrast": "contrast",
        "saturation": "saturation",
        "gamma": "gamma",
        "zoom": "video-zoom",
        "rotate": "video-rotate",
        "scale": "scale",
        "cscale": "cscale",
        "dscale": "dscale",
        "deband": "deband",
        "deband_iterations": "deband-iterations",
        "deband_threshold": "deband-threshold",
        "deband_range": "deband-range",
        "tone_mapping": "tone-mapping",
        "audio_filter": "af",
    }
    values = {}
    remove_keys = set()
    for config_key, conf_key in key_map.items():
        if config_key not in config:
            continue
        try:
            if config_key == "audio_filter":
                if not str(config[config_key] or "").strip():
                    remove_keys.add(conf_key)
                    continue
            values[conf_key] = _format_mpv_video_override_value(config_key, config[config_key])
        except (TypeError, ValueError):
            continue

    if not values:
        return

    try:
        conf_path = Path(mpv_conf_path)
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        if not conf_path.exists():
            conf_path.write_text(_MPV_CONF_TEMPLATE, encoding="utf-8")

        existing_lines = conf_path.read_text(encoding="utf-8").splitlines()
        updated_lines = []
        seen_keys = set()

        for raw_line in existing_lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                updated_lines.append(raw_line)
                continue

            key, _ = line.split("=", 1)
            normalized_key = key.strip().lower()
            if normalized_key in remove_keys:
                seen_keys.add(normalized_key)
                continue
            if normalized_key in values:
                updated_lines.append(f"{normalized_key}={values[normalized_key]}")
                seen_keys.add(normalized_key)
            else:
                updated_lines.append(raw_line)

        for key, value in values.items():
            if key not in seen_keys:
                updated_lines.append(f"{key}={value}")

        conf_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return


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
