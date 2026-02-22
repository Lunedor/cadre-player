import os
import sys
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


def run() -> int:
    # _HERE is where mpv-1.dll lives, so pass it directly.
    configure_windows_dlls(_HERE)

    # Deferred imports: must come AFTER bootstrap has patched the DLL search
    # path, otherwise `import mpv` inside player_window fires too early.
    if __package__ in (None, ""):
        from cadre_player.i18n import setup_i18n
        from cadre_player.player_window import ProOverlayPlayer
    else:
        from .i18n import setup_i18n
        from .player_window import ProOverlayPlayer

    setup_i18n()

    app = QApplication(sys.argv)

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

    player.show()
    player.load_startup_paths(sys.argv[1:])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
