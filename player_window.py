import os
import re
import sys
import subprocess
import logging
import hashlib
import tempfile
from collections import deque
import threading
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import time

import mpv

from PySide6.QtCore import QTimer, Qt, Signal, QPoint
from PySide6.QtGui import QCursor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .settings import (
    load_muted,
    load_repeat,
    load_shuffle,
    load_volume,
    load_video_settings,
    save_video_settings,
    load_aspect_ratio,
    load_resume_position,
    load_pinned_settings,
    load_stream_quality,
)
from .ui.icons import (
    icon_close,
    icon_folder,
    icon_minus,
    icon_playlist,
    icon_plus,
    icon_repeat,
    icon_sort,
    icon_search,
    icon_maximize,
    icon_restore,
    icon_fullscreen,
    icon_shuffle,
    icon_save,
    icon_open_folder,


    icon_trash,
    icon_settings,
    get_app_icon,
)
from .ui.styles import PANEL_STYLE, PLAYLIST_STYLE, MENU_STYLE, TITLE_BAR_STYLE
from .i18n import tr
from .ui.events import UIEventsMixin
from .ui.widgets import (
    ChapterSlider,
    ClickableSlider,
    IconButton,
    OverlayWindow,
    PillOverlayWindow,
    PlaylistFilterProxyModel,
    PlaylistItemDelegate,
    PlaylistListModel,
    PlaylistWidget,
    TitleBarOverlay,
)


from .utils import (
    format_duration,
    is_stream_url as _is_stream_url,
)
from .playlist import (
    PlaylistViewMixin,
    URLResolveWorker,
    _is_youtube_url,
    _youtube_direct_video_url,
)
from .logic import PlayerLogic
from .mpv_power_config import ensure_mpv_power_user_layout



