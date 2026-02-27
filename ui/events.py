import math
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QDateTime, QEvent, QPoint, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QWidget,
)

from .dialogs import SubtitleSettingsDialog, URLInputDialog, VideoSettingsDialog
from .icons import (
    icon_exit_fullscreen,
    icon_fullscreen,
    icon_maximize,
    icon_next_track,
    icon_pause,
    icon_play,
    icon_prev_track,
    icon_repeat,
    icon_restore,
    icon_shuffle,
    icon_stop,
    icon_volume,
    icon_volume_muted,
)
from .menus import create_main_context_menu, create_playlist_context_menu
from ..i18n import tr
from ..mpv_power_config import ensure_mpv_power_user_layout
from ..settings import (
    load_equalizer_settings,
    load_sub_settings,
    load_video_settings,
    save_restore_session_on_startup,
    save_aspect_ratio,
    save_language_setting,
    save_muted,
    save_pinned_settings,
    save_repeat,
    save_shuffle,
    save_sub_settings,
    save_stream_quality,
    save_video_settings,
    save_volume,
)
from ..utils import REPEAT_OFF, REPEAT_ONE, SPEED_STEPS, format_duration, is_stream_url, reveal_path

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

YTDLP_REMOTE_COMPONENTS = "ejs:github"
YTDLP_FMT_PREFIX = "fmt:"


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(h in host for h in ("youtube.com", "youtu.be", "music.youtube.com"))


