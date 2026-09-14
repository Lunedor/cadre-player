from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .i18n import tr
from .settings import save_update_last_success_check
from .ui.styles import DIALOG_STYLE
from .update_core import (
    UpdateError,
    download_checksum,
    download_file,
    expected_portable_zip_name,
    fetch_latest_release,
    is_newer_version,
    update_temp_dir,
    validate_zip_members,
    verify_sha256,
    verify_zip_integrity,
)
from .version import APP_NAME, APP_VERSION


class UpdateCheckSignals(QObject):
    update_available = Signal(object)
    current = Signal()
    error = Signal(str)


class UpdateCheckWorker(QThread):
    def __init__(self, manual: bool = False, parent=None):
        super().__init__(parent)
        self.manual = bool(manual)
        self.signals = UpdateCheckSignals()

    def run(self):
        try:
            release = fetch_latest_release()
            save_update_last_success_check(time.time())
            logging.info(
                "Update check completed: current=%s latest=%s",
                APP_VERSION,
                release.version,
            )
            if is_newer_version(release.version, APP_VERSION):
                self.signals.update_available.emit(release)
            else:
                self.signals.current.emit()
        except Exception as exc:
            logging.info("Update check failed: %s", exc)
            self.signals.error.emit(str(exc))


class UpdateDownloadSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(str, str)
    error = Signal(str)


class UpdateDownloadWorker(QThread):
    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.signals = UpdateDownloadSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        zip_path = None
        try:
            filename = expected_portable_zip_name(self.release.version)
            zip_path = update_temp_dir() / filename

            digest = None
            if self.release.checksum_asset is not None:
                logging.info("Downloading checksum asset: %s", self.release.checksum_asset.name)
                digest = download_checksum(self.release.checksum_asset, filename)
            else:
                logging.warning(
                    "SHA-256 asset missing for release %s; proceeding with ZIP integrity verification.",
                    self.release.version,
                )

            download_file(
                self.release.zip_asset.browser_download_url,
                zip_path,
                progress_callback=lambda done, total: self.signals.progress.emit(done, total),
                cancel_callback=lambda: self._cancelled,
            )

            if digest:
                verify_sha256(zip_path, digest)

            verify_zip_integrity(zip_path)
            validate_zip_members(zip_path)
            self.signals.finished.emit(str(zip_path), self.release.version)
        except Exception as exc:
            if zip_path is not None:
                try:
                    Path(zip_path).unlink(missing_ok=True)
                except OSError:
                    pass
            logging.exception("Update download/verification failed")
            self.signals.error.emit(str(exc))


class UpdateAvailableDialog(QDialog):
    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.setWindowTitle(tr("Update Available"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(360)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(tr("A new version of CadrePlayer is available."))
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: white;")
        layout.addWidget(title)

        size_text = ""
        if release.zip_asset.size:
            size_text = f"\n{tr('Download size')}: {release.zip_asset.size / (1024 * 1024):.1f} MB"
        details = QLabel(
            f"{tr('Current version')}: {APP_VERSION}\n"
            f"{tr('Available version')}: {release.version}"
            f"{size_text}"
        )
        details.setWordWrap(True)
        layout.addWidget(details)

        notes = QTextEdit(self)
        notes.setReadOnly(True)
        notes.setPlainText(str(release.body or tr("No release notes were provided.")))
        notes.setMinimumHeight(150)
        layout.addWidget(notes, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        later_btn = QPushButton(tr("Later"))
        later_btn.clicked.connect(self.reject)
        btn_row.addWidget(later_btn)
        update_btn = QPushButton(tr("Update now"))
        update_btn.setObjectName("PrimaryButton")
        update_btn.clicked.connect(self.accept)
        btn_row.addWidget(update_btn)
        layout.addLayout(btn_row)


class UpdateProgressDialog(QDialog):
    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.worker = UpdateDownloadWorker(release, self)
        self.setWindowTitle(tr("Updating CadrePlayer"))
        self.setMinimumWidth(460)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        self.label = QLabel(tr("Downloading CadrePlayer {}...").format(release.version))
        layout.addWidget(self.label)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.finished.connect(self._on_finished)
        self.worker.signals.error.connect(self._on_error)
        self._zip_path = ""
        self._version = ""

    def start(self) -> None:
        self.worker.start()

    def cancel(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.worker.cancel()
        self.label.setText(tr("Cancelling..."))

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            pct = max(0, min(100, int(downloaded * 100 / total)))
            self.progress.setValue(pct)
            self.label.setText(
                tr("Downloading CadrePlayer {}...").format(self.release.version)
                + f" {downloaded / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB"
            )
        else:
            self.progress.setRange(0, 0)
            self.label.setText(
                tr("Downloading CadrePlayer {}...").format(self.release.version)
                + f" {downloaded / (1024 * 1024):.1f} MB"
            )

    def _on_finished(self, zip_path: str, version: str) -> None:
        self._zip_path = zip_path
        self._version = version
        self.accept()

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, tr("Update Failed"), message or tr("Update failed."))
        self.reject()

    def result_payload(self) -> tuple[str, str]:
        return self._zip_path, self._version


def portable_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def launch_updater(zip_path: str, version: str, parent=None) -> bool:
    if not getattr(sys, "frozen", False):
        QMessageBox.information(
            parent,
            tr("Updates"),
            tr("Installing updates is disabled while running from source."),
        )
        return False

    install_dir = portable_install_dir()
    updater = install_dir / "CadrePlayerUpdater.exe"
    restart_exe = install_dir / "CadrePlayer.exe"
    if not updater.is_file():
        QMessageBox.warning(parent, tr("Update Failed"), tr("CadrePlayerUpdater.exe was not found."))
        return False

    args = [
        str(updater),
        "--pid",
        str(os.getpid()),
        "--install-dir",
        str(install_dir),
        "--zip",
        str(Path(zip_path).resolve()),
        "--restart-exe",
        str(restart_exe),
        "--version",
        str(version),
    ]
    try:
        subprocess.Popen(args, cwd=str(install_dir), close_fds=True)
    except OSError as exc:
        logging.exception("Failed to launch updater")
        QMessageBox.warning(parent, tr("Update Failed"), str(exc))
        return False

    logging.info("Launched updater for %s from %s", version, zip_path)
    return True