class ProOverlayPlayer(QMainWindow, PlayerLogic, PlaylistViewMixin, UIEventsMixin):
    _mpv_event_signal = Signal(str)
    _seek_thumb_ready_signal = Signal(int, str)

    def __init__(self):
        QMainWindow.__init__(self)
        PlayerLogic.__init__(self)
        logging.info("ProOverlayPlayer init: module=%s", __file__)
        
        self.setWindowTitle("Cadre Player")
        self._empty_window_size = (720, 720)
        self.setMinimumSize(720, 480)
        self.resize(*self._empty_window_size)
        self.setAcceptDrops(True)
        self.setWindowIcon(get_app_icon())

        self.shuffle_enabled = load_shuffle()
        self.repeat_mode = load_repeat()
        self.playlist_durations = {} # path -> duration_str
        self.playlist_raw_durations = {} # path -> float (seconds)
        self.sort_include_folders = False
        self.scanners = []
        self.playlist_titles = {} # path/url -> display title
        self.stream_quality = load_stream_quality("best")

        self._playlist_refresh_lock = False
        self._pending_auto_next = False
        self._pending_show_background = False
        self._playlist_last_hovered = 0
        self._cached_paused = True
        self._cached_muted = False
        self._suspend_ui_poll_until = 0.0
        self._next_ui_poll_at = 0.0
        self._next_track_switch_allowed_at = 0.0
        self._pending_resize_check = False
        self._resize_sync_deadline = 0.0
        self._resize_stable_hits = 0
        self._last_resize_dims = None
        self._track_switch_cooldown = 1.10
        self._manual_switch_settle_sec = 1.10
        self._manual_switch_delay_ms = 240
        self._switch_request_id = 0
        self._next_loadfile_allowed_at = 0.0
        self._loadfile_cooldown = 0.32
        self._play_retry_pending = False
        self._playback_load_token = 0
        self._full_duration_scan_active = False
        self._full_duration_scan_cancel_requested = False
        self._full_duration_scan_total = 0
        self._full_duration_scan_done = 0
        self._mpv_event_callback_enabled = False
        self._is_engine_busy = False
        self._last_load_attempt_at = 0.0
        self._engine_busy_timeout_sec = 5.0
        self._engine_busy_settle_sec = 0.95
        self._last_track_switch_time = 0.0
        self._next_duration_scan_attempt_at = 0.0
        self._last_position = 0.0
        self._last_duration = 0.0
        self._last_progress_time = 0.0
        self._unsafe_mpv_read_allowed_at = 0.0
        self._last_seek_cmd_time = 0.0
        self._auto_next_deadline = 0.0
        self._quality_reload_until = 0.0
        self._user_paused = False
        self._pending_duration_paths = []
        self._pending_model_appends = []
        self._active_prepare_worker = None
        self._active_prepare_request = None
        self._prepare_queue = deque()
        self._active_url_worker = None
        self._active_url_request = None
        self._url_queue = deque()
        self._url_resolve_active = False
        self._is_shutting_down = False
        self._url_status_timer = QTimer(self)
        self._url_status_timer.setInterval(450)
        self._url_status_timer.timeout.connect(self._refresh_url_resolve_status)
        self._stream_auth_by_host = {}
        self._stream_quality_cache = {}
        self._stream_auth_cache_limit = 512
        self._stream_quality_cache_limit = 256
        self._mpv_prop_last_set = {}
        self._mpv_prop_error_logged = set()
        self._url_progress_count = 0

        self._append_chunk_timer = QTimer(self)
        self._append_chunk_timer.setInterval(0)
        self._append_chunk_timer.timeout.connect(self._drain_model_append_queue)
        self._import_status_timer = QTimer(self)
        self._import_status_timer.setInterval(350)
        self._import_status_timer.timeout.connect(self._refresh_import_status)
        self._import_progress_active = False
        self._import_progress_count = 0
        self._script_bindings_cache = {}
        self._script_bindings_mtime = 0.0
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(120)
        self._search_debounce_timer.timeout.connect(self.apply_playlist_filter)

        self.saved_volume = load_volume()
        self.saved_muted = load_muted()

        self.central_widget = QWidget()
        self.central_widget.setMouseTracking(True)
        self.setCentralWidget(self.central_widget)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_main_context_menu)
        self._mpv_event_signal.connect(
            self._process_mpv_event_on_main_thread,
            Qt.QueuedConnection,
        )
        self._seek_thumb_ready_signal.connect(
            self._on_seek_thumbnail_ready,
            Qt.QueuedConnection,
        )

        # Session-only toggle: do not persist Always-On-Top across relaunch.
        self.always_on_top = False

        v_config = load_video_settings()
        self.window_zoom = float(v_config.get("zoom", 0.0))
        self._video_rotate_deg = int(v_config.get("rotate", 0) or 0) % 360
        self._video_mirror_horizontal = bool(v_config.get("mirror_horizontal", False))
        self._video_mirror_vertical = bool(v_config.get("mirror_vertical", False))
        self._seek_thumbnail_preview = bool(v_config.get("seek_thumbnail_preview", False))
        self._aspect_ratio_setting = load_aspect_ratio()
        self._seek_thumb_cache = {}
        self._seek_thumb_cursor_global = None
        self._seek_thumb_request_seq = 0
        self._seek_thumb_worker_busy = False
        self._seek_thumb_pending = None
        self._seek_thumb_req_meta = {}
        self._seek_thumb_last_requested_key = None
        self._seek_thumb_last_request_at = 0.0
        self._seek_thumb_snap_seconds = 2
        self._seek_thumb_request_interval_sec = 0.08
        self._seek_thumb_cache_max_items = 220
        self._seek_thumb_temp_dir = Path(tempfile.gettempdir()) / "cadre-player-thumbnails"
        self._seek_thumb_temp_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_probe_done = False
        self._ffmpeg_available = False

        pinned = load_pinned_settings()
        self.pinned_controls = pinned["controls"]
        self.pinned_playlist = pinned["playlist"]

        self._drag_pos = None
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)

        self.video_container = QWidget(self.central_widget)
        self.video_container.setAttribute(Qt.WA_NativeWindow)
        self.video_container.setStyleSheet("background-color: black;")

        self.resize_corner_hint = QWidget(self.video_container)
        self.resize_corner_hint.setFixedSize(14, 14)
        self.resize_corner_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.resize_corner_hint.setStyleSheet(
            "background-color: rgba(255,255,255,28);"
            "border-top: 1px solid rgba(255,255,255,65);"
            "border-left: 1px solid rgba(255,255,255,65);"
            "border-right: 0;"
            "border-bottom: 0;"
            "border-top-left-radius: 3px;"
        )
        self.resize_corner_hint.hide()
        
        self.background_widget = QWidget(self.video_container)
        self.background_widget.setGeometry(0, 0, self.width(), self.height())
        layout = QVBoxLayout(self.background_widget)
        layout.setAlignment(Qt.AlignCenter)
        icon_label = QLabel()
        icon_pixmap = get_app_icon().pixmap(128, 128)
        icon_label.setPixmap(icon_pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        text_label = QLabel("Cadre Player")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("color: rgba(255,255,255,100); font-size: 24px; font-family: 'Segoe UI';")
        layout.addWidget(icon_label)
        layout.addWidget(text_label)
        self.background_widget.show()

        self._power_user_paths = ensure_mpv_power_user_layout()
        self._mpv_config_dir = self._power_user_paths["config_dir"]
        self._mpv_conf_path = self._power_user_paths["mpv_conf_path"]
        self._mpv_scripts_dir = self._power_user_paths["scripts_dir"]
        logging.info(
            "MPV power-user config: dir=%s mpv_conf=%s scripts=%s",
            self._mpv_config_dir,
            self._mpv_conf_path,
            self._mpv_scripts_dir,
        )


        self.player = mpv.MPV(
            wid=str(int(self.video_container.winId())),
            vo=v_config.get("renderer", "gpu"),
            gpu_api=v_config.get("gpu_api", "auto"),
            hwdec=v_config.get("hwdec", "auto-safe"),
            hr_seek="yes",
            input_cursor="yes",
            input_vo_keyboard="yes",
            start_event_thread=False,
            config=True,
            config_dir=self._mpv_config_dir,
        )
        self._set_mpv_property_safe("pause", True, allow_during_busy=True)
        self._cached_paused = True
        self.apply_stream_quality_setting()

        QTimer.singleShot(500, self._apply_mpv_startup_commands)
        self.overlay = OverlayWindow(self)
        self.speed_overlay = PillOverlayWindow(self)
        self.playlist_overlay = OverlayWindow(self)
        self.title_bar = TitleBarOverlay(self)

        self.speed_indicator_timer = QTimer(self)
        self.speed_indicator_timer.setSingleShot(True)
        self.speed_indicator_timer.setInterval(900)
        self.speed_indicator_timer.timeout.connect(self.speed_overlay.hide)
        self._status_overlay_default_ms = 900
        self._status_overlay_error_ms = 3200

        self.playlist_auto_hide_timer = QTimer(self)
        self.playlist_auto_hide_timer.setSingleShot(True)
        self.playlist_auto_hide_timer.setInterval(3000) # 3 second delay
        self.playlist_auto_hide_timer.timeout.connect(self.playlist_overlay.hide)

        try:
            # Disabled for stability: python-mpv event.as_dict() has been causing
            # native crashes in long sessions with rapid track changes.
            if self._mpv_event_callback_enabled:
                self.player.register_event_callback(self._on_mpv_event)
            self.apply_subtitle_settings()
            self.apply_video_settings()
            self.set_aspect_ratio(self._aspect_ratio_setting)
            self.apply_equalizer_settings()
        except Exception:
            pass

        self.setup_ui()
        self.setup_playlist_ui()
        QApplication.instance().installEventFilter(self)

        self.overlay.hide()
        self.speed_overlay.hide()
        self.playlist_overlay.hide()
        self.title_bar.hide()

        if self.pinned_controls or self.current_index < 0:
            self.overlay.show()
        if self.current_index < 0 and self._is_app_focused():
            self.title_bar.show()
        if self.pinned_playlist:
            self.playlist_overlay.show()

        self.mouse_timer = QTimer(self)
        self.mouse_timer.setInterval(100)
        self.mouse_timer.timeout.connect(self.check_mouse_pos)
        self.mouse_timer.start()
        
        self.last_cursor_global_pos = QCursor.pos()
        self.cursor_idle_time = 0

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(100) # Increased frequency from 200ms
        self.ui_timer.timeout.connect(self.force_ui_update)
        self.ui_timer.start()

        self.dragpos = None
        self._is_resizing = False # Add this
        self._context_menu_open = False
        self._fullscreen_transition_active = False

    # Explicit UI-event overrides to ensure Qt dispatch reaches UIEventsMixin.
    def eventFilter(self, obj, event):
        return UIEventsMixin.eventFilter(self, obj, event)

    def mouseDoubleClickEvent(self, event):
        return UIEventsMixin.mouseDoubleClickEvent(self, event)

    def wheelEvent(self, event):
        return UIEventsMixin.wheelEvent(self, event)

    def mousePressEvent(self, event):
        return UIEventsMixin.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        return UIEventsMixin.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        return UIEventsMixin.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event):
        return UIEventsMixin.keyPressEvent(self, event)

    def resizeEvent(self, event):
        return UIEventsMixin.resizeEvent(self, event)

    def moveEvent(self, event):
        return UIEventsMixin.moveEvent(self, event)

    def changeEvent(self, event):
        return UIEventsMixin.changeEvent(self, event)

    def dragEnterEvent(self, event):
        return UIEventsMixin.dragEnterEvent(self, event)

    def dropEvent(self, event):
        return UIEventsMixin.dropEvent(self, event)

    def _apply_mpv_startup_commands(self):
        # Keep startup hook for diagnostics only.
        # Do not override power-user mpv.conf values here.
        logging.info("MPV startup hook: preserving mpv.conf runtime properties")

    def _can_write_mpv_property(self, allow_during_busy: bool = False) -> bool:
        if self._is_shutting_down:
            return False
        if allow_during_busy:
            return True
        if self._is_engine_busy:
            return False
        if time.monotonic() < self._unsafe_mpv_read_allowed_at:
            return False
        return True

    def _set_mpv_property_safe(
        self,
        prop: str,
        value,
        *,
        allow_during_busy: bool = False,
        min_interval_sec: float = 0.0,
    ) -> bool:
        if not self._can_write_mpv_property(allow_during_busy=allow_during_busy):
            return False
        key = str(prop or "").strip()
        if not key:
            return False
        cmd_key = key.replace("_", "-")
        now = time.monotonic()
        if min_interval_sec > 0:
            last = float(self._mpv_prop_last_set.get(key, 0.0))
            if (now - last) < min_interval_sec:
                return False
        try:
            if isinstance(value, bool):
                mpv_value = "yes" if value else "no"
            elif value is None:
                mpv_value = ""
            else:
                mpv_value = str(value)
            self.player.command("set", cmd_key, mpv_value)
            self._mpv_prop_last_set[key] = now
            self._mpv_prop_error_logged.discard(key)
            return True
        except Exception as e:
            if key not in self._mpv_prop_error_logged:
                self._mpv_prop_error_logged.add(key)
                logging.warning(
                    "MPV property set failed: prop=%s value=%r err=%s",
                    key,
                    value,
                    e,
                )
            return False

    def setup_ui(self):
        self.overlay.panel.setStyleSheet(PANEL_STYLE)
        self.apply_panel_shadow(self.overlay.panel, blur=26, offset_y=8)

        self.title_bar.setStyleSheet(TITLE_BAR_STYLE)
        self.title_bar.min_btn.setIcon(QIcon(icon_minus(18)))
        self.title_bar.max_btn.setIcon(QIcon(icon_maximize(18)))
        self.title_bar.close_btn.setIcon(QIcon(icon_close(18)))
        # No shadow needed as we have a gradient bg

        self.prev_btn = IconButton(parent=self)
        self.prev_btn.clicked.connect(self.prev_video)

        self.play_btn = IconButton(parent=self)
        self.play_btn.clicked.connect(self.toggle_play)

        self.next_btn = IconButton(parent=self)
        self.next_btn.clicked.connect(self.next_video)

        self.stop_btn = IconButton(tooltip=tr("Stop"), parent=self)
        self.stop_btn.clicked.connect(self.stop_playback)

        self.playlist_btn = IconButton(tooltip=tr("Toggle playlist"), parent=self)
        self.playlist_btn.clicked.connect(self.toggle_playlist_panel)
        self.playlist_btn.setIcon(QIcon(icon_playlist(22)))

        self.fullscreen_btn = IconButton(tooltip=tr("Toggle fullscreen"), parent=self)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        self.fullscreen_btn.setIcon(QIcon(icon_fullscreen(22)))

        self.add_main_btn = IconButton(tooltip=tr("Add content"), parent=self)
        self.add_main_btn.setIcon(QIcon(icon_plus(22)))
        self.add_main_btn.clicked.connect(self.show_add_menu_main)

        self.settings_btn = IconButton(tooltip=tr("Settings"), parent=self)
        self.settings_btn.clicked.connect(self.show_settings_menu)
        self.settings_btn.setIcon(QIcon(icon_settings(22)))

        self.mute_btn = IconButton(tooltip=tr("Volume"), parent=self)
        self.mute_btn.clicked.connect(self.toggle_volume_popup)

        self.seek_slider = ChapterSlider(Qt.Horizontal)
        self.seek_slider.setFocusPolicy(Qt.NoFocus)
        self.seek_slider.sliderMoved.connect(self.seek_absolute)
        self.seek_slider.set_preview_enabled(self._seek_thumbnail_preview)
        self.seek_slider.previewRequested.connect(self.request_seek_thumbnail_preview)
        self.seek_slider.previewHidden.connect(self.hide_seek_thumbnail_preview)
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.seek_thumb_preview = QWidget(self)
        self.seek_thumb_preview.setVisible(False)
        self.seek_thumb_preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.seek_thumb_preview.setStyleSheet(
            "background-color: rgba(18, 18, 18, 235);"
            "border: 1px solid rgba(255,255,255,48);"
            "border-radius: 7px;"
        )
        thumb_layout = QVBoxLayout(self.seek_thumb_preview)
        thumb_layout.setContentsMargins(6, 6, 6, 6)
        thumb_layout.setSpacing(4)
        self.seek_thumb_image_label = QLabel(self.seek_thumb_preview)
        self.seek_thumb_image_label.setAlignment(Qt.AlignCenter)
        self.seek_thumb_time_label = QLabel("00:00", self.seek_thumb_preview)
        self.seek_thumb_time_label.setAlignment(Qt.AlignCenter)
        self.seek_thumb_time_label.setStyleSheet(
            "color: rgba(255,255,255,230);"
            "font-size: 11px;"
            "font-family: 'Segoe UI';"
            "font-weight: 600;"
        )
        thumb_layout.addWidget(self.seek_thumb_image_label)
        thumb_layout.addWidget(self.seek_thumb_time_label)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(92)
        self.time_label.setAlignment(Qt.AlignCenter)

        self.volume_popup = QWidget(self)
        self.volume_popup.setVisible(False)
        self.volume_popup.setAttribute(Qt.WA_StyledBackground, True)
        self.volume_popup.setStyleSheet(
            "background-color: rgba(18, 18, 18, 238);"
            "border: 1px solid rgba(255,255,255,42);"
            "border-radius: 10px;"
        )
        popup_layout = QVBoxLayout(self.volume_popup)
        popup_layout.setContentsMargins(8, 8, 8, 8)
        popup_layout.setSpacing(6)

        self.popup_mute_btn = IconButton(tooltip=tr("Mute / Unmute"), parent=self.volume_popup)
        self.popup_mute_btn.clicked.connect(self.toggle_mute)
        popup_layout.addWidget(self.popup_mute_btn, 0, Qt.AlignHCenter)

        self.vol_slider = ClickableSlider(Qt.Vertical)
        self.vol_slider.setFocusPolicy(Qt.NoFocus)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.saved_volume)
        self.vol_slider.setFixedHeight(112)
        self.vol_slider.setFixedWidth(20)
        self.vol_slider.setStyleSheet(
            "QSlider::groove:vertical {"
            "  background: rgba(255,255,255,22);"
            "  width: 4px;"
            "  border-radius: 2px;"
            "}"
            "QSlider::sub-page:vertical {"
            "  background: rgba(235,235,235,180);"
            "  border-radius: 2px;"
            "}"
            "QSlider::add-page:vertical {"
            "  background: rgba(255,255,255,10);"
            "  border-radius: 2px;"
            "}"
            "QSlider::handle:vertical {"
            "  background: rgba(255,255,255,230);"
            "  height: 10px;"
            "  margin: 0 -6px;"
            "  border-radius: 4px;"
            "}"
        )
        self.vol_slider.valueChanged.connect(self.on_volume_changed)
        popup_layout.addWidget(self.vol_slider, 1, Qt.AlignHCenter)

        self.player.volume = self.saved_volume
        self.player.mute = self.saved_muted
        self._cached_muted = bool(self.saved_muted)

        layout = QHBoxLayout(self.overlay.panel)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.next_btn)
        layout.addSpacing(3)
        layout.addWidget(self.seek_slider, 1)
        layout.addSpacing(3)
        layout.addWidget(self.time_label)
        layout.addWidget(self.mute_btn)
        layout.addSpacing(4)
        layout.addWidget(self.settings_btn)
        layout.addWidget(self.add_main_btn)
        layout.addWidget(self.fullscreen_btn)
        layout.addWidget(self.playlist_btn)

        self.update_transport_icons()
        self.update_mute_icon()

    def _is_local_playlist_item(self, media_path: str) -> bool:
        token = str(media_path or "").strip()
        if not token or _is_stream_url(token):
            return False
        p = Path(token)
        return p.exists() and p.is_file()

    def _probe_ffmpeg_available(self) -> bool:
        if self._ffmpeg_probe_done:
            return self._ffmpeg_available
        self._ffmpeg_probe_done = True
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                check=False,
                capture_output=True,
                timeout=3,
                text=True,
            )
            self._ffmpeg_available = bool(result.returncode == 0)
        except Exception:
            self._ffmpeg_available = False
        return self._ffmpeg_available

    def hide_seek_thumbnail_preview(self):
        if hasattr(self, "seek_thumb_preview"):
            self.seek_thumb_preview.hide()

    def _cache_seek_thumbnail(self, media_path: str, snapped_sec: int, image_path: str):
        key = (str(media_path), int(snapped_sec))
        self._seek_thumb_cache[key] = image_path
        while len(self._seek_thumb_cache) > int(self._seek_thumb_cache_max_items):
            try:
                self._seek_thumb_cache.pop(next(iter(self._seek_thumb_cache)))
            except StopIteration:
                break

    def _nearest_cached_seek_thumbnail(self, media_path: str, snapped_sec: int, max_distance: int = 24) -> str | None:
        target_path = str(media_path)
        target_sec = int(snapped_sec)
        best_dist = int(max_distance) + 1
        best_path = None
        for (path_key, sec_key), image_path in self._seek_thumb_cache.items():
            if path_key != target_path:
                continue
            if not image_path or not Path(image_path).exists():
                continue
            dist = abs(int(sec_key) - target_sec)
            if dist < best_dist:
                best_dist = dist
                best_path = image_path
        return best_path if best_dist <= int(max_distance) else None

    def request_seek_thumbnail_preview(self, seconds: float, cursor_global):
        if not self._seek_thumbnail_preview:
            self.hide_seek_thumbnail_preview()
            return
        if self.current_index < 0 or self.current_index >= len(self.playlist):
            self.hide_seek_thumbnail_preview()
            return
        media_path = str(self.playlist[self.current_index] or "")
        if not self._is_local_playlist_item(media_path):
            self.hide_seek_thumbnail_preview()
            return
        if not self._probe_ffmpeg_available():
            self.hide_seek_thumbnail_preview()
            return
        try:
            sec_int = max(0, int(round(float(seconds))))
        except (TypeError, ValueError):
            self.hide_seek_thumbnail_preview()
            return

        self._seek_thumb_cursor_global = cursor_global
        self.seek_thumb_time_label.setText(format_duration(float(sec_int)))
        snap_unit = max(1, int(self._seek_thumb_snap_seconds))
        snapped_sec = (sec_int // snap_unit) * snap_unit
        cache_key = (media_path, snapped_sec)
        cached = self._seek_thumb_cache.get(cache_key)
        if cached and Path(cached).exists():
            self._show_seek_thumbnail_widget(cached)
            return
        nearest_cached = self._nearest_cached_seek_thumbnail(media_path, snapped_sec)
        if nearest_cached:
            self._show_seek_thumbnail_widget(nearest_cached)

        now = time.monotonic()
        if (
            self._seek_thumb_last_requested_key == cache_key
            and (now - self._seek_thumb_last_request_at) < self._seek_thumb_request_interval_sec
        ):
            return

        self._seek_thumb_request_seq += 1
        req_id = int(self._seek_thumb_request_seq)
        self._seek_thumb_pending = (media_path, snapped_sec, req_id)
        self._seek_thumb_last_requested_key = cache_key
        self._seek_thumb_last_request_at = now
        if self._seek_thumb_worker_busy:
            return
        self._start_seek_thumbnail_worker()

    def _show_seek_thumbnail_widget(self, image_path: str):
        if not image_path or not Path(image_path).exists():
            self.hide_seek_thumbnail_preview()
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self.hide_seek_thumbnail_preview()
            return
        scaled = pixmap.scaled(220, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.seek_thumb_image_label.setPixmap(scaled)
        self.seek_thumb_image_label.setFixedSize(scaled.size())
        self.seek_thumb_preview.adjustSize()

        if self._seek_thumb_cursor_global is not None:
            local = self.mapFromGlobal(self._seek_thumb_cursor_global)
            win_w = self.width()
            win_h = self.height()
            x = int(local.x() - (self.seek_thumb_preview.width() // 2))
            y = int(local.y() - self.seek_thumb_preview.height() - 16)

            # Keep preview above controls if panel is visible.
            controls_top = self.seek_slider.mapTo(self, QPoint(0, 0)).y()
            if hasattr(self, "overlay") and self.overlay.isVisible():
                panel_top_global = self.overlay.panel.mapToGlobal(QPoint(0, 0)).y()
                controls_top = min(controls_top, self.mapFromGlobal(QPoint(0, panel_top_global)).y())
            y = min(y, int(controls_top - self.seek_thumb_preview.height() - 8))

            x = max(8, min(x, max(8, win_w - self.seek_thumb_preview.width() - 8)))
            y = max(8, min(y, max(8, win_h - self.seek_thumb_preview.height() - 8)))
            self.seek_thumb_preview.move(x, y)
        self.seek_thumb_preview.show()
        self.seek_thumb_preview.raise_()

    def _start_seek_thumbnail_worker(self):
        if not self._seek_thumb_pending or self._seek_thumb_worker_busy:
            return
        media_path, sec_int, req_id = self._seek_thumb_pending
        self._seek_thumb_pending = None
        self._seek_thumb_worker_busy = True
        self._seek_thumb_req_meta[int(req_id)] = (str(media_path), int(sec_int))

        def _worker(path: str, sec: int, request_id: int):
            token = hashlib.sha1(f"{path}|{sec}".encode("utf-8", errors="ignore")).hexdigest()
            output = self._seek_thumb_temp_dir / f"{token}.jpg"
            if not output.exists():
                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-ss",
                            str(sec),
                            "-i",
                            str(path),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=320:-1:force_original_aspect_ratio=decrease",
                            str(output),
                        ],
                        check=False,
                        capture_output=True,
                        timeout=7,
                    )
                except Exception:
                    pass
            self._seek_thumb_ready_signal.emit(int(request_id), str(output) if output.exists() else "")

        threading.Thread(
            target=_worker,
            args=(media_path, sec_int, req_id),
            daemon=True,
        ).start()

    def _on_seek_thumbnail_ready(self, request_id: int, image_path: str):
        self._seek_thumb_worker_busy = False
        meta = self._seek_thumb_req_meta.pop(int(request_id), None)
        if self._seek_thumb_pending:
            self._start_seek_thumbnail_worker()
        if image_path and meta is not None:
            media_path, snapped_sec = meta
            self._cache_seek_thumbnail(media_path, snapped_sec, image_path)
        if request_id != self._seek_thumb_request_seq:
            return
        if not image_path or meta is None or self.current_index < 0 or self.current_index >= len(self.playlist):
            self.hide_seek_thumbnail_preview()
            return
        media_path, snapped_sec = meta
        current_path = str(self.playlist[self.current_index] or "")
        if str(media_path) != current_path:
            return
        self._show_seek_thumbnail_widget(image_path)

    def toggle_volume_popup(self):
        if self.volume_popup.isVisible():
            self.volume_popup.hide()
            return
        self.show_volume_popup()

    def show_volume_popup(self):
        self.volume_popup.adjustSize()
        # Use global mapping because controls live in an overlay window.
        anchor_global = self.mute_btn.mapToGlobal(QPoint(self.mute_btn.width() // 2, 0))
        anchor = self.mapFromGlobal(anchor_global)
        x = int(anchor.x() - (self.volume_popup.width() // 2))
        y = int(anchor.y() - self.volume_popup.height() - 8)

        # Never let the popup drop under the control bar.
        if hasattr(self, "overlay") and self.overlay.isVisible():
            panel_top_global = self.overlay.panel.mapToGlobal(QPoint(0, 0)).y()
            panel_top_local = self.mapFromGlobal(QPoint(0, panel_top_global)).y()
            y = min(y, int(panel_top_local - self.volume_popup.height() - 6))

        x = max(8, min(x, max(8, self.width() - self.volume_popup.width() - 8)))
        y = max(8, min(y, max(8, self.height() - self.volume_popup.height() - 8)))
        self.volume_popup.move(x, y)
        self.volume_popup.show()
        self.volume_popup.raise_()

    def setup_playlist_ui(self):
        self.playlist_overlay.panel.setObjectName("PlaylistPanel")
        self.playlist_overlay.panel.setStyleSheet(PLAYLIST_STYLE)
        self.playlist_overlay.setAttribute(Qt.WA_TranslucentBackground)
        
        # External window shadow
        self.apply_panel_shadow(self.playlist_overlay.panel, blur=30, offset_y=0)

        layout = QVBoxLayout(self.playlist_overlay.panel)
        layout.setContentsMargins(12, 40, 12, 12) # Leave space for title bar buttons
        layout.setSpacing(10)

        self.playlist_widget = PlaylistWidget()
        self.playlist_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # Remove horizontal scroll
        self.playlist_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.playlist_widget.setDefaultDropAction(Qt.MoveAction)
        self.playlist_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_model = PlaylistListModel(self)
        self.playlist_filter_model = PlaylistFilterProxyModel(self)
        self.playlist_filter_model.setSourceModel(self.playlist_model)
        self.playlist_widget.setModel(self.playlist_filter_model)
        self.playlist_delegate = PlaylistItemDelegate(self.playlist_widget)
        self.playlist_widget.setItemDelegate(self.playlist_delegate)

        self.playlist_widget.doubleClicked.connect(self.play_selected_item)
        self.playlist_widget.customContextMenuRequested.connect(
            self.open_playlist_context_menu
        )
        self.playlist_model.rowsMoved.connect(
            lambda *_: self.sync_playlist_from_widget()
        )
        self.playlist_model.orderChanged.connect(self.sync_playlist_from_widget)
        layout.addWidget(self.playlist_widget, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8) # Increased spacing
        controls.setContentsMargins(4, 8, 4, 4) # Add some breathability

        self.shuffle_btn = IconButton(tooltip=tr("Shuffle"), checkable=True, parent=self)
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        self.shuffle_btn.setIcon(QIcon(icon_shuffle(22)))
        self.repeat_btn = IconButton(tooltip=tr("Repeat mode"), parent=self)
        self.repeat_btn.clicked.connect(self.cycle_repeat_mode)
        self.repeat_btn.setIcon(QIcon(icon_repeat(22)))
        self.add_btn = IconButton(tooltip=tr("Add content"), parent=self)
        self.add_btn.setIcon(QIcon(icon_plus(22)))

        self.search_btn = IconButton(tooltip=tr("Search playlist"), parent=self)
        self.search_btn.clicked.connect(self.toggle_playlist_search)
        self.search_btn.setIcon(QIcon(icon_search(22)))
        self.search_btn.setCheckable(True)

        self.playlist_search_input = QLineEdit(self.playlist_overlay.panel)
        self.playlist_search_input.setPlaceholderText(tr("Search in playlist..."))
        self.playlist_search_input.setClearButtonEnabled(True)
        self.playlist_search_input.setMaximumWidth(220)
        self.playlist_search_input.setVisible(False)
        self.playlist_search_input.textChanged.connect(self.schedule_playlist_filter)

        self.add_menu = QMenu(self)
        self.add_menu.setStyleSheet(MENU_STYLE)
        
        file_act = self.add_menu.addAction(tr("File"))
        file_act.triggered.connect(self.add_files_dialog)
        
        folder_act = self.add_menu.addAction(tr("Folder"))
        folder_act.triggered.connect(self.add_folder_dialog)
        
        url_act = self.add_menu.addAction(tr("URL"))
        url_act.triggered.connect(self.open_url_dialog)
        
        self.add_btn.clicked.connect(self.show_add_menu)

        self.open_playlist_btn = IconButton(tooltip=tr("Open M3U Playlist"), parent=self)
        self.open_playlist_btn.clicked.connect(self.load_playlist_m3u)
        self.open_playlist_btn.setIcon(QIcon(icon_open_folder(22)))

        self.save_playlist_btn = IconButton(tooltip=tr("Save M3U Playlist"), parent=self)
        self.save_playlist_btn.clicked.connect(self.save_playlist_m3u)
        self.save_playlist_btn.setIcon(QIcon(icon_save(22)))

        self.restore_session_btn = IconButton(tooltip=tr("Restore last session playlist"), parent=self)
        self.restore_session_btn.clicked.connect(self.restore_session_playlist)
        self.restore_session_btn.setIcon(QIcon(icon_folder(22)))


        self.remove_btn = IconButton(tooltip=tr("Remove from playlist"), parent=self)
        self.remove_btn.clicked.connect(self.remove_selected_from_playlist)
        self.remove_btn.setIcon(QIcon(icon_minus(22)))

        self.sort_btn = IconButton(tooltip=tr("Sort Playlist"), parent=self)
        self.sort_btn.clicked.connect(self.show_sort_menu)
        self.sort_btn.setIcon(QIcon(icon_sort(22)))


        self.delete_file_btn = IconButton(tooltip=tr("Delete file to recycle bin"), parent=self)
        self.delete_file_btn.clicked.connect(self.delete_selected_file_to_trash)
        self.delete_file_btn.setIcon(QIcon(icon_trash(22)))

        controls.setSpacing(2)
        controls.addWidget(self.search_btn)
        controls.addWidget(self.playlist_search_input)

        # Group 1: Shuffle/Repeat
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        
        controls.addStretch(1)
        
        # Group 2: Add/Open/Save
        controls.addWidget(self.add_btn)
        controls.addWidget(self.open_playlist_btn)
        controls.addWidget(self.save_playlist_btn)
        controls.addWidget(self.restore_session_btn)
        
        controls.addStretch(1)
        
        # Group 3: Sort/Remove/Recycle
        controls.addWidget(self.sort_btn)
        controls.addWidget(self.remove_btn)
        controls.addWidget(self.delete_file_btn)
        
        layout.addLayout(controls)
        self.update_mode_buttons()

    def closeEvent(self, event):
        if self._is_shutting_down:
            event.accept()
            return
        self._is_shutting_down = True
        logging.info("Close event: shutdown begin")
        # External watchdog: survives native deadlocks that can block Python threads/GIL.
        try:
            pid = os.getpid()
            if os.name == "nt":
                cmd = f"timeout /t 4 /nobreak >nul & taskkill /F /PID {pid} >nul 2>&1"
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen(["cmd", "/c", cmd], creationflags=flags)
            else:
                subprocess.Popen(
                    [sys.executable, "-c", "import os,sys,time; time.sleep(4); os.kill(int(sys.argv[1]), 9)", str(pid)],
                    start_new_session=True,
                )
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        # Hard-exit watchdog: guarantees terminal returns even if native threads hang.
        killer = threading.Timer(2.5, lambda: os._exit(0))
        killer.daemon = True
        killer.start()

        self.save_current_resume_info()
        self._save_session_playlist_snapshot()
        
        # Stop timers
        if hasattr(self, "mouse_timer"):
            self.mouse_timer.stop()
        if hasattr(self, "ui_timer"):
            self.ui_timer.stop()
        if hasattr(self, "_append_chunk_timer"):
            self._append_chunk_timer.stop()
        if hasattr(self, "_import_status_timer"):
            self._import_status_timer.stop()
        if hasattr(self, "_url_status_timer"):
            self._url_status_timer.stop()
        self._stop_import_progress()
        self._stop_url_resolve_status()
        self._shutdown_background_workers()

        # Explicitly close and delete all overlay windows
        for attr in ["overlay", "speed_overlay", "playlist_overlay", "title_bar"]:
            if hasattr(self, attr):
                win = getattr(self, attr)
                win.close()
                win.deleteLater()

        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
            app.exit(0)

        # Avoid terminate() here; python-mpv can deadlock/crash during close.

        logging.info("Close event: shutdown dispatch complete")
        event.accept()
        super().closeEvent(event)

    def _shutdown_background_workers(self):
        url_worker = self._active_url_worker
        prepare_worker = self._active_prepare_worker
        scanners = list(self.scanners)

        self._active_url_worker = None
        self._active_url_request = None
        self._url_queue.clear()

        self._active_prepare_worker = None
        self._active_prepare_request = None
        self._prepare_queue.clear()

        self.scanners.clear()
        self._pending_duration_paths.clear()
        self._pending_model_appends.clear()

        if url_worker is not None:
            try:
                url_worker.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                url_worker.requestInterruption()
                url_worker.quit()
            except (RuntimeError, TypeError):
                pass

        if prepare_worker is not None:
            try:
                prepare_worker.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                prepare_worker.requestInterruption()
                prepare_worker.quit()
            except (RuntimeError, TypeError):
                pass

        for scanner in scanners:
            try:
                scanner.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                scanner.requestInterruption()
                scanner.quit()
            except (RuntimeError, TypeError):
                pass

    def _create_url_resolve_worker(self, urls, auth=None):
        return URLResolveWorker(urls, auth=auth)

    def _schedule_play_current_retry(self, now: float) -> bool:
        if now >= self._next_loadfile_allowed_at:
            return False
        delay_ms = max(20, int((self._next_loadfile_allowed_at - now) * 1000))
        if not self._play_retry_pending:
            self._play_retry_pending = True

            def _retry():
                self._play_retry_pending = False
                self.play_current()

            QTimer.singleShot(delay_ms, _retry)
        return True

    def _apply_stream_auth_header_for_current(self, current_file) -> None:
        try:
            parsed = urlparse(str(current_file))
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                host = parsed.netloc.split("@")[-1].lower()
                auth_value = self._stream_auth_by_host.get(host)
                if auth_value:
                    self._set_mpv_property_safe(
                        "http_header_fields",
                        f"Authorization: {auth_value}",
                        allow_during_busy=True,
                    )
                else:
                    self._set_mpv_property_safe(
                        "http_header_fields",
                        "",
                        allow_during_busy=True,
                    )
            else:
                self._set_mpv_property_safe(
                    "http_header_fields",
                    "",
                    allow_during_busy=True,
                )
        except (TypeError, ValueError):
            pass

    def _apply_seek_profile_for_source(self, current_file) -> None:
        source = str(current_file or "")
        stream_source = _is_stream_url(source)
        if stream_source:
            profile = {
                "cache": "yes",
                "demuxer_max_bytes": "1000M",
                "demuxer_max_back_bytes": "200M",
                "force_seekable": "yes",
                "hr_seek": "no",
                # Clear any config-level extractor override that can cap YouTube quality.
                "ytdl_raw_options": "",
            }
        else:
            profile = {
                "cache": "auto",
                "demuxer_max_bytes": "64M",
                "demuxer_max_back_bytes": "16M",
                "force_seekable": "no",
                "hr_seek": "yes",
                "ytdl_raw_options": "",
            }
        for prop, value in profile.items():
            self._set_mpv_property_safe(prop, value, allow_during_busy=True)

    def _prepare_playback_switch_state(self, current_file) -> None:
        self._pending_auto_next = False
        self._pending_show_background = False
        self._last_track_switch_time = time.monotonic()
        # Always keep a bounded post-load resize probe as a hard fallback.
        # Some files expose dimensions only after decode starts.
        self._pending_resize_check = True
        self._resize_stable_hits = 0
        self._last_resize_dims = None
        self._resize_sync_deadline = time.monotonic() + (
            6.0 if _is_stream_url(str(current_file)) else 3.0
        )
        self._auto_next_deadline = 0.0
        self._user_paused = False
        self._last_position = 0.0
        self._last_duration = 0.0
        self._last_progress_time = 0.0
        self._unsafe_mpv_read_allowed_at = time.monotonic() + 1.25
        # Do not force speed here; rapid set_property calls can crash on some mpv builds.
        # Give mpv more settle time between rapid switches before property polling.
        self._suspend_ui_poll_until = time.monotonic() + 0.95
        self._next_ui_poll_at = self._suspend_ui_poll_until

    def _load_current_file_with_resize_strategy(self, current_file, load_token: int) -> None:
        loaded_paused = False
        # Prefer paused load first so first visible frame can be sized correctly.
        try:
            self.player.command("loadfile", current_file, "replace", "pause=yes")
            loaded_paused = True
        except Exception:
            self.player.command("loadfile", current_file, "replace")
        if loaded_paused:
            max_attempts = 18 if _is_stream_url(str(current_file)) else 8
            QTimer.singleShot(
                80,
                lambda t=load_token, m=max_attempts: self._await_initial_resize_then_unpause(
                    t,
                    attempt=0,
                    max_attempts=m,
                ),
            )
        else:
            # Keep playback state consistent across mpv/python-mpv combinations.
            QTimer.singleShot(120, lambda t=load_token: self._ensure_playback_unpaused(t))
            QTimer.singleShot(380, lambda t=load_token: self._ensure_playback_unpaused(t))

    def _reset_ui_for_loaded_track(self, current_file, load_token: int) -> None:
        self.background_widget.hide()
        self._cached_paused = False
        known_duration = 0.0
        try:
            known_duration = float(self.playlist_raw_durations.get(str(current_file), 0.0) or 0.0)
        except (TypeError, ValueError):
            known_duration = 0.0
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setRange(0, max(0, int(round(known_duration))))
            self.seek_slider.setValue(0)
        self.seek_slider.set_current_time(0.0)
        self.seek_slider.set_chapters([])
        if known_duration > 0:
            self.time_label.setText(f"00:00 / {format_duration(known_duration)}")
        else:
            self.time_label.setText("00:00 / 00:00")
        self.update_transport_icons()
        self.sync_shuffle_pos_to_current()
        QTimer.singleShot(
            0,
            lambda t=load_token: self.highlight_current_item() if t == self._playback_load_token else None,
        )

    def _display_name_for_track(self, current_file) -> str:
        display_name = self.playlist_titles.get(str(current_file))
        if display_name:
            return display_name
        try:
            parsed = urlparse(str(current_file))
            if parsed.scheme and parsed.netloc:
                if _is_youtube_url(str(current_file)):
                    direct_yt = _youtube_direct_video_url(str(current_file))
                    if direct_yt:
                        vid = parse_qs(urlparse(direct_yt).query).get("v", [""])[0]
                        return f"YouTube {vid}" if vid else "YouTube"
                    return "YouTube"
                return unquote(Path(parsed.path.rstrip("/")).name) or parsed.netloc
            return Path(str(current_file)).name
        except (TypeError, ValueError):
            return str(current_file)

    def _update_window_title_for_track(self, current_file) -> None:
        display_name = self._display_name_for_track(current_file)
        title = f"[{self.current_index + 1}/{len(self.playlist)}] {display_name}"
        self.setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.info_label.setText(title)

    def _schedule_resume_and_chapter_refresh(self, current_file, load_token: int) -> None:
        # Resume logic
        resume_pos = load_resume_position(current_file)
        if resume_pos > 5:  # Only resume if more than 5 seconds in
            QTimer.singleShot(
                240,
                lambda t=load_token, p=str(current_file), pos=resume_pos: self._safe_resume_seek(t, p, pos, 0),
            )
        # Chapter metadata can arrive late for some formats/streams.
        QTimer.singleShot(1450, lambda t=load_token: self._refresh_chapter_markers(t))
        QTimer.singleShot(2300, lambda t=load_token: self._refresh_chapter_markers(t))
        QTimer.singleShot(3300, lambda t=load_token: self._refresh_chapter_markers(t))

    def play_current(self):
        if self._full_duration_scan_active:
            self.show_status_overlay(tr("Duration scan is running (F4 to cancel)"))
            return
        if self._is_shutting_down:
            return
        if not (0 <= self.current_index < len(self.playlist)):
            return
        now = time.monotonic()
        if self._schedule_play_current_retry(now):
            return
        self._next_loadfile_allowed_at = now + self._loadfile_cooldown
        self._next_track_switch_allowed_at = max(
            self._next_track_switch_allowed_at,
            now + self._manual_switch_settle_sec,
        )
        self._is_engine_busy = True
        self._last_load_attempt_at = now
        self._play_retry_pending = False
        self._playback_load_token += 1
        load_token = self._playback_load_token
        QTimer.singleShot(
            int(self._engine_busy_settle_sec * 1000),
            lambda t=load_token: self._release_engine_busy_if_current(t),
        )

        current_file = self.playlist[self.current_index]
        self._apply_stream_auth_header_for_current(current_file)
        self._apply_seek_profile_for_source(current_file)
        self._prepare_playback_switch_state(current_file)
        self._load_current_file_with_resize_strategy(current_file, load_token)
        self._reset_ui_for_loaded_track(current_file, load_token)
        self._update_window_title_for_track(current_file)
        self._schedule_resume_and_chapter_refresh(current_file, load_token)

        # Avoid frequent mpv property reads here; explicit sync_size calls remain available.

    def _ensure_playback_unpaused(self, load_token: int):
        if self._is_shutting_down:
            return
        if load_token != self._playback_load_token:
            return
        if self._full_duration_scan_active:
            return
        if self.current_index < 0:
            return
        self._set_mpv_property_safe("pause", False, allow_during_busy=True)

    def _release_engine_busy_if_current(self, load_token: int):
        if load_token != self._playback_load_token:
            return
        self._is_engine_busy = False

    def _safe_resume_seek(self, load_token: int, expected_path: str, pos, attempt: int = 0):
        try:
            if self._is_shutting_down:
                return
            if load_token != self._playback_load_token:
                return
            if not (0 <= self.current_index < len(self.playlist)):
                return
            if str(self.playlist[self.current_index]) != str(expected_path):
                return
            self.player.command("seek", float(pos), "absolute", "keyframes")
            self.show_status_overlay(tr("Resumed from {}").format(format_duration(pos)))
        except Exception:
            if attempt < 8:
                QTimer.singleShot(
                    220,
                    lambda t=load_token, p=expected_path, s=pos, a=attempt + 1: self._safe_resume_seek(t, p, s, a),
                )

    def stop_playback(self):
        self.save_current_resume_info()
        # Cancel any delayed/scheduled switch from rapid navigation.
        self._switch_request_id += 1
        # Ensure stop never triggers a deferred auto-next transition.
        self._pending_auto_next = False
        self._auto_next_deadline = 0.0
        self._is_engine_busy = False
        self.player.command("stop")
        self.background_widget.show()
        self._cached_paused = True
        self._user_paused = True
        # Reset cached timeline so Play after Stop restarts current item.
        self._last_position = 0.0
        self._last_duration = 0.0
        self._last_progress_time = 0.0
        self.time_label.setText("00:00 / 00:00")
        self.seek_slider.setValue(0)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.set_current_time(0.0)
        self.seek_slider.set_chapters([])
        self.update_transport_icons()
        self.setWindowTitle("Cadre Player")
        if hasattr(self, "title_bar"):
            self.title_bar.info_label.setText("")
        self.sync_size()

    def _on_mpv_event(self, event):
        try:
            # Keep callback minimal and avoid event.as_dict() due ctypes instability.
            name = None
            if hasattr(event, "event_id") and hasattr(event.event_id, "name"):
                name = event.event_id.name
            elif hasattr(event, "name"):
                name = event.name
            if isinstance(name, bytes):
                name = name.decode(errors="ignore")
            if not name:
                return
            self._mpv_event_signal.emit(str(name))
        except Exception:
            pass

    def _process_mpv_event_on_main_thread(self, name: str):
        if name == "end-file":
            # During quality reload, ignore transient end-file to avoid false next-track.
            if time.monotonic() < self._quality_reload_until:
                logging.info("Quality reload in progress: ignoring end-file event.")
                return
            self._is_engine_busy = False
            self._pending_auto_next = True
            self._cached_paused = True
        elif name == "start-file":
            self._is_engine_busy = False
            self._pending_auto_next = False
            self._pending_show_background = False
            self._quality_reload_until = 0.0
            self._cached_paused = False
            # mpv may reset subtitle runtime props on new file load.
            QTimer.singleShot(0, self.apply_subtitle_settings)
            # Re-apply runtime video transforms that can be reset on file load.
            QTimer.singleShot(0, self._apply_video_mirror_filters)
