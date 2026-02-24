import faulthandler
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .utils import get_user_data_path


_FAULT_FILE = None


def setup_app_logging() -> Path:
    log_path = Path(get_user_data_path("logs.txt"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers if startup path is called more than once.
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler):
            existing = getattr(handler, "baseFilename", "")
            if existing and Path(existing) == log_path:
                return log_path

    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)

    logging.captureWarnings(True)
    _enable_fault_handler(log_path)
    _install_exception_hooks()
    logging.info(
        "Logging initialized. Python=%s log_path=%s",
        sys.version.split()[0],
        str(log_path),
    )
    return log_path


def _enable_fault_handler(log_path: Path) -> None:
    global _FAULT_FILE
    try:
        _FAULT_FILE = open(log_path, "a", encoding="utf-8")
        faulthandler.enable(_FAULT_FILE)
    except Exception:
        _FAULT_FILE = None


def _install_exception_hooks() -> None:
    def _log_exception(exc_type, exc_value, exc_tb):
        logging.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _log_exception

    if hasattr(sys, "unraisablehook"):
        def _log_unraisable(unraisable):
            logging.critical(
                "Unraisable exception: %s",
                getattr(unraisable, "err_msg", ""),
                exc_info=(
                    type(unraisable.exc_value),
                    unraisable.exc_value,
                    unraisable.exc_traceback,
                ),
            )

        sys.unraisablehook = _log_unraisable

    try:
        import threading

        def _thread_hook(args):
            logging.critical(
                "Unhandled thread exception in %s",
                getattr(args.thread, "name", "unknown"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_hook
    except Exception:
        logging.error("Could not install threading excepthook:\n%s", traceback.format_exc())
