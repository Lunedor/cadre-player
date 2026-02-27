import os
import sys
import threading
import logging
import shutil
import subprocess
if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "lunedor.cadre.player.1.0"
        )
from pathlib import Path


_HERE = Path(__file__).resolve().parent  # C:\Projects\py-video

# ── Package bootstrap ────────────────────────────────────────────────────────
# The project folder is named "py-video" (hyphen), which is not a valid Python
# identifier, so Python can never discover it on sys.path automatically.
# When this script is run directly (__package__ is None / ""), we manually
# register the folder as the "py_video" package in sys.modules so that every
# relative import inside player_window.py, playlist.py, etc. resolves
# correctly (they all do `from .something import …`).
if __package__ in (None, ""):
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "cadre_player",
        str(_HERE / "__init__.py"),
        submodule_search_locations=[str(_HERE)],
    )
    _pkg = _ilu.module_from_spec(_spec)
    _pkg.__path__ = [str(_HERE)]          # type: ignore[attr-defined]
    _pkg.__package__ = "cadre_player"     # type: ignore[attr-defined]
    sys.modules["cadre_player"] = _pkg
    _spec.loader.exec_module(_pkg)        # type: ignore[union-attr]

    from bootstrap import configure_windows_dlls
else:
    from .bootstrap import configure_windows_dlls

from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _HERE


def _probe_tool_version(binary_name: str) -> str:
    exe = shutil.which(binary_name)
    if not exe:
        return "not found"
    try:
        run_kwargs = {}
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if flags:
                run_kwargs["creationflags"] = flags
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            **run_kwargs,
        )
        raw = (proc.stdout or proc.stderr or "").splitlines()
        first_line = raw[0].strip() if raw else ""
        return f"{exe} ({first_line or 'version unknown'})"
    except Exception as e:
        return f"{exe} (version probe failed: {e})"


def _log_runtime_tool_diagnostics() -> None:
    try:
        import yt_dlp as _yt_dlp

        py_yt_dlp = getattr(_yt_dlp.version, "__version__", "unknown")
    except Exception as e:
        py_yt_dlp = f"unavailable ({e})"
    base_dir = _runtime_base_dir()
    bundled_deno = base_dir / "deno.exe"
    bundled_ytdlp = base_dir / "yt-dlp.exe"
    bundled_deno_vendor = base_dir / "vendor" / "deno.exe"
    bundled_ytdlp_vendor = base_dir / "vendor" / "yt-dlp.exe"
    deno_on_path = shutil.which("deno") or ""
    ytdlp_on_path = shutil.which("yt-dlp") or ""
    path_preview = os.environ.get("PATH", "").split(os.pathsep)[:4]
    logging.info("Runtime PATH head=%s", path_preview)
    logging.info(
        "Bundled binary status: deno=%s deno_vendor=%s yt-dlp=%s yt-dlp_vendor=%s",
        bundled_deno.exists(),
        bundled_deno_vendor.exists(),
        bundled_ytdlp.exists(),
        bundled_ytdlp_vendor.exists(),
    )
    logging.info(
        "Resolved executables: deno=%s bundled=%s yt-dlp=%s bundled=%s",
        deno_on_path or "not found",
        deno_on_path
        and str(Path(deno_on_path).resolve()).casefold()
        in {
            str(bundled_deno.resolve()).casefold(),
            str(bundled_deno_vendor.resolve()).casefold(),
        },
        ytdlp_on_path or "not found",
        ytdlp_on_path
        and str(Path(ytdlp_on_path).resolve()).casefold()
        in {
            str(bundled_ytdlp.resolve()).casefold(),
            str(bundled_ytdlp_vendor.resolve()).casefold(),
        },
    )
    logging.info("Runtime yt-dlp (python package)=%s", py_yt_dlp)
    logging.info("Runtime tool deno=%s", _probe_tool_version("deno"))
    logging.info("Runtime tool yt-dlp cli=%s", _probe_tool_version("yt-dlp"))


def _prepend_runtime_paths() -> None:
    base_dir = _runtime_base_dir()
    candidates = [str(base_dir), str(base_dir / "vendor")]
    current = os.environ.get("PATH", "")
    existing = current.split(os.pathsep) if current else []
    merged = []
    seen = set()
    for path in candidates + existing:
        norm = str(path).strip()
        if not norm:
            continue
        key = os.path.normcase(norm)
        if key in seen:
            continue
        seen.add(key)
        merged.append(norm)
    os.environ["PATH"] = os.pathsep.join(merged)


def run() -> int:
    _prepend_runtime_paths()
    # _HERE is where mpv-1.dll lives, so pass it directly.
    configure_windows_dlls(_HERE)

    # Deferred imports: must come AFTER bootstrap has patched the DLL search
    # path, otherwise `import mpv` inside player_window fires too early.
    if __package__ in (None, ""):
        from cadre_player.i18n import setup_i18n
        from cadre_player.app_logging import setup_app_logging
        from cadre_player.player_window import ProOverlayPlayer
    else:
        from .i18n import setup_i18n
        from .app_logging import setup_app_logging
        from .player_window import ProOverlayPlayer

    setup_app_logging()
    _log_runtime_tool_diagnostics()
    setup_i18n()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    from ui.icons import get_app_icon
    app.setWindowIcon(get_app_icon())

    SERVER_NAME = "cadre_player_single_instance_server"
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)

    if socket.waitForConnected(300):
        args = sys.argv[1:]
        if args:
            message = "\n".join(args).encode("utf-8")
            socket.write(message)
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            socket.waitForDisconnected(500)
        return 0

    server = QLocalServer()
    server.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    player = ProOverlayPlayer()

    def on_new_connection() -> None:
        client = server.nextPendingConnection()
        if client:
            if client.bytesAvailable() == 0:
                client.waitForReadyRead(500)
            data = client.readAll().data().decode("utf-8")
            paths = data.split("\n") if data else []
            paths = [p for p in paths if p.strip()]
            if paths:
                player.load_startup_paths(paths)
                if player.isMinimized():
                    player.showNormal()
                player.activateWindow()
                player.raise_()
            client.disconnectFromServer()

    server.newConnection.connect(on_new_connection)

    def _quit_watchdog() -> None:
        killer = threading.Timer(3.0, lambda: os._exit(0))
        killer.daemon = True
        killer.start()

    app.aboutToQuit.connect(_quit_watchdog)

    player.show()
    player.load_startup_paths(sys.argv[1:])

    exit_code = app.exec()

    try:
        server.close()
        server.removeServer(SERVER_NAME)
    except Exception as e:
        logging.debug("Server cleanup skipped: %s", e)

    lingering = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and t.is_alive() and not t.daemon
    ]
    for t in lingering:
        try:
            t.join(timeout=0.25)
        except Exception as e:
            logging.debug("Thread join skipped for %s: %s", getattr(t, "name", "unknown"), e)
    lingering = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and t.is_alive() and not t.daemon
    ]
    if lingering:
        try:
            logging.warning(
                "Forcing process exit due to lingering non-daemon threads: %s",
                [getattr(t, "name", "unknown") for t in lingering],
            )
        except Exception as e:
            logging.debug("Lingering-thread warning failed: %s", e)
        os._exit(int(exit_code))

    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(run())
