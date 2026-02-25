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