class UIEventsMixin:
    def _safe_player_float(self, attr: str, default: float = 0.0) -> float:
        try:
            raw = getattr(self.player, attr, None)
        except (AttributeError, RuntimeError):
            return float(default)
        try:
            if raw is None:
                return float(default)
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    def _safe_set_player_attr(self, attr: str, value) -> bool:
        try:
            setattr(self.player, attr, value)
            return True
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _apply_video_mirror_filters(self):
        # Apply mirror/flip using plain vf filters for maximum compatibility.
        h_enabled = bool(getattr(self, "_video_mirror_horizontal", False))
        v_enabled = bool(getattr(self, "_video_mirror_vertical", False))
        logging.info("Applying mirror filters: h=%s v=%s", h_enabled, v_enabled)
        mirror_enabled = h_enabled or v_enabled

        # Some hwdec modes can bypass vf filters; use copy-back while mirroring.
        if mirror_enabled:
            prev_hwdec = getattr(self, "_mirror_prev_hwdec", None)
            if prev_hwdec is None:
                try:
                    self._mirror_prev_hwdec = str(getattr(self.player, "hwdec", "") or "")
                except Exception:
                    self._mirror_prev_hwdec = ""
            try:
                current_hwdec = str(getattr(self.player, "hwdec", "") or "")
            except Exception:
                current_hwdec = ""
            if current_hwdec not in {"auto-copy", "no"}:
                if self._safe_set_player_attr("hwdec", "auto-copy"):
                    logging.info("Mirror: hwdec switched to auto-copy (was %r)", current_hwdec)
        else:
            prev_hwdec = getattr(self, "_mirror_prev_hwdec", None)
            if prev_hwdec is not None:
                if self._safe_set_player_attr("hwdec", prev_hwdec):
                    logging.info("Mirror: hwdec restored to %r", prev_hwdec)
                self._mirror_prev_hwdec = None
        # Remove existing mirror filters first; repeat a few times in case both exist.
        for _ in range(3):
            for name in ("hflip", "vflip"):
                try:
                    self.player.command("vf", "remove", name)
                except Exception:
                    pass

        if h_enabled:
            try:
                self.player.command("vf", "add", "hflip")
                logging.info("Mirror filter added: hflip")
            except Exception as e:
                logging.warning("Mirror filter add failed (hflip): %s", e)
        if v_enabled:
            try:
                self.player.command("vf", "add", "vflip")
                logging.info("Mirror filter added: vflip")
            except Exception as e:
                logging.warning("Mirror filter add failed (vflip): %s", e)

        try:
            vf_state = self.player.command("get_property_native", "vf")
            logging.info("Mirror vf after apply: %r", vf_state)
        except Exception as e:
            logging.debug("Mirror vf read failed: %s", e)

    def _save_zoom_setting(self):
        config = load_video_settings()
        config["zoom"] = self.window_zoom
        save_video_settings(config)

    def update_transport_icons(self):
        if self._is_shutting_down:
            return
        self.prev_btn.setIcon(icon_prev_track(22))
        self.next_btn.setIcon(icon_next_track(22))
        self.stop_btn.setIcon(icon_stop(22))
        self.play_btn.setIcon(icon_play(22) if self._cached_paused else icon_pause(22))
        self.prev_btn.setText("")
        self.next_btn.setText("")
        self.stop_btn.setText("")
        self.play_btn.setText("")

    def update_mute_icon(self):
        pixmap = icon_volume_muted(22) if self._cached_muted else icon_volume(22)
        self.mute_btn.setIcon(QIcon(pixmap))
        self.mute_btn.setText("")
        if hasattr(self, "popup_mute_btn"):
            self.popup_mute_btn.setIcon(QIcon(pixmap))
            self.popup_mute_btn.setText("")

    def update_fullscreen_icon(self):
        pixmap = icon_exit_fullscreen(24) if self.isFullScreen() else icon_fullscreen(24)
        self.fullscreen_btn.setIcon(QIcon(pixmap))

    def on_volume_changed(self, value: int):
        self.player.volume = value
        save_volume(value)
        self.show_status_overlay(tr("Volume: {}%").format(value))

    def update_mode_buttons(self):
        self.shuffle_btn.setChecked(self.shuffle_enabled)
        self.shuffle_btn.setIcon(QIcon(icon_shuffle(22, off=not self.shuffle_enabled)))

        repeat_tip = (tr("Repeat Off"), tr("Repeat One"), tr("Repeat All"))[self.repeat_mode]
        self.repeat_btn.setToolTip(repeat_tip)
        self.repeat_btn.setChecked(self.repeat_mode != REPEAT_OFF)
        self.repeat_btn.setIcon(
            QIcon(
                icon_repeat(
                    22,
                    one=(self.repeat_mode == REPEAT_ONE),
                    off=(self.repeat_mode == REPEAT_OFF),
                )
            )
        )

    def show_settings_menu(self):
        menu = create_main_context_menu(self, QPoint())
        if menu:
            self._exec_menu_on_top(
                menu,
                self.settings_btn.mapToGlobal(self.settings_btn.rect().topLeft()),
            )

    def _exec_menu_on_top(self, menu: QMenu, global_pos: QPoint):
        if not menu:
            return None
        had_title_bar = bool(hasattr(self, "title_bar") and self.title_bar.isVisible())
        self._context_menu_open = True
        mouse_timer_was_active = bool(hasattr(self, "mouse_timer") and self.mouse_timer.isActive())
        if mouse_timer_was_active:
            self.mouse_timer.stop()
        if had_title_bar:
            self.title_bar.hide()
        try:
            menu.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            menu.setAttribute(Qt.WA_AlwaysStackOnTop, True)
            menu.raise_()
        except (RuntimeError, TypeError) as e:
            logging.debug("menu on-top setup failed: %s", e)
        try:
            return menu.exec(global_pos)
        finally:
            self._context_menu_open = False
            if mouse_timer_was_active:
                self.mouse_timer.start()
            if had_title_bar:
                QTimer.singleShot(0, self._restore_title_bar_after_menu)

    def _prepare_modal_window(self, widget):
        if widget is None:
            return
        try:
            widget.setWindowModality(Qt.ApplicationModal)
        except (RuntimeError, TypeError) as e:
            logging.debug("prepare modal: setWindowModality failed: %s", e)
        try:
            widget.setWindowFlag(Qt.WindowStaysOnTopHint, bool(self.always_on_top))
        except (RuntimeError, TypeError) as e:
            logging.debug("prepare modal: setWindowFlag failed: %s", e)

    def _exec_modal(self, widget):
        self._prepare_modal_window(widget)
        try:
            widget.raise_()
        except RuntimeError as e:
            logging.debug("exec modal: raise failed: %s", e)
        return widget.exec()

    def _run_file_dialog(self, dialog: QFileDialog) -> list[str]:
        result = self._exec_modal(dialog)
        if result == QFileDialog.Accepted:
            try:
                return dialog.selectedFiles()
            except RuntimeError as e:
                logging.debug("file dialog selectedFiles failed: %s", e)
                return []
        return []

    def _show_message(
        self,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButtons = QMessageBox.Ok,
        default_button: QMessageBox.StandardButton = QMessageBox.NoButton,
    ) -> QMessageBox.StandardButton:
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        if default_button != QMessageBox.NoButton:
            box.setDefaultButton(default_button)
        return QMessageBox.StandardButton(self._exec_modal(box))

    def _restore_title_bar_after_menu(self):
        if not hasattr(self, "title_bar"):
            return
        if QApplication.activeModalWidget() is not None:
            return
        if self._context_menu_open or self.isFullScreen() or not self._is_app_focused():
            return
        self._sync_title_bar_geometry()
        self.title_bar.show()
        self.title_bar.raise_()

    def _sync_title_bar_geometry(self):
        if not hasattr(self, "title_bar") or self.isMinimized():
            return
        width = self.width()
        height = 32
        pos = self.mapToGlobal(QPoint(0, 0))
        self.title_bar.setGeometry(pos.x(), pos.y(), width, height)

    def _is_app_focused(self) -> bool:
        if self.isMinimized():
            return False
        if self.isActiveWindow():
            return True
        active_win = QApplication.activeWindow()
        if active_win is None:
            try:
                return self.rect().contains(self.mapFromGlobal(QCursor.pos()))
            except RuntimeError:
                return False
        app_windows = [self] + [
            getattr(self, attr)
            for attr in ["title_bar", "overlay", "playlist_overlay", "speed_overlay"]
            if hasattr(self, attr)
        ]
        return any(
            active_win == win or win.isAncestorOf(active_win)
            for win in app_windows
        )

    def _sync_overlay_geometry(self):
        if not hasattr(self, "overlay"):
            return

        pad = 14
        height = 64
        inset = 8

        pill_w = min(900, self.width() - pad * 2 - inset * 2)
        overlay_w = pill_w + inset * 2

        geometry = self.geometry()
        x = geometry.x() + (self.width() - overlay_w) // 2
        y = geometry.y() + geometry.height() - height - pad

        self.overlay.setGeometry(x, y, overlay_w, height)
        self.overlay.panel.setGeometry(inset, 0, pill_w, height)

    def _sync_playlist_overlay_geometry(self):
        if not hasattr(self, "playlist_overlay"):
            return

        width = 400
        height = self.height() - 88
        geometry = self.geometry()

        x = geometry.x() + geometry.width() - width
        y = geometry.y()

        self.playlist_overlay.setGeometry(x, y, width, height)
        self.playlist_overlay.panel.setGeometry(0, 0, width, height)

    def _sync_speed_indicator_geometry(self):
        if not hasattr(self, "speed_overlay"):
            return

        metrics = self.speed_overlay.label.fontMetrics()
        text = self.speed_overlay.label.text()
        text_width = metrics.horizontalAdvance(text) if text else 0
        width = max(112, text_width + 40)

        height = 42
        inner_x = (self.width() - width) // 2
        y = 30
        geometry = self.geometry()
        x = geometry.x() + inner_x
        global_y = geometry.y() + y
        self.speed_overlay.setGeometry(x, global_y, width, height)
        self.speed_overlay.panel.setGeometry(0, 0, width, height)
        self.speed_overlay.label.setGeometry(0, 0, width, height)

    def _enforce_overlay_stack(self):
        if not getattr(self, "always_on_top", False):
            return
        if self.isMinimized():
            return
        if QApplication.activeModalWidget() is not None:
            return
        if self._context_menu_open:
            return
        try:
            self.raise_()
        except RuntimeError:
            pass
        for attr in ("overlay", "speed_overlay", "playlist_overlay", "title_bar"):
            win = getattr(self, attr, None)
            if win is None or not win.isVisible():
                continue
            try:
                win.raise_()
            except RuntimeError:
                pass

    def _sync_overlay_topmost_flags(self):
        enabled = bool(self.always_on_top)
        for attr in ("overlay", "speed_overlay", "playlist_overlay", "title_bar"):
            win = getattr(self, attr, None)
            if win is None:
                continue
            try:
                was_visible = win.isVisible()
                win.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
                if was_visible:
                    win.show()
            except RuntimeError:
                pass

    def check_mouse_pos(self):
        if self.isMinimized():
            for attr in ("title_bar", "overlay", "playlist_overlay", "speed_overlay"):
                win = getattr(self, attr, None)
                if win and win.isVisible():
                    win.hide()
            if hasattr(self, "resize_corner_hint"):
                self.resize_corner_hint.hide()
            return
        if not self._is_app_focused():
            if hasattr(self, "title_bar") and self.title_bar.isVisible():
                self.title_bar.hide()
            if hasattr(self, "resize_corner_hint"):
                self.resize_corner_hint.hide()
            return
        if getattr(self, "_fullscreen_transition_active", False):
            return

        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        volume_popup_active = hasattr(self, "volume_popup") and self.volume_popup.isVisible()

        margin = 20
        in_resize_area = (
            self.rect().contains(local_pos)
            and local_pos.x() >= self.width() - margin
            and local_pos.y() >= self.height() - margin
        )
        is_resizing = getattr(self, "_is_resizing", False)

        if in_resize_area or is_resizing:
            self.cursor_idle_time = 0
            if self.cursor().shape() != Qt.SizeFDiagCursor:
                self.setCursor(Qt.SizeFDiagCursor)
                self.video_container.setCursor(Qt.SizeFDiagCursor)
            if hasattr(self, "resize_corner_hint"):
                self.resize_corner_hint.show()
                self.resize_corner_hint.raise_()
        else:
            if global_pos != self.last_cursor_global_pos:
                self.last_cursor_global_pos = global_pos
                self.cursor_idle_time = 0
                if self.cursor().shape() != Qt.ArrowCursor:
                    self.setCursor(Qt.ArrowCursor)
                    self.video_container.setCursor(Qt.ArrowCursor)
                if hasattr(self, "resize_corner_hint"):
                    self.resize_corner_hint.hide()
            else:
                if self.rect().contains(local_pos):
                    self.cursor_idle_time += 100
                    if self.cursor_idle_time >= 2500:
                        if self.cursor().shape() != Qt.BlankCursor:
                            self.setCursor(Qt.BlankCursor)
                            self.video_container.setCursor(Qt.BlankCursor)
                            if hasattr(self, "resize_corner_hint"):
                                self.resize_corner_hint.hide()
                else:
                    self.cursor_idle_time = 0
                    if hasattr(self, "resize_corner_hint"):
                        self.resize_corner_hint.hide()

        if self.pinned_controls:
            if not self.overlay.isVisible():
                self._sync_overlay_geometry()
                self.overlay.show()
        elif volume_popup_active:
            if not self.overlay.isVisible():
                self._sync_overlay_geometry()
                self.overlay.show()
        elif self.rect().contains(local_pos) and local_pos.y() > (self.height() - 90):
            if not self.overlay.isVisible():
                self._sync_overlay_geometry()
                self.overlay.show()
        elif self.overlay.isVisible():
            if self.current_index < 0 or self._cached_paused:
                pass
            elif local_pos.y() <= (self.height() - 90):
                self.overlay.hide()
                if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
                    self.volume_popup.hide()
                if hasattr(self, "hide_seek_thumbnail_preview"):
                    self.hide_seek_thumbnail_preview()

        if (
            hasattr(self, "overlay")
            and hasattr(self, "seek_thumb_preview")
            and not self.overlay.isVisible()
            and self.seek_thumb_preview.isVisible()
        ):
            self.hide_seek_thumbnail_preview()

        if self.pinned_playlist:
            if not self.playlist_overlay.isVisible():
                self._sync_playlist_overlay_geometry()
                self.playlist_overlay.show()
                self.playlist_overlay.raise_()
        elif self.rect().contains(local_pos) and local_pos.x() > (self.width() - 20):
            is_title_bar_visible = hasattr(self, "title_bar") and self.title_bar.isVisible()
            if not self.playlist_overlay.isVisible() and not is_title_bar_visible:
                self._sync_playlist_overlay_geometry()
                self.playlist_overlay.show()
                self.playlist_overlay.raise_()
                self.playlist_widget.updateGeometries()
                QTimer.singleShot(1, self.playlist_widget.update)

        if self.playlist_overlay.isVisible() and not self.pinned_playlist:
            playlist_rect = self.playlist_overlay.geometry()
            if global_pos.x() > (playlist_rect.x() - 40):
                self.playlist_auto_hide_timer.stop()
            elif not self.playlist_auto_hide_timer.isActive():
                self.playlist_auto_hide_timer.start()

        if self._context_menu_open:
            if self.title_bar.isVisible():
                self.title_bar.hide()
        elif self.current_index < 0:
            if not self.title_bar.isVisible() and not self.isFullScreen():
                self._sync_title_bar_geometry()
                self.title_bar.show()
                self.title_bar.raise_()
        else:
            if self.rect().contains(local_pos) and local_pos.y() < 60:
                if not self.title_bar.isVisible() and not self.isFullScreen():
                    self._sync_title_bar_geometry()
                    self.title_bar.show()
                    self.title_bar.raise_()
            elif self.title_bar.isVisible():
                if local_pos.y() >= 60 or not self.rect().contains(local_pos):
                    self.title_bar.hide()

        if self.isFullScreen() and self.title_bar.isVisible():
            self.title_bar.hide()
        self._enforce_overlay_stack()

    def resizeEvent(self, event):
        self.video_container.setGeometry(0, 0, self.width(), self.height())
        self.background_widget.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, "resize_corner_hint"):
            self.resize_corner_hint.move(
                max(0, self.video_container.width() - self.resize_corner_hint.width()),
                max(0, self.video_container.height() - self.resize_corner_hint.height()),
            )
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_speed_indicator_geometry()
        self._sync_title_bar_geometry()
        self._enforce_overlay_stack()
        QMainWindow.resizeEvent(self, event)

    def moveEvent(self, event):
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_speed_indicator_geometry()
        self._sync_title_bar_geometry()
        self._enforce_overlay_stack()
        QMainWindow.moveEvent(self, event)

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange:
            if not self._is_app_focused() and hasattr(self, "title_bar"):
                self.title_bar.hide()

        if event.type() == QEvent.WindowStateChange:
            self.update_fullscreen_icon()
            if self.isMinimized():
                for attr in ("title_bar", "overlay", "playlist_overlay", "speed_overlay"):
                    win = getattr(self, attr, None)
                    if win and win.isVisible():
                        win.hide()
                if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
                    self.volume_popup.hide()
            if hasattr(self, "title_bar"):
                if self.isMaximized():
                    self.title_bar.max_btn.setIcon(QIcon(icon_restore(18)))
                else:
                    self.title_bar.max_btn.setIcon(QIcon(icon_maximize(18)))

        QMainWindow.changeEvent(self, event)

    def open_about_dialog(self):
        from .dialogs import AboutDialog

        dialog = AboutDialog(self)
        self._exec_modal(dialog)

    def toggle_window_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.title_bar.max_btn.setIcon(QIcon(icon_maximize(18)))
        else:
            self.showMaximized()
            self.title_bar.max_btn.setIcon(QIcon(icon_restore(18)))

    def toggle_pin_controls(self):
        self.pinned_controls = not self.pinned_controls
        save_pinned_settings("controls", self.pinned_controls)
        if self.pinned_controls:
            self._sync_overlay_geometry()
            self.overlay.show()
            self.show_status_overlay(tr("Controls Pinned"))
        else:
            self.show_status_overlay(tr("Controls Unpinned"))

    def toggle_pin_playlist(self):
        self.pinned_playlist = not self.pinned_playlist
        save_pinned_settings("playlist", self.pinned_playlist)
        if self.pinned_playlist:
            self._sync_playlist_overlay_geometry()
            self.playlist_overlay.show()
            self.playlist_overlay.raise_()
            self.show_status_overlay(tr("Playlist Pinned"))
        else:
            self.show_status_overlay(tr("Playlist Unpinned"))

    def show_add_menu(self):
        self._exec_menu_on_top(
            self.add_menu,
            self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()),
        )

    def show_add_menu_main(self):
        pos = self.add_main_btn.mapToGlobal(self.add_main_btn.rect().topLeft())
        pos.setY(pos.y() - self.add_menu.sizeHint().height())
        self._exec_menu_on_top(self.add_menu, pos)

    def apply_panel_shadow(self, panel: QWidget, blur: int, offset_y: int):
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, offset_y)
        shadow.setColor(QColor(0, 0, 0, 180))
        panel.setGraphicsEffect(shadow)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible():
                return QMainWindow.mouseDoubleClickEvent(self, event)

            pos = event.position().toPoint()
            if self.video_container.geometry().contains(pos):
                self.toggle_fullscreen()
                event.accept()
                return

        QMainWindow.mouseDoubleClickEvent(self, event)

    def open_playlist_context_menu(self, pos):
        result = create_playlist_context_menu(self, pos)
        if not result:
            return
        menu, indices, path, play_act, rem_act, del_act, rev_act, copy_act = result

        action = self._exec_menu_on_top(
            menu,
            self.playlist_widget.viewport().mapToGlobal(pos),
        )
        if action == play_act:
            self.current_index = indices[0]
            self.play_current()
        elif action == rem_act:
            self.remove_playlist_indices(indices)
        elif action == del_act:
            self.delete_to_trash(indices)
        elif action == rev_act:
            self.reveal_path(path)
        elif action == copy_act:
            if len(indices) == 1:
                QApplication.clipboard().setText(path)
            else:
                paths_text = "\n".join([self.playlist[i] for i in indices])
                QApplication.clipboard().setText(paths_text)

    def reveal_path(self, path: str):
        reveal_path(path)

    def open_main_context_menu(self, pos):
        menu = create_main_context_menu(self, pos)
        if menu:
            self._exec_menu_on_top(menu, self.mapToGlobal(pos))

    def add_subtitle_file(self):
        dialog = QFileDialog(self, tr("Add Subtitle"), "")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter(tr("Subtitles (*.srt *.ass *.ssa *.sub *.vtt);;All files (*.*)"))
        selected = self._run_file_dialog(dialog)
        file = selected[0] if selected else ""
        if file:
            self.player.command("sub-add", file)

    def open_subtitle_settings(self):
        dialog = SubtitleSettingsDialog(self, self)
        self._exec_modal(dialog)

    def open_video_settings(self):
        dialog = VideoSettingsDialog(self, self)
        self._exec_modal(dialog)

    def open_equalizer_dialog(self):
        from .dialogs import EqualizerDialog

        dialog = EqualizerDialog(self, self)
        self._exec_modal(dialog)

    def open_url_dialog(self):
        logging.debug("Open URL dialog launched")
        diag = URLInputDialog(self)
        accepted = bool(self._exec_modal(diag))
        logging.debug("Open URL dialog closed: accepted=%s", accepted)
        if accepted:
            url = diag.get_url()
            logging.debug("Open URL dialog value: url=%s", url or "")
            if url:
                auth = diag.get_auth()
                is_idle = self._player_is_idle()
                logging.debug(
                    "Open URL import requested: idle=%s auth_enabled=%s",
                    is_idle,
                    bool((auth or {}).get("enabled")),
                )
                self.import_stream_sources_async([url], play_new=is_idle, auth=auth)
            else:
                logging.warning("Open URL dialog accepted but URL was empty")
                self.show_status_overlay(tr("No URL provided"))

    def open_advanced_mpv_conf(self):
        try:
            ensure_mpv_power_user_layout()
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._mpv_conf_path)))
            if not ok:
                self.show_status_overlay(tr("Could not open mpv.conf"))
        except (OSError, RuntimeError):
            self.show_status_overlay(tr("Could not open mpv.conf"))

    def open_mpv_scripts_folder(self):
        try:
            ensure_mpv_power_user_layout()
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._mpv_scripts_dir)))
            if not ok:
                self.show_status_overlay(tr("Could not open scripts folder"))
        except (OSError, RuntimeError):
            self.show_status_overlay(tr("Could not open scripts folder"))

    def toggle_mpv_stats_overlay(self):
        try:
            self.player.command("script-binding", "stats/display-stats-toggle")
        except Exception:
            self.show_status_overlay(tr("Stats overlay unavailable"))

    def toggle_fullscreen(self):
        if self._fullscreen_transition_active:
            return
        self._fullscreen_transition_active = True

        if hasattr(self, "title_bar"):
            self.title_bar.hide()
        if hasattr(self, "overlay"):
            self.overlay.hide()
        if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
            self.volume_popup.hide()
        if hasattr(self, "playlist_overlay") and not self.pinned_playlist:
            self.playlist_overlay.hide()

        target_fullscreen = not self.isFullScreen()
        self.setUpdatesEnabled(False)
        try:
            if target_fullscreen:
                self.setWindowState(self.windowState() | Qt.WindowFullScreen)
            else:
                self.setWindowState(self.windowState() & ~Qt.WindowFullScreen)
            self.show()
            self.player.fullscreen = target_fullscreen
            self.update_fullscreen_icon()
        finally:
            QTimer.singleShot(90, self._finalize_fullscreen_toggle)

    def _finalize_fullscreen_toggle(self):
        self.setUpdatesEnabled(True)
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_speed_indicator_geometry()
        self._sync_title_bar_geometry()

        if self.pinned_controls:
            self.overlay.show()
        if self.pinned_playlist:
            self.playlist_overlay.show()
            self.playlist_overlay.raise_()

        self._fullscreen_transition_active = False

    def screenshot_save_as(self):
        if not self.playlist or self.current_index < 0:
            return

        base = Path(self.playlist[self.current_index]).stem
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        default_name = f"{base}_{timestamp}.png"
        dialog = QFileDialog(self, tr("Save screenshot"), str(Path.home() / "Pictures" / default_name))
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilter(tr("PNG (*.png);;JPEG (*.jpg *.jpeg);;All files (*.*)"))
        selected = self._run_file_dialog(dialog)
        path = selected[0] if selected else ""
        if not path:
            return

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.player.command("screenshot-to-file", str(target), "video")

    def _status_overlay_timeout_for_text(self, text: str) -> int:
        msg = str(text or "").strip().casefold()
        if not msg:
            return self._status_overlay_default_ms

        error_hints = (
            "failed",
            "error",
            "invalid",
            "unreachable",
            "could not",
            "authentication failed",
            "timed out",
            "no playable",
            "not available",
            "crashed",
        )
        if any(hint in msg for hint in error_hints):
            return self._status_overlay_error_ms
        return self._status_overlay_default_ms

    def show_status_overlay(self, text: str, duration_ms: int | None = None):
        if self._is_shutting_down:
            return
        if self._full_duration_scan_active:
            scan_prefix = tr("Scanning durations...")
            cancel_prefix = tr("Cancelling duration scan...")
            locked_prefix = tr("Duration scan is running (F4 to cancel)")
            if not (
                str(text).startswith(scan_prefix)
                or str(text).startswith(cancel_prefix)
                or str(text).startswith(locked_prefix)
            ):
                text = tr("Scanning durations... {}/{}").format(
                    self._full_duration_scan_done,
                    self._full_duration_scan_total,
                )
        self.speed_overlay.label.setText(text)
        self._sync_speed_indicator_geometry()
        self.speed_overlay.show()
        self.speed_overlay.raise_()
        if self._full_duration_scan_active:
            self.speed_indicator_timer.stop()
            return
        timeout_ms = duration_ms if duration_ms is not None else self._status_overlay_timeout_for_text(text)
        if timeout_ms <= 0:
            self.speed_indicator_timer.stop()
            return
        self.speed_indicator_timer.start(int(timeout_ms))

    def show_speed_indicator(self):
        speed = self._safe_player_float("speed", 1.0)
        self.show_status_overlay(tr("{}x").format(speed))

    def set_playback_speed(self, speed: float):
        try:
            value = float(speed)
        except (TypeError, ValueError):
            return False
        if value <= 0:
            return False
        if not self._set_mpv_property_safe("speed", value):
            return False
        self.show_status_overlay(tr("{}x").format(value))
        return True

    def select_audio_track(self, track_id):
        if not self._can_switch_track_now(manual=True):
            return False
        if not self._set_mpv_property_safe("aid", track_id):
            return False
        return True

    def select_subtitle_track(self, track_id):
        if not self._can_switch_track_now(manual=True):
            return False
        if not self._set_mpv_property_safe("sid", track_id):
            return False
        return True

    def change_speed_step(self, direction: int):
        current = self._safe_player_float("speed", 1.0)
        closest = min(
            range(len(SPEED_STEPS)),
            key=lambda idx: abs(SPEED_STEPS[idx] - current),
        )
        target = max(0, min(len(SPEED_STEPS) - 1, closest + direction))
        self.set_playback_speed(SPEED_STEPS[target])

    def toggle_shuffle(self):
        self.shuffle_enabled = not self.shuffle_enabled
        save_shuffle(self.shuffle_enabled)
        if self.shuffle_enabled:
            self.rebuild_shuffle_order(keep_current=True)
            self.show_status_overlay(tr("Shuffle On"))
        else:
            self.show_status_overlay(tr("Shuffle Off"))
        self.update_mode_buttons()

    def cycle_repeat_mode(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        save_repeat(self.repeat_mode)
        self.update_mode_buttons()
        self.show_status_overlay((tr("Repeat Off"), tr("Repeat One"), tr("Repeat All"))[self.repeat_mode])

    def seek_absolute(self, value: int):
        if self.current_index < 0:
            return
        now = time.monotonic()
        if (now - self._last_seek_cmd_time) < 0.08:
            return
        self._last_seek_cmd_time = now
        try:
            target = max(0, int(value))
            self.player.command("seek", target, "absolute", "keyframes")
        except Exception:
            return

    def seek_relative(self, seconds: int):
        if self.current_index < 0:
            return
        now = time.monotonic()
        if (now - self._last_seek_cmd_time) < 0.08:
            return
        self._last_seek_cmd_time = now
        try:
            self.player.command("seek", int(seconds), "relative")
            if (now - self._last_track_switch_time) > 0.2:
                self.show_status_overlay(tr("Seek {}s").format(seconds))
        except Exception:
            return

    def toggle_play(self):
        if self._full_duration_scan_active:
            self.show_status_overlay(tr("Duration scan is running (F4 to cancel)"))
            return
        is_idle = self._player_is_idle()
        if is_idle and self.playlist:
            if self.current_index < 0:
                self.current_index = 0
            self.play_current()
            return

        new_paused = not self._cached_paused
        self._set_mpv_property_safe("pause", new_paused, allow_during_busy=True)
        self._cached_paused = new_paused
        self._user_paused = new_paused
        self.update_transport_icons()
        self.show_status_overlay(tr("Paused") if new_paused else tr("Playing"))

    def toggle_mute(self):
        new_muted = not self._cached_muted
        self.player.mute = new_muted
        self._cached_muted = new_muted
        save_muted(new_muted)
        self.update_mute_icon()
        status = tr("Muted") if new_muted else tr("Unmuted")
        self.show_status_overlay(status)

    def set_aspect_ratio(self, ratio_str):
        self._aspect_ratio_setting = str(ratio_str or "auto")
        try:
            if ratio_str == "auto":
                self._set_mpv_property_safe("video_aspect_override", -1, allow_during_busy=True)
            else:
                self._set_mpv_property_safe("video_aspect_override", ratio_str, allow_during_busy=True)

            save_aspect_ratio(ratio_str)
            self.show_status_overlay(tr("Aspect: {}").format(ratio_str))
            QTimer.singleShot(50, self.sync_size)
        except (TypeError, ValueError, RuntimeError) as e:
            logging.warning("Error setting aspect ratio: %s", e)

    def toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top

        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.always_on_top)

        self.show()
        self._sync_overlay_topmost_flags()
        if self.pinned_controls or self.current_index < 0:
            self.overlay.show()
        if self.pinned_playlist:
            self.playlist_overlay.show()
        if self.current_index < 0 and not self.isFullScreen() and not self._context_menu_open:
            self.title_bar.show()
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_title_bar_geometry()
        self._enforce_overlay_stack()

    def toggle_restore_session_on_startup(self):
        self.restore_session_on_startup = not bool(getattr(self, "restore_session_on_startup", False))
        save_restore_session_on_startup(self.restore_session_on_startup)
        status = tr("On") if self.restore_session_on_startup else tr("Off")
        self.show_status_overlay(tr("Restore session on startup: {}").format(status))

    def change_language(self, lang_code: str):
        save_language_setting(lang_code)
        from ..i18n import setup_i18n

        setup_i18n(lang_code)

        self._show_message(
            QMessageBox.Information,
            tr("Language Changed"),
            tr("Language has been changed to {}. Some changes will take effect after restart.").format(
                lang_code.upper()
            ),
        )
        self.update_mode_buttons()
        self.update_transport_icons()
        self.update_mute_icon()

    def apply_equalizer_settings(self):
        data = load_equalizer_settings()
        try:
            if data["enabled"]:
                freqs = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
                gains = data["gains"]
                af_str = ",".join(
                    f"equalizer=f={f}:width_type=o:w=1:g={g}"
                    for f, g in zip(freqs, gains)
                )
                self.player.af = af_str
            else:
                self.player.af = ""
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            logging.warning("Apply EQ error: %s", e)

    def update_equalizer_gains(self, gains):
        self.apply_equalizer_settings()

    def apply_video_settings(self):
        config = load_video_settings()
        try:
            self._set_mpv_property_safe("brightness", config.get("brightness", 0), allow_during_busy=True)
            self._set_mpv_property_safe("contrast", config.get("contrast", 0), allow_during_busy=True)
            self._set_mpv_property_safe("saturation", config.get("saturation", 0), allow_during_busy=True)
            self._set_mpv_property_safe("gamma", config.get("gamma", 0), allow_during_busy=True)
            self.window_zoom = float(config.get("zoom", 0.0))
            self._video_rotate_deg = int(config.get("rotate", 0) or 0) % 360
            self._set_mpv_property_safe("video_rotate", self._video_rotate_deg, allow_during_busy=True)
            self._video_mirror_horizontal = bool(config.get("mirror_horizontal", False))
            self._video_mirror_vertical = bool(config.get("mirror_vertical", False))
            self._seek_thumbnail_preview = bool(config.get("seek_thumbnail_preview", False))
            self._apply_video_mirror_filters()
            renderer = config.get("renderer", "gpu")
            hwdec = config.get("hwdec", "auto-safe")
            gpu_api = config.get("gpu_api", "auto")
            self._safe_set_player_attr("vo", renderer)
            self._safe_set_player_attr("gpu_api", gpu_api)
            self._safe_set_player_attr("hwdec", hwdec)
            if hasattr(self, "seek_slider"):
                self.seek_slider.set_preview_enabled(self._seek_thumbnail_preview)
            if not self._seek_thumbnail_preview and hasattr(self, "hide_seek_thumbnail_preview"):
                self.hide_seek_thumbnail_preview()
            self.sync_size()
        except (TypeError, ValueError, RuntimeError) as e:
            logging.warning("Error applying video settings: %s", e)

    def _read_video_dimensions(self) -> tuple[int, int] | None:
        candidates: list[tuple[int, int]] = []
        try:
            dw = int(self.player.dwidth or 0)
            dh = int(self.player.dheight or 0)
            candidates.append((dw, dh))
        except Exception:
            pass
        try:
            w = int(self.player.width or 0)
            h = int(self.player.height or 0)
            candidates.append((w, h))
        except Exception:
            pass
        for prop in ("video-out-params", "video-params"):
            try:
                params = self.player.command("get_property_native", prop)
                if isinstance(params, dict):
                    w = int(params.get("dw") or params.get("w") or 0)
                    h = int(params.get("dh") or params.get("h") or 0)
                    candidates.append((w, h))
            except Exception:
                pass
        for w, h in candidates:
            if w > 0 and h > 0:
                return (w, h)
        return None

    def _apply_video_dimensions(self, dims: tuple[int, int]) -> None:
        self._last_resize_dims = dims
        self._resize_stable_hits = 0
        self.sync_size(dimensions=dims)

    def _await_initial_resize_then_unpause(
        self,
        load_token: int,
        *,
        attempt: int = 0,
        max_attempts: int = 10,
    ) -> None:
        if self._is_shutting_down:
            return
        if load_token != self._playback_load_token:
            return
        dims = self._read_video_dimensions()
        if dims is not None:
            self._apply_video_dimensions(dims)
            self._pending_resize_check = False
            self._ensure_playback_unpaused(load_token)
            return
        if attempt >= max_attempts:
            self._ensure_playback_unpaused(load_token)
            QTimer.singleShot(
                120,
                lambda t=load_token: self._kickstart_resize_after_start(t, attempt=0, max_attempts=16),
            )
            return
        QTimer.singleShot(
            90,
            lambda t=load_token, a=attempt + 1, m=max_attempts: self._await_initial_resize_then_unpause(
                t,
                attempt=a,
                max_attempts=m,
            ),
        )

    def _kickstart_resize_after_start(
        self, load_token: int, *, attempt: int = 0, max_attempts: int = 16
    ) -> None:
        if self._is_shutting_down:
            return
        if load_token != self._playback_load_token:
            return
        dims = self._read_video_dimensions()
        if dims is not None:
            self._set_mpv_property_safe("pause", True, allow_during_busy=True)
            self._cached_paused = True
            self._apply_video_dimensions(dims)
            self._set_mpv_property_safe("pause", False, allow_during_busy=True)
            self._cached_paused = False
            return
        if attempt >= max_attempts:
            return
        QTimer.singleShot(
            75,
            lambda t=load_token, a=attempt + 1, m=max_attempts: self._kickstart_resize_after_start(
                t,
                attempt=a,
                max_attempts=m,
            ),
        )

    def sync_size(self, dimensions: tuple[int, int] | None = None):
        if self._is_shutting_down:
            return
        if self.isFullScreen():
            self._set_mpv_property_safe("video_zoom", self.window_zoom, min_interval_sec=0.05)
            return

        dims = dimensions or self._last_resize_dims
        if not dims or dims[0] <= 0 or dims[1] <= 0:
            if self.current_index < 0:
                empty_w, empty_h = self._empty_window_size
                self.resize(
                    max(self.minimumWidth(), int(empty_w)),
                    max(self.minimumHeight(), int(empty_h)),
                )
                self._set_mpv_property_safe("video_zoom", 0.0, min_interval_sec=0.05)
            return

        w, h = int(dims[0]), int(dims[1])
        rotate = int(self._video_rotate_deg or 0) % 360
        if rotate in {90, 270}:
            w, h = h, w
        intrinsic_aspect = (w / h) if h else 1.77
        base_h = h if h else 720

        effective_aspect = intrinsic_aspect
        override = self._aspect_ratio_setting
        if override and override != "auto":
            if isinstance(override, str) and ":" in override:
                try:
                    num, den = map(float, override.split(":"))
                    if den > 0:
                        effective_aspect = num / den
                except (TypeError, ValueError):
                    pass

        try:
            zoom_factor = 2 ** self.window_zoom
        except (TypeError, ValueError, OverflowError):
            zoom_factor = 1.0

        screen_rect = self.screen().availableGeometry()
        clamped_base_h = min(base_h, screen_rect.height() * 0.7)
        ideal_h = clamped_base_h * zoom_factor
        ideal_w = ideal_h * effective_aspect

        target_w = ideal_w
        target_h = ideal_h

        limit_h = screen_rect.height() * 0.9
        if target_h > limit_h:
            target_h = limit_h
            target_w = target_h * effective_aspect

        limit_w = screen_rect.width() * 0.9
        if target_w > limit_w:
            target_w = limit_w
            if effective_aspect > 0:
                target_h = target_w / effective_aspect

        self.resize(int(round(target_w)), int(round(target_h)))

        if target_h > 0:
            overflow_scale = ideal_h / target_h
            if abs(overflow_scale - 1.0) > 0.001:
                self._set_mpv_property_safe(
                    "video_zoom",
                    math.log2(overflow_scale),
                    min_interval_sec=0.05,
                )
            else:
                self._set_mpv_property_safe("video_zoom", 0.0, min_interval_sec=0.05)
                self._set_mpv_property_safe("video_pan_x", 0.0, min_interval_sec=0.05)
                self._set_mpv_property_safe("video_pan_y", 0.0, min_interval_sec=0.05)

        new_geometry = self.geometry()
        if not screen_rect.contains(new_geometry):
            self.move(
                max(screen_rect.left(), min(new_geometry.left(), screen_rect.right() - new_geometry.width())),
                max(screen_rect.top(), min(new_geometry.top(), screen_rect.bottom() - new_geometry.height())),
            )

    def _process_pending_resize_check(self, now: float) -> bool:
        if not self._pending_resize_check:
            return True
        if (now - self._last_track_switch_time) < 0.35:
            return False
        dims = self._read_video_dimensions()
        if dims is not None:
            if dims != self._last_resize_dims:
                self._apply_video_dimensions(dims)
            self._resize_stable_hits += 1
            if self._resize_stable_hits >= 5 and now >= (self._resize_sync_deadline - 0.8):
                self._pending_resize_check = False
        elif now >= self._resize_sync_deadline:
            self._pending_resize_check = False
        return True

    def _handle_pending_background_and_auto_next(self, suppress_end_advance: bool) -> bool:
        if self._pending_show_background:
            self._pending_show_background = False
            self.background_widget.show()
        if self._pending_auto_next and not suppress_end_advance:
            self._pending_auto_next = False
            self._advance_after_end()
            return True
        return False

    def _should_skip_ui_poll(self, now: float) -> bool:
        if now < self._suspend_ui_poll_until:
            return True
        if (
            self._pending_duration_paths
            and not self.scanners
            and now >= self._next_duration_scan_attempt_at
        ):
            self._next_duration_scan_attempt_at = now + 1.2
            if self._full_duration_scan_active:
                self.scan_durations(None, allow_while_playing=True, force=True)
        if now < self._next_ui_poll_at:
            return True
        self._next_ui_poll_at = now + (0.45 if self._cached_paused else 0.25)
        return False

    def _sync_progress_caches(self, now: float, position, duration) -> None:
        if self._is_engine_busy and (
            (position is not None and math.isfinite(position))
            or (duration is not None and math.isfinite(duration) and duration > 0)
        ):
            self._is_engine_busy = False
        if position is not None and math.isfinite(position):
            if position > (self._last_position + 0.02):
                self._last_progress_time = now
            self._last_position = float(position)
        if duration is not None and math.isfinite(duration) and duration > 0:
            self._last_duration = float(duration)

    def _sync_runtime_duration_for_current(self, duration) -> None:
        if duration is None or not (0 <= self.current_index < len(self.playlist)):
            return
        if not math.isfinite(duration):
            return
        path = str(self.playlist[self.current_index])
        allow_runtime_duration = True
        if not is_stream_url(path):
            loaded_path = ""
            try:
                loaded_path = str(getattr(self.player, "path", "") or "")
            except (AttributeError, RuntimeError):
                loaded_path = ""
            if not loaded_path:
                allow_runtime_duration = False
            else:
                try:
                    exp_norm = os.path.normcase(os.path.normpath(os.path.abspath(path)))
                    got_norm = os.path.normcase(
                        os.path.normpath(os.path.abspath(str(Path(loaded_path))))
                    )
                    allow_runtime_duration = exp_norm == got_norm
                except (TypeError, ValueError, OSError):
                    allow_runtime_duration = False
        if not allow_runtime_duration:
            return
        dur_str = format_duration(duration)
        if self.playlist_durations.get(path) != dur_str:
            self.playlist_durations[path] = dur_str
            self.playlist_raw_durations[path] = duration
            if hasattr(self, "playlist_model"):
                self.playlist_model.update_duration(path, dur_str)

    def _should_advance_after_end(self, now: float, position, duration, suppress_end_advance: bool) -> bool:
        is_at_end = False
        if position is not None and duration is not None and duration > 0:
            if position >= max(0.0, duration - 0.15):
                is_at_end = True

        if (
            not is_at_end
            and not self._user_paused
            and self.current_index >= 0
            and self._last_duration > 0
            and self._last_position >= (self._last_duration - 0.25)
            and (position is None or duration is None or self._cached_paused)
            and not suppress_end_advance
        ):
            if self._auto_next_deadline <= 0:
                self._auto_next_deadline = now + 0.4
            elif now >= self._auto_next_deadline:
                is_at_end = True
        else:
            self._auto_next_deadline = 0.0

        if (
            not is_at_end
            and not self._user_paused
            and self.current_index >= 0
            and self._last_progress_time > 0
            and (position is None or duration is None)
            and (now - self._last_progress_time) > 0.8
            and (now - self._last_track_switch_time) > 1.0
            and not suppress_end_advance
        ):
            is_at_end = True
        if (
            not is_at_end
            and not self._user_paused
            and self.current_index >= 0
            and self._last_duration > 0
            and self._last_position >= (self._last_duration - 0.6)
            and (now - self._last_progress_time) > 1.2
            and not suppress_end_advance
        ):
            is_at_end = True
        return is_at_end

    def _sync_timeline_widgets(self, position, duration) -> None:
        if position is None or duration is None:
            return
        if not math.isfinite(position) or not math.isfinite(duration):
            return
        if not self.seek_slider.isSliderDown():
            safe_duration = max(0, int(duration))
            safe_position = max(0, min(safe_duration, int(position)))
            self.seek_slider.setRange(0, safe_duration)
            self.seek_slider.setValue(safe_position)
        self.seek_slider.set_current_time(float(position))
        current_str = format_duration(position)
        duration_str = format_duration(duration)
        self.time_label.setText(f"{current_str} / {duration_str}")

    def force_ui_update(self):
        try:
            if self._is_shutting_down:
                return
            now = time.monotonic()
            suppress_end_advance = now < self._quality_reload_until
            if now < self._unsafe_mpv_read_allowed_at:
                return
            if not self._process_pending_resize_check(now):
                return
            if self._handle_pending_background_and_auto_next(suppress_end_advance):
                return
            if self._should_skip_ui_poll(now):
                return

            position = self.player.time_pos
            duration = self.player.duration
            self._sync_progress_caches(now, position, duration)
            self._sync_runtime_duration_for_current(duration)

            if self._should_advance_after_end(now, position, duration, suppress_end_advance):
                advanced = self._advance_after_end()
                if not advanced:
                    self._cached_paused = True
                    self._pending_show_background = True
                    self.update_transport_icons()
                self._auto_next_deadline = 0.0
                return

            self._sync_timeline_widgets(position, duration)
        except Exception:
            # Keep this broad: mpv property access can fail with backend/runtime-specific errors.
            pass

    def _extract_chapter_times(self) -> list[dict]:
        try:
            chapters = self.player.chapter_list
        except Exception:
            return []
        if not chapters:
            return []
        out = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            raw = chapter.get("time")
            try:
                sec = float(raw)
            except (TypeError, ValueError):
                continue
            if sec >= 0:
                out.append({"time": sec, "title": str(chapter.get("title") or "")})
        return out

    def _refresh_chapter_markers(self, load_token: int):
        if self._is_shutting_down:
            return
        if load_token != self._playback_load_token:
            return
        if time.monotonic() < self._unsafe_mpv_read_allowed_at:
            return
        if self.current_index < 0:
            self.seek_slider.set_chapters([])
            return
        self.seek_slider.set_chapters(self._extract_chapter_times())

    def apply_subtitle_settings(self):
        config = load_sub_settings()
        style = str(config.get("back_style", "Shadow"))
        if style not in {"None", "Shadow", "Outline", "Opaque Box"}:
            style = "Shadow"
        color_value = str(config.get("color", "#FFFFFF"))

        def _safe_set(attr: str, value, mpv_prop: str | None = None):
            try:
                setattr(self.player, attr, value)
                return
            except Exception:
                pass
            if mpv_prop:
                try:
                    self.player.command("set", mpv_prop, str(value))
                except Exception:
                    pass

        def _to_ass_color(value: str, default: str) -> str:
            # ASS wants &HAABBGGRR where AA=alpha (00 opaque, FF transparent).
            raw = str(value or "").strip()
            m = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{8})", raw)
            if not m:
                raw = default
                m = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{8})", raw)
            assert m is not None
            token = m.group(1)
            if len(token) == 6:
                rr, gg, bb = token[0:2], token[2:4], token[4:6]
                aa = "00"
            else:
                aa, rr, gg, bb = token[0:2], token[2:4], token[4:6], token[6:8]
            return f"&H{aa.upper()}{bb.upper()}{gg.upper()}{rr.upper()}"

        _safe_set("sub_ass_override", "force", "sub-ass-override")
        _safe_set("sub_ass_style_override", "force", "sub-ass-style-override")

        font_size = int(config.get("font_size", 55))
        _safe_set("sub_font_size", font_size, "sub-font-size")
        _safe_set("sub_scale", max(0.2, min(5.0, float(font_size) / 55.0)), "sub-scale")
        _safe_set("sub_color", color_value, "sub-color")
        _safe_set("sub_pos", int(config.get("pos", 100)), "sub-pos")
        _safe_set("sub_delay", float(config.get("delay", 0.0)), "sub-delay")

        _safe_set("sub_border_style", "outline-and-shadow", "sub-border-style")
        _safe_set("sub_border_size", 0, "sub-border-size")
        _safe_set("sub_shadow_offset", 0, "sub-shadow-offset")
        _safe_set("sub_line_spacing", 0, "sub-line-spacing")
        _safe_set("sub_back_color", "#00000000", "sub-back-color")
        _safe_set("sub_border_color", "#00000000", "sub-border-color")

        if style == "Outline":
            _safe_set("sub_border_size", 3, "sub-border-size")
            _safe_set("sub_border_color", "#FF000000", "sub-border-color")
        elif style == "Shadow":
            _safe_set("sub_border_size", 0, "sub-border-size")
            _safe_set("sub_shadow_offset", 3, "sub-shadow-offset")
            _safe_set("sub_back_color", "#FF000000", "sub-back-color")
        elif style == "Opaque Box":
            _safe_set("sub_border_style", "opaque-box", "sub-border-style")
            _safe_set("sub_border_size", 1, "sub-border-size")
            _safe_set("sub_shadow_offset", 0, "sub-shadow-offset")
            _safe_set("sub_border_color", "#80000000", "sub-border-color")
            _safe_set("sub_line_spacing", 4, "sub-line-spacing")

        ass_parts = [f"PrimaryColour={_to_ass_color(color_value, '#FFFFFF')}"]
        if style == "None":
            ass_parts.extend(["BorderStyle=1", "Outline=0", "Shadow=0"])
        elif style == "Outline":
            ass_parts.extend(
                [
                    "BorderStyle=1",
                    "Outline=3",
                    "Shadow=0",
                    "OutlineColour=&H00000000",
                ]
            )
        elif style == "Shadow":
            ass_parts.extend(
                [
                    "BorderStyle=1",
                    "Outline=0",
                    "Shadow=3",
                    "BackColour=&H00000000",
                ]
            )
        else:
            ass_parts.extend(
                [
                    "BorderStyle=3",
                    "Outline=1",
                    "Shadow=0",
                    "BackColour=&H80000000",
                ]
            )
        _safe_set("sub_ass_force_style", ",".join(ass_parts), "sub-ass-force-style")

        track = self._current_subtitle_track()
        if track and self._is_bitmap_subtitle_track(track):
            key = str(track.get("id", "bitmap-sub"))
            if getattr(self, "_last_bitmap_sub_warn_id", "") != key:
                self._last_bitmap_sub_warn_id = key
                self.show_status_overlay(
                    tr("Embedded bitmap subtitles: size/background style support is limited"),
                    2400,
                )

    def _current_subtitle_track(self) -> dict | None:
        try:
            tracks = self.player.track_list or []
        except Exception:
            return None
        if not isinstance(tracks, list):
            return None
        for track in tracks:
            if isinstance(track, dict) and track.get("type") == "sub" and track.get("selected"):
                return track
        return None

    def _is_bitmap_subtitle_track(self, track: dict) -> bool:
        codec = str(track.get("codec") or "").lower()
        title = str(track.get("title") or "").lower()
        fmt = str(track.get("format") or "").lower()
        image_flag = bool(track.get("image")) or bool(track.get("is_image"))
        bitmap_tokens = (
            "pgs",
            "hdmv_pgs_subtitle",
            "vobsub",
            "dvd_subtitle",
            "dvb_subtitle",
            "xsub",
            "teletext",
        )
        if image_flag:
            return True
        blob = f"{codec} {title} {fmt}"
        return any(token in blob for token in bitmap_tokens)

    def _persist_runtime_subtitle_settings(self):
        try:
            config = load_sub_settings()
            font_size = self.player.sub_font_size
            sub_pos = self.player.sub_pos
            sub_delay = self.player.sub_delay
            config.update(
                {
                    "font_size": int(font_size if font_size is not None else config.get("font_size", 55)),
                    "pos": int(sub_pos if sub_pos is not None else config.get("pos", 100)),
                    "delay": float(sub_delay if sub_delay is not None else config.get("delay", 0.0)),
                }
            )
            save_sub_settings(config)
        except (RuntimeError, TypeError, ValueError) as e:
            logging.debug("Failed to persist runtime subtitle settings: %s", e)

    def apply_stream_quality_setting(self):
        # Reset cached per-URL quality lists to avoid stale results after runtime
        # extractor/client option changes.
        self._stream_quality_cache.clear()
        mapping = {
            "best": "bestvideo+bestaudio/best",
            "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480": "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "360": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        }
        raw_quality = str(self.stream_quality or "best")
        if raw_quality.startswith(YTDLP_FMT_PREFIX):
            fmt = raw_quality[len(YTDLP_FMT_PREFIX) :].strip() or mapping["best"]
        else:
            fmt = mapping.get(raw_quality, mapping["best"])
        try:
            self.player.ytdl_format = fmt
        except Exception:
            pass
        try:
            if 0 <= self.current_index < len(self.playlist):
                self._apply_seek_profile_for_source(self.playlist[self.current_index])
        except Exception:
            pass

    def _quality_label(self, value: str) -> str:
        if value == "best":
            return tr("Auto (Best)")
        if value.isdigit():
            return f"{value}p"
        if value.startswith(YTDLP_FMT_PREFIX):
            return tr("Custom Format")
        return value

    def _is_stream_quality_resolvable_url(self, url: str) -> bool:
        return is_stream_url(url) and _is_youtube_url(url)

    def _dedupe_quality_values(self, options: list[tuple[str, str]]) -> list[tuple[str, str]]:
        dedup: list[tuple[str, str]] = []
        seen = set()
        for value, label in options:
            if value not in seen:
                seen.add(value)
                dedup.append((value, label))
        return dedup

    def _cache_stream_quality_values(self, key: str, values: list[tuple[str, str]]) -> None:
        self._stream_quality_cache[key] = list(values)
        while len(self._stream_quality_cache) > self._stream_quality_cache_limit:
            self._stream_quality_cache.pop(next(iter(self._stream_quality_cache)), None)

    def _normalize_video_codec_label(self, codec: str) -> tuple[str, str]:
        raw = str(codec or "").strip().lower()
        if not raw or raw == "none":
            return "", ""
        token = raw.split(".", 1)[0]
        if raw.startswith("av01") or token == "av01":
            return "AV1", "av01"
        if raw.startswith("vp9") or token == "vp9":
            return "VP9", "vp9"
        if raw.startswith("avc1") or raw.startswith("avc3") or token in {"avc1", "avc3"}:
            return "H.264", "avc"
        if raw.startswith("hvc1") or raw.startswith("hev1") or token in {"hvc1", "hev1"}:
            return "HEVC", token
        return token.upper(), token

    def _build_codec_format_selector(self, height: int, codec_token: str) -> str:
        return (
            f"bestvideo[vcodec*={codec_token}][height<={int(height)}]+"
            f"bestaudio/"
            f"bestvideo[height<={int(height)}]+bestaudio/"
            f"best[height<={int(height)}]"
        )

    def _extract_youtube_quality_options(self, url: str) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = [("best", tr("Auto (Best)"))]
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "remote_components": YTDLP_REMOTE_COMPONENTS,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats", []) if isinstance(info, dict) else []
        codec_variants: set[tuple[int, str, str]] = set()
        for item in formats:
            if not isinstance(item, dict):
                continue
            vcodec = str(item.get("vcodec") or "").strip()
            if vcodec in {"", "none"}:
                continue
            height = item.get("height")
            if isinstance(height, int) and height > 0:
                codec_label, codec_token = self._normalize_video_codec_label(vcodec)
                if codec_label and codec_token:
                    codec_variants.add((height, codec_label, codec_token))
        codec_order = {"H.264": 0, "VP9": 1, "AV1": 2, "HEVC": 3}
        for height, codec_label, codec_token in sorted(
            codec_variants,
            key=lambda x: (-x[0], codec_order.get(x[1], 9), x[1]),
        ):
            selector = self._build_codec_format_selector(height, codec_token)
            options.append((f"{YTDLP_FMT_PREFIX}{selector}", f"{height}p ({codec_label})"))
        return options

    def _resolve_quality_options_for_url(self, url: str) -> list[tuple[str, str]]:
        if not self._is_stream_quality_resolvable_url(url):
            return []
        if yt_dlp is None:
            return [("best", tr("Auto (Best)"))]

        key = url.casefold()
        if key in self._stream_quality_cache:
            return list(self._stream_quality_cache[key])

        options: list[tuple[str, str]] = [("best", tr("Auto (Best)"))]
        try:
            options = self._extract_youtube_quality_options(url)
        except Exception:
            pass

        dedup = self._dedupe_quality_values(options)
        self._cache_stream_quality_values(key, dedup)
        return dedup

    def get_stream_quality_menu_options(self):
        if not (0 <= self.current_index < len(self.playlist)):
            return []
        current_item = str(self.playlist[self.current_index])
        values = self._resolve_quality_options_for_url(current_item)
        if not values:
            return []
        options = []
        for value, label in values:
            options.append((value, label or self._quality_label(value), value == self.stream_quality))
        return options

    def _current_quality_display_label(self, selected_value: str) -> str:
        value = str(selected_value or "best")
        if not (0 <= self.current_index < len(self.playlist)):
            return self._quality_label(value)
        current_item = str(self.playlist[self.current_index])
        for opt_value, opt_label in self._resolve_quality_options_for_url(current_item):
            if opt_value == value:
                return opt_label or self._quality_label(value)
        return self._quality_label(value)

    def _reload_current_stream_for_quality_change(self) -> bool:
        if not (0 <= self.current_index < len(self.playlist)):
            return False
        current_item = str(self.playlist[self.current_index])
        if not is_stream_url(current_item):
            return False
        try:
            self._apply_seek_profile_for_source(current_item)
        except Exception:
            pass
        pos = self._safe_player_float("time_pos", 0.0)
        was_paused = bool(self._cached_paused)
        self._quality_reload_until = time.monotonic() + 5.0
        self._pending_auto_next = False
        self._auto_next_deadline = 0.0
        try:
            self.player.command(
                "loadfile",
                current_item,
                "replace",
                "pause=yes" if was_paused else "pause=no",
            )
            if pos > 1.0:
                QTimer.singleShot(
                    200,
                    lambda p=pos: self.player.command("seek", p, "absolute", "keyframes"),
                )
            return True
        except Exception:
            try:
                self.player.command("loadfile", current_item, "replace")
            except Exception:
                return False
            self._set_mpv_property_safe("pause", was_paused, allow_during_busy=True)
            return True

    def set_stream_quality(self, quality: str):
        self.stream_quality = str(quality or "best")
        save_stream_quality(self.stream_quality)
        self.apply_stream_quality_setting()
        shown = self._current_quality_display_label(self.stream_quality)
        reloaded = self._reload_current_stream_for_quality_change()
        if reloaded:
            self.show_status_overlay(tr("Quality: {} (reloaded)").format(shown))
        else:
            self.show_status_overlay(tr("Quality: {}").format(shown))

    def _is_owned_by_player(self, obj):
        if obj is None:
            return False
        if obj is self:
            return True
        try:
            if isinstance(obj, QWidget):
                overlays = [
                    getattr(self, "overlay", None),
                    getattr(self, "speed_overlay", None),
                    getattr(self, "playlist_overlay", None),
                    getattr(self, "title_bar", None),
                ]
                for w in overlays:
                    if w and (obj is w or w.isAncestorOf(obj)):
                        return True
                return self.isAncestorOf(obj)
        except RuntimeError:
            return False
        return False

    def _is_app_shortcut_key(self, event) -> bool:
        key = event.key()
        return key in {
            Qt.Key_Escape,
            Qt.Key_Right,
            Qt.Key_Left,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
            Qt.Key_F4,
            Qt.Key_Space,
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_F,
            Qt.Key_Delete,
            Qt.Key_Period,
            Qt.Key_Comma,
            Qt.Key_BracketRight,
            Qt.Key_BracketLeft,
            Qt.Key_Plus,
            Qt.Key_Equal,
            Qt.Key_Minus,
            Qt.Key_0,
            Qt.Key_2,
            Qt.Key_4,
            Qt.Key_6,
            Qt.Key_8,
            Qt.Key_B,
            Qt.Key_M,
            Qt.Key_S,
            Qt.Key_P,
            Qt.Key_V,
            Qt.Key_R,
            Qt.Key_G,
            Qt.Key_H,
            Qt.Key_J,
            Qt.Key_K,
            Qt.Key_I,
            Qt.Key_U,
            Qt.Key_O,
            Qt.Key_L,
            Qt.Key_X,
            Qt.Key_Y,
        }

    def _canonicalize_mpv_key(self, key_name: str) -> str:
        text = str(key_name or "").strip()
        if not text:
            return ""
        parts = [p for p in text.split("+") if p]
        if not parts:
            return ""
        mods = []
        base = parts[-1]
        if len(base) > 1:
            base = base.lower()
        mod_order = {"ctrl": 0, "alt": 1, "shift": 2, "meta": 3}
        for p in parts[:-1]:
            low = p.strip().lower()
            if low in mod_order and low not in mods:
                mods.append(low)
        mods.sort(key=lambda m: mod_order[m])
        return "+".join(mods + [base])

    def _list_lua_script_files(self, scripts_dir: Path) -> list[Path]:
        try:
            return sorted(scripts_dir.rglob("*.lua"))
        except (OSError, RuntimeError):
            return []

    def _scripts_newest_mtime(self, files: list[Path]) -> float:
        newest_mtime = 0.0
        for file_path in files:
            try:
                newest_mtime = max(newest_mtime, float(file_path.stat().st_mtime))
            except OSError:
                pass
        return newest_mtime

    def _extract_script_bindings_from_lua_files(self, files: list[Path]) -> dict[str, list[str]]:
        pattern = re.compile(
            r"mp\.add_(?:forced_)?key_binding\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        )
        cache: dict[str, list[str]] = {}
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                continue
            for key_name, binding_name in pattern.findall(text):
                canonical = self._canonicalize_mpv_key(key_name)
                if not canonical:
                    continue
                cache.setdefault(canonical, [])
                if binding_name not in cache[canonical]:
                    cache[canonical].append(binding_name)
        return cache

    def _refresh_script_bindings_cache(self):
        scripts_dir = Path(getattr(self, "_mpv_scripts_dir", "") or "")
        if not scripts_dir or not scripts_dir.exists():
            self._script_bindings_cache = {}
            self._script_bindings_mtime = 0.0
            return

        lua_files = self._list_lua_script_files(scripts_dir)
        newest_mtime = self._scripts_newest_mtime(lua_files)

        if newest_mtime and newest_mtime == self._script_bindings_mtime and self._script_bindings_cache:
            return

        self._script_bindings_cache = self._extract_script_bindings_from_lua_files(lua_files)
        self._script_bindings_mtime = newest_mtime

    def _trigger_script_binding_for_event(self, event) -> bool:
        key_name = self._qt_event_to_mpv_key(event)
        if not key_name:
            return False

        self._refresh_script_bindings_cache()
        canonical = self._canonicalize_mpv_key(key_name)
        names = self._script_bindings_cache.get(canonical, [])
        if not names:
            return False

        for binding_name in names:
            try:
                self.player.command("script-binding", binding_name)
                return True
            except Exception:
                continue
        return False

    def _qt_special_key_name(self, key) -> str | None:
        special = {
            Qt.Key_Space: "SPACE",
            Qt.Key_Enter: "ENTER",
            Qt.Key_Return: "ENTER",
            Qt.Key_Escape: "ESC",
            Qt.Key_Tab: "TAB",
            Qt.Key_Backspace: "BS",
            Qt.Key_Delete: "DEL",
            Qt.Key_Insert: "INS",
            Qt.Key_Home: "HOME",
            Qt.Key_End: "END",
            Qt.Key_PageUp: "PGUP",
            Qt.Key_PageDown: "PGDWN",
            Qt.Key_Left: "LEFT",
            Qt.Key_Right: "RIGHT",
            Qt.Key_Up: "UP",
            Qt.Key_Down: "DOWN",
        }
        return special.get(key)

    def _qt_base_key_name(self, event) -> str | None:
        key = event.key()
        base = self._qt_special_key_name(key)
        if base:
            return base
        if Qt.Key_F1 <= key <= Qt.Key_F12:
            return f"F{key - Qt.Key_F1 + 1}"
        if Qt.Key_A <= key <= Qt.Key_Z:
            ch = chr(ord("a") + (key - Qt.Key_A))
            if event.modifiers() & Qt.ShiftModifier:
                ch = ch.upper()
            return ch
        if Qt.Key_0 <= key <= Qt.Key_9:
            return str(key - Qt.Key_0)
        text = event.text() or ""
        if not text or not text.isprintable():
            return None
        return "SPACE" if text == " " else text

    def _qt_modifier_parts(self, event, base: str) -> list[str]:
        mods = event.modifiers()
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.MetaModifier:
            parts.append("meta")
        if (mods & Qt.ShiftModifier) and base.isupper() and len(base) > 1:
            parts.append("shift")
        elif (mods & Qt.ShiftModifier) and base in {
            "ENTER", "ESC", "TAB", "BS", "DEL", "INS", "HOME", "END",
            "PGUP", "PGDWN", "LEFT", "RIGHT", "UP", "DOWN",
        }:
            parts.append("shift")
        return parts

    def _qt_event_to_mpv_key(self, event) -> str | None:
        key = event.key()
        if key in {
            Qt.Key_Shift,
            Qt.Key_Control,
            Qt.Key_Alt,
            Qt.Key_Meta,
            Qt.Key_AltGr,
        }:
            return None
        base = self._qt_base_key_name(event)
        if not base:
            return None
        parts = self._qt_modifier_parts(event, base)
        if parts:
            return "+".join(parts + [base])
        return base

    def _forward_key_to_mpv(self, event) -> bool:
        key_name = self._qt_event_to_mpv_key(event)
        if not key_name:
            return False

        try:
            self.player.command("keypress", key_name)
            return True
        except Exception as first_err:
            try:
                keypress_fn = getattr(self.player, "keypress", None)
                if callable(keypress_fn):
                    keypress_fn(key_name)
                    return True
            except Exception as second_err:
                logging.debug(
                    "mpv key forward failed: key=%s cmd_err=%s method_err=%s",
                    key_name,
                    first_err,
                    second_err,
                )
                return False
            logging.debug("mpv key forward failed: key=%s cmd_err=%s", key_name, first_err)
            return False

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self._is_owned_by_player(obj):
            owner_windows = {
                self,
                getattr(self, "overlay", None),
                getattr(self, "speed_overlay", None),
                getattr(self, "playlist_overlay", None),
                getattr(self, "title_bar", None),
            }
            target_window = obj.window() if isinstance(obj, QWidget) else None
            if target_window not in owner_windows:
                return QMainWindow.eventFilter(self, obj, event)

            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit):
                return QMainWindow.eventFilter(self, obj, event)
            if self._is_playlist_search_focused() or self._is_playlist_widget_focused():
                return QMainWindow.eventFilter(self, obj, event)

            if not self._is_app_shortcut_key(event):
                if self._trigger_script_binding_for_event(event):
                    return True
                if self._forward_key_to_mpv(event):
                    return True
                return QMainWindow.eventFilter(self, obj, event)
            self.keyPressEvent(event)
            return True
        return QMainWindow.eventFilter(self, obj, event)

    def wheelEvent(self, event):
        if (
            hasattr(self, "playlist_overlay")
            and self.playlist_overlay.isVisible()
            and self.playlist_overlay.geometry().contains(QCursor.pos())
        ):
            QMainWindow.wheelEvent(self, event)
            return

        delta = event.angleDelta().y()
        if delta > 0:
            self.vol_slider.setValue(self.vol_slider.value() + 5)
        elif delta < 0:
            self.vol_slider.setValue(self.vol_slider.value() - 5)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
                global_pos = event.globalPosition().toPoint()
                on_main_btn = self.mute_btn.rect().contains(self.mute_btn.mapFromGlobal(global_pos))
                on_popup = self.volume_popup.rect().contains(self.volume_popup.mapFromGlobal(global_pos))
                if not on_main_btn and not on_popup:
                    self.volume_popup.hide()
            if event.position().x() >= self.width() - 20 and event.position().y() >= self.height() - 20:
                self._is_resizing = True
                self.dragpos = event.globalPosition().toPoint()
                self._start_size = self.size()
                event.accept()
                return

            if (
                hasattr(self, "playlist_overlay")
                and self.playlist_overlay.isVisible()
                and not getattr(self, "pinned_playlist", False)
            ):
                if not self.playlist_overlay.geometry().contains(event.position().toPoint()):
                    self.playlist_overlay.hide()

            if self.video_container.geometry().contains(event.position().toPoint()) and not self.isFullScreen():
                self.dragpos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return

        QMainWindow.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self.dragpos is not None:
            if hasattr(self, "_is_resizing") and self._is_resizing:
                delta = event.globalPosition().toPoint() - self.dragpos
                new_width = max(self.minimumWidth(), self._start_size.width() + delta.x())
                new_height = max(self.minimumHeight(), self._start_size.height() + delta.y())
                self.resize(new_width, new_height)
            else:
                self.move(event.globalPosition().toPoint() - self.dragpos)

            event.accept()
            return

        QMainWindow.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.dragpos = None
        self._is_resizing = False
        QMainWindow.mouseReleaseEvent(self, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        QMainWindow.dragEnterEvent(self, event)

    def dropEvent(self, event):
        target = "playlist" if self._is_cursor_over_playlist_panel() else "video"
        self.handle_drop_urls(event.mimeData().urls(), drop_target=target)
        if not event.isAccepted():
            event.acceptProposedAction()

    def _is_cursor_over_playlist_panel(self) -> bool:
        return bool(
            hasattr(self, "playlist_overlay")
            and self.playlist_overlay.isVisible()
            and self.playlist_overlay.geometry().contains(QCursor.pos())
        )

    def handle_drop_urls(self, urls, drop_target: str = "auto"):
        local_paths = []
        remote_urls = []
        for qurl in urls or []:
            local = qurl.toLocalFile()
            if local:
                local_paths.append(Path(local))
                continue
            value = qurl.toString().strip()
            if value:
                remote_urls.append(value)
        self.handle_dropped_paths(local_paths, remote_urls=remote_urls, drop_target=drop_target)

    def _focused_widget(self):
        return QApplication.focusWidget()

    def _is_playlist_search_focused(self) -> bool:
        focused = self._focused_widget()
        if not focused or not hasattr(self, "playlist_search_input"):
            return False
        return focused is self.playlist_search_input or self.playlist_search_input.isAncestorOf(focused)

    def _is_playlist_widget_focused(self) -> bool:
        focused = self._focused_widget()
        if not focused or not hasattr(self, "playlist_widget"):
            return False
        return focused is self.playlist_widget or self.playlist_widget.isAncestorOf(focused)

    def _handle_escape_shortcuts(self, key) -> bool:
        if key == Qt.Key_Escape:
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible() and not self.pinned_playlist:
                self.playlist_overlay.hide()
                return True
            if self.isFullScreen():
                self.toggle_fullscreen()
                return True
        return False

    def _handle_playlist_focus_shortcuts(self, event, key) -> bool:
        if self._is_playlist_search_focused():
            QMainWindow.keyPressEvent(self, event)
            return True
        if self._is_playlist_widget_focused():
            if key in (Qt.Key_Enter, Qt.Key_Return):
                self.play_selected_item()
                return True
            if key == Qt.Key_Delete:
                if event.modifiers() & Qt.ShiftModifier:
                    self.delete_to_trash()
                else:
                    self.remove_selected_from_playlist()
                return True
            QMainWindow.keyPressEvent(self, event)
            return True
        return False

    def _handle_open_shortcuts(self, key, mods) -> bool:
        if key == Qt.Key_O and (mods & Qt.ControlModifier) and (mods & Qt.ShiftModifier):
            self.add_folder_dialog()
            return True
        if key == Qt.Key_O and (mods & Qt.ControlModifier):
            self.add_files_dialog()
            return True
        if key == Qt.Key_L and (mods & Qt.ControlModifier):
            self.open_url_dialog()
            return True
        return False

    def _handle_transport_shortcuts(self, event, key) -> bool:
        if key == Qt.Key_Right:
            self.seek_relative(5)
            return True
        if key == Qt.Key_Left:
            self.seek_relative(-5)
            return True
        if key == Qt.Key_Up:
            self.vol_slider.setValue(self.vol_slider.value() + 5)
            return True
        if key == Qt.Key_Down:
            self.vol_slider.setValue(self.vol_slider.value() - 5)
            return True
        if key == Qt.Key_PageUp:
            self.prev_video()
            return True
        if key == Qt.Key_PageDown:
            self.next_video()
            return True
        if key == Qt.Key_F4:
            self.toggle_full_duration_scan()
            return True
        if key == Qt.Key_Space:
            self.toggle_play()
            return True
        if key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_F):
            self.toggle_fullscreen()
            return True
        if key == Qt.Key_Delete:
            if event.modifiers() & Qt.ShiftModifier:
                self.delete_to_trash()
            else:
                self.remove_selected_from_playlist()
            return True
        if key == Qt.Key_Period:
            self.player.command("frame-step")
            return True
        if key == Qt.Key_Comma:
            self.player.command("frame-back-step")
            return True
        if key == Qt.Key_BracketRight:
            self.change_speed_step(1)
            return True
        if key == Qt.Key_BracketLeft:
            self.change_speed_step(-1)
            return True
        if key == Qt.Key_M:
            self.toggle_mute()
            return True
        if key == Qt.Key_S:
            self.screenshot_save_as()
            return True
        if key == Qt.Key_P:
            self.toggle_playlist_panel()
            return True
        if key == Qt.Key_V:
            self.open_video_settings()
            return True
        return False

    def _handle_zoom_shortcuts(self, key) -> bool:
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self.window_zoom += 0.1
            self.show_status_overlay(tr("Zoom: {}").format(f"{self.window_zoom:.1f}"))
            self._save_zoom_setting()
            self.sync_size()
            return True
        if key == Qt.Key_Minus:
            self.window_zoom = max(-2.0, self.window_zoom - 0.1)
            self.show_status_overlay(tr("Zoom: {}").format(f"{self.window_zoom:.1f}"))
            self._save_zoom_setting()
            self.sync_size()
            return True
        if key == Qt.Key_0:
            self.window_zoom = 0.0
            self.show_status_overlay(tr("Zoom Reset"))
            self._save_zoom_setting()
            self._set_mpv_property_safe("video_pan_x", 0.0, min_interval_sec=0.05)
            self._set_mpv_property_safe("video_pan_y", 0.0, min_interval_sec=0.05)
            self.sync_size()
            return True
        return False

    def _handle_pan_shortcuts(self, key) -> bool:
        if key == Qt.Key_4:
            if (self.player.video_zoom or 0.0) > 0.0:
                next_x = min(3.0, (self.player.video_pan_x or 0.0) + 0.05)
                self._set_mpv_property_safe("video_pan_x", next_x, min_interval_sec=0.03)
                self.show_status_overlay(tr("Pan Left"))
            return True
        if key == Qt.Key_6:
            if (self.player.video_zoom or 0.0) > 0.0:
                next_x = max(-3.0, (self.player.video_pan_x or 0.0) - 0.05)
                self._set_mpv_property_safe("video_pan_x", next_x, min_interval_sec=0.03)
                self.show_status_overlay(tr("Pan Right"))
            return True
        if key == Qt.Key_8:
            if (self.player.video_zoom or 0.0) > 0.0:
                next_y = min(3.0, (self.player.video_pan_y or 0.0) + 0.05)
                self._set_mpv_property_safe("video_pan_y", next_y, min_interval_sec=0.03)
                self.show_status_overlay(tr("Pan Up"))
            return True
        if key == Qt.Key_2:
            if (self.player.video_zoom or 0.0) > 0.0:
                next_y = max(-3.0, (self.player.video_pan_y or 0.0) - 0.05)
                self._set_mpv_property_safe("video_pan_y", next_y, min_interval_sec=0.03)
                self.show_status_overlay(tr("Pan Down"))
            return True
        return False

    def _handle_brightness_shortcut(self, key, mods) -> bool:
        if key != Qt.Key_B:
            return False
        if mods & Qt.ShiftModifier:
            self.player.brightness = max(-100, self.player.brightness - 5)
        else:
            self.player.brightness = min(100, self.player.brightness + 5)
        cfg = load_video_settings()
        cfg["brightness"] = int(self.player.brightness or 0)
        save_video_settings(cfg)
        self.show_status_overlay(tr("Brightness: {}").format(self.player.brightness))
        return True

    def _save_video_transform_settings(self):
        cfg = load_video_settings()
        cfg["rotate"] = int(self._video_rotate_deg or 0) % 360
        cfg["mirror_horizontal"] = bool(self._video_mirror_horizontal)
        cfg["mirror_vertical"] = bool(self._video_mirror_vertical)
        save_video_settings(cfg)

    def rotate_video_90(self, angle=None):
        # Supports both shortcut rotate (+90) and menu select absolute angle.
        if isinstance(angle, bool):
            angle = None
        if angle in {0, 90, 180, 270}:
            self._video_rotate_deg = int(angle)
        else:
            self._video_rotate_deg = (int(self._video_rotate_deg or 0) + 90) % 360
        self._set_mpv_property_safe("video_rotate", self._video_rotate_deg, allow_during_busy=True)
        self._save_video_transform_settings()
        self.sync_size()
        self.show_status_overlay(tr("Rotate: {}").format(f"{self._video_rotate_deg}°"))

    def reset_video_rotation(self, *_args):
        self._video_rotate_deg = 0
        self._set_mpv_property_safe("video_rotate", self._video_rotate_deg, allow_during_busy=True)
        self._save_video_transform_settings()
        self.sync_size()
        self.show_status_overlay(tr("Rotate reset"))

    def toggle_mirror_horizontal(self, *_args):
        self._video_mirror_horizontal = not bool(self._video_mirror_horizontal)
        self._apply_video_mirror_filters()
        self._save_video_transform_settings()
        self.show_status_overlay(
            tr("Mirror Horizontal: {}").format(
                tr("On") if self._video_mirror_horizontal else tr("Off")
            )
        )

    def toggle_mirror_vertical(self, *_args):
        self._video_mirror_vertical = not bool(self._video_mirror_vertical)
        self._apply_video_mirror_filters()
        self._save_video_transform_settings()
        self.show_status_overlay(
            tr("Mirror Vertical: {}").format(
                tr("On") if self._video_mirror_vertical else tr("Off")
            )
        )

    def _handle_rotation_shortcuts(self, key, mods) -> bool:
        if key == Qt.Key_R and (mods & Qt.ControlModifier):
            self.reset_video_rotation()
            return True
        if key == Qt.Key_R:
            self.rotate_video_90()
            return True
        return False

    def _handle_mirror_shortcuts(self, key) -> bool:
        if key == Qt.Key_X:
            self.toggle_mirror_horizontal()
            return True
        if key == Qt.Key_Y:
            self.toggle_mirror_vertical()
            return True
        return False

    def _handle_subtitle_runtime_shortcuts(self, key, mods) -> bool:
        if key == Qt.Key_G:
            self.player.sub_delay -= 0.1
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Delay: {}s").format(f"{self.player.sub_delay:.1f}"))
            return True
        if key == Qt.Key_H:
            self.player.sub_delay += 0.1
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Delay: {}s").format(f"{self.player.sub_delay:.1f}"))
            return True
        if key == Qt.Key_J:
            self.player.sub_font_size = max(1, self.player.sub_font_size - 1)
            self.player.sub_scale = max(0.2, min(5.0, float(self.player.sub_font_size) / 55.0))
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Size: {}").format(self.player.sub_font_size))
            return True
        if key == Qt.Key_K:
            self.player.sub_font_size = min(120, self.player.sub_font_size + 1)
            self.player.sub_scale = max(0.2, min(5.0, float(self.player.sub_font_size) / 55.0))
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Size: {}").format(self.player.sub_font_size))
            return True
        if key == Qt.Key_I and (mods & Qt.ShiftModifier):
            self.toggle_mpv_stats_overlay()
            return True
        if key == Qt.Key_U:
            self.player.sub_pos = max(0, self.player.sub_pos - 1)
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Pos: {}").format(self.player.sub_pos))
            return True
        if key == Qt.Key_I:
            self.player.sub_pos = min(100, self.player.sub_pos + 1)
            self._persist_runtime_subtitle_settings()
            self.show_status_overlay(tr("Pos: {}").format(self.player.sub_pos))
            return True
        return False

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if self._handle_escape_shortcuts(key):
            return
        if self._handle_playlist_focus_shortcuts(event, key):
            return
        if self._handle_open_shortcuts(key, mods):
            return
        if self._handle_transport_shortcuts(event, key):
            return
        if self._handle_zoom_shortcuts(key):
            return
        if self._handle_pan_shortcuts(key):
            return
        if self._handle_brightness_shortcut(key, mods):
            return
        if self._handle_rotation_shortcuts(key, mods):
            return
        if self._handle_mirror_shortcuts(key):
            return
        if self._handle_subtitle_runtime_shortcuts(key, mods):
            return

        QMainWindow.keyPressEvent(self, event)
