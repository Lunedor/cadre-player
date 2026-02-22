import os
from pathlib import Path

import math
import mpv

from PySide6.QtCore import QDateTime, QTimer, Qt, QEvent, QPoint
from PySide6.QtGui import QColor, QCursor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QSizeGrip,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QAction

from .settings import (
    load_muted,
    load_repeat,
    load_shuffle,
    load_volume,
    save_muted,
    save_repeat,
    save_shuffle,
    save_volume,
    load_always_on_top,
    save_always_on_top,
    load_sub_settings,
    save_sub_settings,
    load_video_settings,
    save_video_settings,
    load_aspect_ratio,
    save_aspect_ratio,
    load_resume_position,
    save_resume_position,
    save_language_setting,
    load_pinned_settings,
    save_pinned_settings,
)
from .ui.icons import (
    icon_close,
    icon_folder,
    icon_minus,
    icon_pause,
    icon_play,
    icon_playlist,
    icon_plus,
    icon_repeat,
    icon_sort,
    icon_maximize,
    icon_restore,
    icon_fullscreen,
    icon_exit_fullscreen,
    icon_shuffle,
    icon_save,
    icon_open_folder,


    icon_prev_track,
    icon_next_track,
    icon_stop,
    icon_trash,
    icon_volume,
    icon_volume_muted,
    get_app_icon,
)
from .ui.styles import PANEL_STYLE, PLAYLIST_STYLE, MENU_STYLE, TITLE_BAR_STYLE
from .ui.dialogs import SubtitleSettingsDialog, VideoSettingsDialog, URLInputDialog
from .i18n import tr
from .ui.widgets import (
    ClickableSlider,
    IconButton,
    OverlayWindow,
    PillOverlayWindow,
    PlaylistWidget,
    PlaylistItemWidget,
    RoundedPanel,
    TitleBarOverlay,
)


from .utils import (
    VIDEO_EXTENSIONS,
    SPEED_STEPS,
    REPEAT_OFF,
    REPEAT_ONE,
    REPEAT_ALL,
    format_duration,
    is_video_file,
    list_folder_videos,
    collect_paths,
    reveal_path,
    delete_to_trash as util_delete_to_trash,
)
from .playlist import DurationScanner
from .ui.menus import create_main_context_menu, create_playlist_context_menu
from .logic import PlayerLogic

class ProOverlayPlayer(QMainWindow, PlayerLogic):
    def __init__(self):
        QMainWindow.__init__(self)
        PlayerLogic.__init__(self)
        
        self.setWindowTitle("Cadre Player")
        self.setMinimumSize(900, 700)
        self.setAcceptDrops(True)
        self.setWindowIcon(get_app_icon())

        self.shuffle_enabled = load_shuffle()
        self.repeat_mode = load_repeat()
        self.playlist_durations = {} # path -> duration_str
        self.playlist_raw_durations = {} # path -> float (seconds)
        self.sort_include_folders = False
        self.scanners = []

        self._playlist_refresh_lock = False
        self._pending_auto_next = False
        self._playlist_last_hovered = 0

        self.saved_volume = load_volume()
        self.saved_muted = load_muted()

        self.central_widget = QWidget()
        self.central_widget.setMouseTracking(True)
        self.setCentralWidget(self.central_widget)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_main_context_menu)

        self.always_on_top = load_always_on_top()
        if self.always_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        v_config = load_video_settings()
        self.window_zoom = float(v_config.get("zoom", 0.0))

        pinned = load_pinned_settings()
        self.pinned_controls = pinned["controls"]
        self.pinned_playlist = pinned["playlist"]

        self._drag_pos = None
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)

        self.video_container = QWidget(self.central_widget)
        self.video_container.setAttribute(Qt.WA_NativeWindow)
        self.video_container.setStyleSheet("background-color: black;")
        
        
        self.player = mpv.MPV(
            wid=str(int(self.video_container.winId())),
            vo="gpu",
            hwdec=v_config.get("hwdec", "auto-safe"),
            hr_seek="yes",
            input_cursor="yes",
            input_vo_keyboard="yes",
            config=False,
        )
        self.player.pause = True # Ensure we start in "Ready" state, not "Playing" ghost state

        try:
            self.player.command("script-message", "osc-visibility", "never")
            self.player.command("set", "osc", "no")
            self.player.command("set", "osd-level", "0")
        except Exception:
            pass
        self.overlay = OverlayWindow(self)
        self.speed_overlay = PillOverlayWindow(self)
        self.playlist_overlay = OverlayWindow(self)
        self.title_bar = TitleBarOverlay(self)

        self.speed_indicator_timer = QTimer(self)
        self.speed_indicator_timer.setSingleShot(True)
        self.speed_indicator_timer.setInterval(900)
        self.speed_indicator_timer.timeout.connect(self.speed_overlay.hide)

        self.playlist_auto_hide_timer = QTimer(self)
        self.playlist_auto_hide_timer.setSingleShot(True)
        self.playlist_auto_hide_timer.setInterval(3000) # 3 second delay
        self.playlist_auto_hide_timer.timeout.connect(self.playlist_overlay.hide)

        try:
            self.player.register_event_callback(self._on_mpv_event)
            self.apply_subtitle_settings()
            self.apply_video_settings()
            self.set_aspect_ratio(load_aspect_ratio())
        except Exception:
            pass

        self.setup_ui()
        self.setup_playlist_ui()

        self.overlay.hide()
        self.speed_overlay.hide()
        self.playlist_overlay.hide()
        self.title_bar.hide()

        if self.pinned_controls or self.current_index < 0:
            self.overlay.show()
        if self.pinned_playlist:
            self.playlist_overlay.show()

        self._size_poll = QTimer(self)
        self._size_poll.setInterval(120)
        self._size_poll.timeout.connect(self._try_sync_size)

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


    def _save_zoom_setting(self):
        config = load_video_settings()
        config["zoom"] = self.window_zoom
        save_video_settings(config)

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

        self.mute_btn = IconButton(parent=self)
        self.mute_btn.clicked.connect(self.toggle_mute)

        self.seek_slider = ClickableSlider(Qt.Horizontal)
        self.seek_slider.setFocusPolicy(Qt.NoFocus)
        self.seek_slider.sliderMoved.connect(
            lambda value: self.player.command("seek", value, "absolute", "keyframes")
        )
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(88)
        self.time_label.setAlignment(Qt.AlignCenter)

        self.vol_slider = ClickableSlider(Qt.Horizontal)
        self.vol_slider.setFocusPolicy(Qt.NoFocus)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.saved_volume)
        self.vol_slider.setFixedWidth(70)
        self.vol_slider.valueChanged.connect(self.on_volume_changed)

        self.player.volume = self.saved_volume
        self.player.mute = self.saved_muted

        layout = QHBoxLayout(self.overlay.panel)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(6)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.next_btn)
        layout.addWidget(self.stop_btn)
        layout.addSpacing(10)
        layout.addWidget(self.seek_slider, 1)
        layout.addSpacing(10)
        layout.addWidget(self.time_label)
        layout.addWidget(self.mute_btn)
        layout.addWidget(self.vol_slider)
        layout.addSpacing(4)
        layout.addWidget(self.add_main_btn)
        layout.addWidget(self.fullscreen_btn)
        layout.addWidget(self.playlist_btn)

        self.update_transport_icons()
        self.update_mute_icon()

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
        self.playlist_widget.setDragDropMode(QListWidget.InternalMove)
        self.playlist_widget.setDefaultDropAction(Qt.MoveAction)
        self.playlist_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_widget.itemDoubleClicked.connect(self.play_selected_item)
        self.playlist_widget.customContextMenuRequested.connect(
            self.open_playlist_context_menu
        )
        self.playlist_widget.model().rowsMoved.connect(
            lambda *_: self.sync_playlist_from_widget()
        )
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
        # Group 1: Shuffle/Repeat
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        
        controls.addStretch(1)
        
        # Group 2: Add/Open/Save
        controls.addWidget(self.add_btn)
        controls.addWidget(self.open_playlist_btn)
        controls.addWidget(self.save_playlist_btn)
        
        controls.addStretch(1)
        
        # Group 3: Sort/Remove/Recycle
        controls.addWidget(self.sort_btn)
        controls.addWidget(self.remove_btn)
        controls.addWidget(self.delete_file_btn)
        
        layout.addLayout(controls)
        self.update_mode_buttons()

    def show_add_menu(self):
        # Show menu below the playlist add button
        self.add_menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def show_add_menu_main(self):
        # Show menu above the main transport add button
        pos = self.add_main_btn.mapToGlobal(self.add_main_btn.rect().topLeft())
        pos.setY(pos.y() - self.add_menu.sizeHint().height())
        self.add_menu.exec(pos)

    def apply_panel_shadow(self, panel: QWidget, blur: int, offset_y: int):
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, offset_y)
        shadow.setColor(QColor(0, 0, 0, 180))
        panel.setGraphicsEffect(shadow)

    def update_transport_icons(self):
        self.prev_btn.setIcon(icon_prev_track(22))
        self.next_btn.setIcon(icon_next_track(22))
        self.stop_btn.setIcon(icon_stop(22))
        self.play_btn.setIcon(icon_play(22) if self.player.pause else icon_pause(22))
        self.prev_btn.setText("")
        self.next_btn.setText("")
        self.stop_btn.setText("")
        self.play_btn.setText("")

    def update_mute_icon(self):
        pixmap = icon_volume_muted(22) if self.player.mute else icon_volume(22)
        self.mute_btn.setIcon(QIcon(pixmap))
        self.mute_btn.setText("")

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
        self.repeat_btn.setIcon(QIcon(icon_repeat(22, one=(self.repeat_mode == REPEAT_ONE), off=(self.repeat_mode == REPEAT_OFF))))

    def _sync_overlay_geometry(self):
        if not hasattr(self, "overlay"):
            return

        pad = 14
        height = 64
        inset = 8
        
        pill_w = min(900, self.width() - pad * 2 - inset * 2)
        overlay_w = pill_w + inset * 2

        geometry = self.geometry()
        # Always center relative to the full window width for visual stability
        x = geometry.x() + (self.width() - overlay_w) // 2
        y = geometry.y() + geometry.height() - height - pad

        self.overlay.setGeometry(x, y, overlay_w, height)
        self.overlay.panel.setGeometry(inset, 0, pill_w, height)

    def _sync_playlist_overlay_geometry(self):
        if not hasattr(self, "playlist_overlay"):
            return

        width = 400
        # Increase offset to 88px to clear the transport bar fully and leave a gap
        height = self.height() - 88
        geometry = self.geometry()

        # Always place inside on the right
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
        y = 18
        geometry = self.geometry()
        x = geometry.x() + inner_x
        global_y = geometry.y() + y
        self.speed_overlay.setGeometry(x, global_y, width, height)
        self.speed_overlay.panel.setGeometry(0, 0, width, height)
        self.speed_overlay.label.setGeometry(0, 0, width, height)

    def _sync_title_bar_geometry(self):
        if not hasattr(self, "title_bar") or self.isMinimized():
            return
        width = self.width()
        height = 32 # Match button height
        pos = self.mapToGlobal(QPoint(0, 0))
        self.title_bar.setGeometry(pos.x(), pos.y(), width, height)

    def check_mouse_pos(self):
        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)

        margin = 20  # Use 20 to perfectly match the 20x20 area in mousePressEvent!
        in_resize_area = (
            self.rect().contains(local_pos)
            and local_pos.x() >= self.width() - margin
            and local_pos.y() >= self.height() - margin
        )
        is_resizing = getattr(self, "_is_resizing", False)
        
        # Cursor auto-hide logic
        if in_resize_area or is_resizing:
            self.cursor_idle_time = 0
            if self.cursor().shape() != Qt.SizeFDiagCursor:
                self.setCursor(Qt.SizeFDiagCursor)
                self.video_container.setCursor(Qt.SizeFDiagCursor)
        else:
            if global_pos != self.last_cursor_global_pos:
                self.last_cursor_global_pos = global_pos
                self.cursor_idle_time = 0
                # FIX: If it's the BlankCursor OR the ResizeCursor, turn it back to Arrow
                if self.cursor().shape() != Qt.ArrowCursor:
                    self.setCursor(Qt.ArrowCursor)
                    self.video_container.setCursor(Qt.ArrowCursor)
            else:
                if self.rect().contains(local_pos):
                    self.cursor_idle_time += 100
                    if self.cursor_idle_time >= 2500:
                        if self.cursor().shape() != Qt.BlankCursor:
                            self.setCursor(Qt.BlankCursor)
                            self.video_container.setCursor(Qt.BlankCursor)
                else:
                    self.cursor_idle_time = 0

        # Overlay/Transport auto-show (bottom area)
        # ONLY show transport if playlist is hidden to avoid overlapping/blocking playlist buttons
        if self.pinned_controls:
            if not self.overlay.isVisible():
                self._sync_overlay_geometry()
                self.overlay.show()
        elif self.rect().contains(local_pos) and local_pos.y() > (self.height() - 90):
            if not self.overlay.isVisible():
                self._sync_overlay_geometry()
                self.overlay.show()
        elif self.overlay.isVisible():
            # If no video is playing, keep overlay visible
            if self.current_index < 0 or self.player.time_pos is None:
                pass
            # Hide transport if mouse leaves the area OR if playlist is toggled open
            elif local_pos.y() <= (self.height() - 90):
                self.overlay.hide()

        # Playlist auto-show (right edge)
        if self.pinned_playlist:
            if not self.playlist_overlay.isVisible():
                self._sync_playlist_overlay_geometry()
                self.playlist_overlay.show()
                self.playlist_overlay.raise_()
        elif self.rect().contains(local_pos) and local_pos.x() > (self.width() - 20):
            # Disable auto-show if title bar is visible to avoid clutter
            is_title_bar_visible = hasattr(self, "title_bar") and self.title_bar.isVisible()
            if not self.playlist_overlay.isVisible() and not is_title_bar_visible:
                self._sync_playlist_overlay_geometry()
                self.playlist_overlay.show()
                self.playlist_overlay.raise_()
                self.playlist_widget.updateGeometries()
                QTimer.singleShot(1, self.playlist_widget.update)

        # Playlist auto-hide with delay
        if self.playlist_overlay.isVisible() and not self.pinned_playlist:
            playlist_rect = self.playlist_overlay.geometry()
            # If mouse is inside or very close to the playlist, stop/reset the hide timer
            if global_pos.x() > (playlist_rect.x() - 40):
                self.playlist_auto_hide_timer.stop()
            elif not self.playlist_auto_hide_timer.isActive():
                # Start hiding after mouse stays outside for the interval
                self.playlist_auto_hide_timer.start()

        # Title/System Buttons auto-show (top area)
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

    def resizeEvent(self, event):
        self.video_container.setGeometry(0, 0, self.width(), self.height())
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_speed_indicator_geometry()
        self._sync_title_bar_geometry()            
        super().resizeEvent(event)

    def moveEvent(self, event):
        self._sync_overlay_geometry()
        self._sync_playlist_overlay_geometry()
        self._sync_speed_indicator_geometry()
        self._sync_title_bar_geometry()
        super().moveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self.update_fullscreen_icon()
            if hasattr(self, "title_bar"):
                if self.isMaximized():
                    self.title_bar.max_btn.setIcon(QIcon(icon_restore(18)))
                else:
                    self.title_bar.max_btn.setIcon(QIcon(icon_maximize(18)))
        super().changeEvent(event)

    def closeEvent(self, event):
        self.save_current_resume_info()
        
        # Stop timers
        if hasattr(self, "mouse_timer"): self.mouse_timer.stop()
        if hasattr(self, "ui_timer"): self.ui_timer.stop()
        if hasattr(self, "_size_poll"): self._size_poll.stop()
        
        # Crucial: Shutdown MPV player properly
        if hasattr(self, "player"):
            try:
                self.player.terminate()
            except:
                pass

        # Explicitly close and delete all overlay windows
        for attr in ["overlay", "speed_overlay", "playlist_overlay", "title_bar"]:
            if hasattr(self, attr):
                win = getattr(self, attr)
                win.close()
                win.deleteLater()
        
        super().closeEvent(event)
        QApplication.quit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        self.handle_dropped_paths(paths)
        # Note: We rely on the child widget (OverlayWindow) to accept the event if it forwarded it.
        # If it's a direct drop on the main window, we can accept it here.
        if event.isAccepted() == False:
            event.acceptProposedAction()

    def handle_dropped_paths(self, paths):
        if not paths:
            return

        # Always append. If 1 file, no expansion, play if idle.
        if len(paths) == 1 and paths[0].is_file() and self.is_video_file(paths[0]):
            added = [str(paths[0].resolve())]
        else:
            added = self.collect_paths(paths, recursive=True)

        if not added:
            return

        # Play if nothing currently playing (idle)
        is_idle = self.current_index < 0 or self.player.time_pos is None
        added = self.append_to_playlist(added, play_new=is_idle)
        self.show_status_overlay(tr("Added {}").format(len(added)))

    def is_video_file(self, path: Path) -> bool:
        return is_video_file(path)

    def list_folder_videos(self, folder: Path, recursive: bool = False):
        return list_folder_videos(folder, recursive=recursive)

    def collect_paths(self, paths, recursive: bool = False):
        return collect_paths(paths, recursive=recursive)

    def load_startup_paths(self, raw_paths):
        paths = [Path(p) for p in raw_paths if p]
        paths = [p for p in paths if p.exists()]
        if not paths:
            return

        if len(paths) == 1 and paths[0].is_file() and self.is_video_file(paths[0]):
            self.quick_open_file(paths[0])
            return

        loaded = self.collect_paths(paths, recursive=True)
        if not loaded:
            return
        self.playlist = loaded
        self.current_index = 0
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self.play_current()
        self.scan_durations(loaded)

    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("Select files to open"),
            "",
            tr("Video Files ({})").format(" ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS)) + ";;" + tr("All files (*.*)")
        )
        if files:
            added = self.append_to_playlist(files, play_new=False)
            self.show_status_overlay(tr("Added {}").format(len(added)))

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Select folder to open"))
        if folder:
            # Ask if recursive
            res = QMessageBox.question(
                self, tr("Include Subfolders"),
                tr("Do you want to include videos from subfolders as well?"),
                QMessageBox.Yes | QMessageBox.No
            )
            recursive = (res == QMessageBox.Yes)
            added = self.collect_paths([Path(folder)], recursive=recursive)
            if added:
                self.append_to_playlist(added, play_new=False)
                self.show_status_overlay(tr("Added {}").format(len(added)))

    def open_url_dialog(self):
        diag = URLInputDialog(self)
        if diag.exec():
            url = diag.get_url()
            if url:
                self.append_to_playlist([url], play_new=True)
                self.show_status_overlay(tr("Added URL"))

    def quick_open_file(self, file_path: Path):
        # Resolve to absolute normalized path
        selected = file_path.resolve()
        sel_str = os.path.normpath(str(selected))
        sel_lower = sel_str.lower()

        # Get all videos in same folder
        siblings = self.list_folder_videos(selected.parent)
        
        # Check if already in list (robust comparison)
        try:
            match_idx = next(
                i for i, s in enumerate(siblings) 
                if os.path.normpath(s).lower() == sel_lower
            )
        except StopIteration:
            siblings.insert(0, sel_str)
            match_idx = 0

        self.playlist = siblings
        self.current_index = match_idx
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self.play_current()
        self.scan_durations(siblings)

    def append_to_playlist(self, paths, play_new: bool = False):
        if not paths:
            return []
            
        # Filter out duplicates and preserve order
        unique_paths = []
        seen = set(self.playlist)
        for p in paths:
            # Convert Path objects to string for comparison with existing playlist
            p_str = str(p.resolve()) if isinstance(p, Path) else str(p)
            if p_str not in seen:
                unique_paths.append(p_str)
                seen.add(p_str)
        
        if not unique_paths:
            return []

        start_count = len(self.playlist)
        self.playlist.extend(unique_paths)
        if self.current_index < 0 and self.playlist:
            self.current_index = 0

        self.rebuild_shuffle_order(keep_current=True)
        
        # Batch add to view instead of full refresh if we already had items
        if start_count > 0:
            self._append_to_view(unique_paths, start_count + 1)
        else:
            self.refresh_playlist_view()

        if play_new and self.playlist:
            self.current_index = start_count
            self.play_current()
        elif self.player.time_pos is None and self.playlist:
            # Auto-play: player is idle and we just got new content — start from the first item
            if self.current_index < 0:
                self.current_index = 0
            self.play_current()

        # Start scanning for durations in the background
        self.scan_durations(unique_paths)
        return unique_paths

    def scan_durations(self, paths):
        if not paths:
            return
        scanner = DurationScanner(paths)
        scanner.finished_item.connect(self._on_duration_found)
        scanner.finished.connect(lambda: self.scanners.remove(scanner) if scanner in self.scanners else None)
        self.scanners.append(scanner)
        scanner.start()

    def _on_duration_found(self, path, dur_str, seconds):
        self.playlist_durations[path] = dur_str
        self.playlist_raw_durations[path] = seconds
        # Find all items with this path and update them

        for i in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(i)
            if item.data(Qt.UserRole) == path:
                widget = self.playlist_widget.itemWidget(item)
                if widget and hasattr(widget, "duration_label"):
                    widget.duration_label.setText(dur_str)

    def refresh_playlist_view(self):
        if not hasattr(self, "playlist_widget"):
            return

        self._playlist_refresh_lock = True
        self.playlist_widget.setUpdatesEnabled(False)
        self.playlist_widget.clear()
        
        self._append_to_view(self.playlist, 1)
        
        self.playlist_widget.setUpdatesEnabled(True)
        self._playlist_refresh_lock = False
        self.highlight_current_item()

    def _append_to_view(self, paths, start_idx):
        if not hasattr(self, "playlist_widget") or not paths:
            return
            
        is_refresh = (start_idx == 1)
        if not is_refresh:
            self.playlist_widget.setUpdatesEnabled(False)
            
        for i, path in enumerate(paths):
            idx = start_idx + i
            name = Path(path).name
            duration = self.playlist_durations.get(path, "--:--")
            
            item = QListWidgetItem()
            item.setData(Qt.UserRole, path)
            widget = PlaylistItemWidget(idx, name, duration)
            item.setSizeHint(widget.sizeHint())
            
            self.playlist_widget.addItem(item)
            self.playlist_widget.setItemWidget(item, widget)
            
            # Periodically process events to keep UI responsive for huge lists
            if (i + 1) % 50 == 0:
                QApplication.processEvents()
                
        if not is_refresh:
            self.playlist_widget.setUpdatesEnabled(True)

    def highlight_current_item(self):
        if not hasattr(self, "playlist_widget"):
            return
        if self.current_index < 0 or self.current_index >= self.playlist_widget.count():
            return
        self.playlist_widget.setCurrentRow(self.current_index)
        self.playlist_widget.scrollToItem(self.playlist_widget.item(self.current_index))

    def sync_playlist_from_widget(self):
        if self._playlist_refresh_lock:
            return
        
        # Don't sync if the widget is empty or being cleared
        if self.playlist_widget.count() == 0 and len(self.playlist) > 0:
            return

        current_path = (
            self.playlist[self.current_index]
            if 0 <= self.current_index < len(self.playlist)
            else None
        )
        reordered = []
        for row in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(row)
            reordered.append(item.data(Qt.UserRole))
        
        if not reordered and len(self.playlist) > 0:
            return # Safety check

        self.playlist = reordered
        if current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        else:
            self.current_index = -1
        self.rebuild_shuffle_order(keep_current=True)
        # We don't call refresh_playlist_view here because it would reset the widget state
        # while the user is interacting with it.
        # But we DO need to update the indices displayed in the items.
        for row in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(row)
            widget = self.playlist_widget.itemWidget(item)
            if widget and hasattr(widget, "index_label"):
                widget.index_label.setText(f"{row + 1:02d}")

    def show_sort_menu(self):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        
        # Name sorting
        az_act = QAction(tr("Name (A-Z)"), menu)
        az_act.triggered.connect(lambda: self.sort_playlist("name", False))
        
        za_act = QAction(tr("Name (Z-A)"), menu)
        za_act.triggered.connect(lambda: self.sort_playlist("name", True))
        
        # Duration sorting
        dur_asc_act = QAction(tr("Duration (Shortest first)"), menu)
        dur_asc_act.triggered.connect(lambda: self.sort_playlist("duration", False))
        
        dur_desc_act = QAction(tr("Duration (Longest first)"), menu)
        dur_desc_act.triggered.connect(lambda: self.sort_playlist("duration", True))
        
        # Folders toggle
        folder_act = QAction(tr("Include folder name in sort"), menu)
        folder_act.setCheckable(True)
        folder_act.setChecked(self.sort_include_folders)
        folder_act.triggered.connect(self.toggle_sort_include_folders)
        
        menu.addAction(az_act)
        menu.addAction(za_act)
        menu.addSeparator()
        menu.addAction(dur_asc_act)
        menu.addAction(dur_desc_act)
        menu.addSeparator()
        menu.addAction(folder_act)
        
        # Position menu at the button
        btn_pos = self.sort_btn.mapToGlobal(self.sort_btn.rect().bottomLeft())
        menu.exec(btn_pos)

    def toggle_sort_include_folders(self):
        self.sort_include_folders = not self.sort_include_folders
        status = tr("including") if self.sort_include_folders else tr("excluding")
        self.show_status_overlay(tr("Sort {} folders").format(status))
        self.refresh_playlist_view()

    def sort_playlist(self, criteria="name", reverse=False):
        if not self.playlist:
            return
            
        current_path = (
            self.playlist[self.current_index]
            if 0 <= self.current_index < len(self.playlist)
            else None
        )
        
        if criteria == "name":
            if self.sort_include_folders:
                # Full path (case insensitive)
                self.playlist.sort(key=lambda x: x.lower(), reverse=reverse)
            else:
                # Just filename (case insensitive)
                self.playlist.sort(key=lambda x: Path(x).name.lower(), reverse=reverse)
        
        elif criteria == "duration":
            # Duration (default to 0 if unknown)
            self.playlist.sort(key=lambda x: self.playlist_raw_durations.get(x, 0.0), reverse=reverse)
        
        if current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        
        self.rebuild_shuffle_order(keep_current=True)
        # The instruction snippet includes `if reverse: self.playlist.reverse()`,
        # but the `sort` method already handles `reverse=reverse`.
        # I will keep the `sort` method as is, as it's more idiomatic.

        key_name = tr("Path") if (criteria == "name" and self.sort_include_folders) else tr(criteria.capitalize())
        dir_name = tr("DESC") if reverse else tr("ASC")
        self.show_status_overlay(tr("Sorted: {} {}").format(key_name, dir_name))
        
        self.refresh_playlist_view()
        self.highlight_current_item()

    def save_playlist_m3u(self):
        if not self.playlist:
            return
            
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Save Playlist"), "", tr("M3U Playlist (*.m3u)")
        )
        if not path:
            return
            
        if not path.endswith(".m3u"):
            path += ".m3u"
            
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for item_path in self.playlist:
                    name = Path(item_path).name
                    # EXTM3U format: #EXTINF:duration,title
                    # We can use -1 if duration is unknown
                    raw_dur = self.playlist_raw_durations.get(item_path, -1)
                    dur_int = int(raw_dur) if raw_dur > 0 else -1
                    f.write(f"#EXTINF:{dur_int},{name}\n")
                    f.write(f"{item_path}\n")
            self.show_status_overlay(tr("Playlist Saved"))
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Could not save playlist: {}").format(e))

    def load_playlist_m3u(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Playlist"), "", tr("M3U Playlist (*.m3u);;All files (*.*)")
        )
        if not path:
            return
            
        try:
            new_paths = []
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Assume it's a file path
                    if os.path.exists(line):
                        new_paths.append(line)
                    else:
                        # Try relative to playlist file
                        rel_path = os.path.join(os.path.dirname(path), line)
                        if os.path.exists(rel_path):
                            new_paths.append(os.path.normpath(rel_path))

            if new_paths:
                # Replace or append? Usually load means replace or a new list. 
                # Let's ask via dialog or just append. 
                # Better to replace if we are "opening" a playlist.
                self.playlist = new_paths
                self.current_index = 0
                self.rebuild_shuffle_order(keep_current=True)
                self.refresh_playlist_view()
                self.play_current()
                self.scan_durations(new_paths)
                self.show_status_overlay(tr("Loaded {} items").format(len(new_paths)))
            else:
                self.show_status_overlay(tr("No valid files in playlist"))
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Could not load playlist: {}").format(e))



    def toggle_playlist_panel(self):
        if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible():
            self.playlist_overlay.hide()
            return
        self._sync_playlist_overlay_geometry()
        self.playlist_overlay.show()
        self.playlist_overlay.raise_()
        # Force layout update to ensure elision calculates with correct width immediately
        self.playlist_widget.updateGeometries()
        QTimer.singleShot(1, self.playlist_widget.update)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            # If playlist overlay/panel is visible, don't fullscreen-toggle
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible():
                return super().mouseDoubleClickEvent(event)

            # Only toggle if double-click is on the video area
            pos = event.position().toPoint()   # Qt6
            if self.video_container.geometry().contains(pos):
                self.toggle_fullscreen()
                event.accept()
                return

        super().mouseDoubleClickEvent(event)

    def show_status_overlay(self, text: str):
        self.speed_overlay.label.setText(text)
        self._sync_speed_indicator_geometry()
        self.speed_overlay.show()
        self.speed_overlay.raise_()
        self.speed_indicator_timer.start()

    def show_speed_indicator(self):
        speed = float(self.player.speed or 1.0)
        self.show_status_overlay(tr("{}x").format(speed))

    def change_speed_step(self, direction: int):
        current = float(self.player.speed or 1.0)
        closest = min(
            range(len(SPEED_STEPS)),
            key=lambda idx: abs(SPEED_STEPS[idx] - current),
        )
        target = max(0, min(len(SPEED_STEPS) - 1, closest + direction))
        self.player.speed = SPEED_STEPS[target]
        self.show_status_overlay(tr("{}x").format(self.player.speed))

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


    def force_ui_update(self):
        try:
            if self._pending_auto_next:
                self._pending_auto_next = False
                self._advance_after_end()
                return

            position = self.player.time_pos
            duration = self.player.duration

            # Update duration in playlist durations and widget
            if duration is not None and 0 <= self.current_index < len(self.playlist):
                if math.isfinite(duration):
                    path = self.playlist[self.current_index]
                    dur_str = format_duration(duration)
                    if self.playlist_durations.get(path) != dur_str:
                        self.playlist_durations[path] = dur_str
                        self.playlist_raw_durations[path] = duration
                        item = self.playlist_widget.item(self.current_index)
                        if item:
                            widget = self.playlist_widget.itemWidget(item)
                            if widget and hasattr(widget, "duration_label"):
                                widget.duration_label.setText(dur_str)

            # Check for end of file
            if not self.player.pause:
                is_at_end = False
                if bool(self.player.eof_reached):
                    is_at_end = True
                elif position is not None and duration is not None and duration > 0:
                    # Threshold check to advance slightly before absolute EOF if needed
                    if position >= max(0.0, duration - 0.15):
                        is_at_end = True
                
                if is_at_end:
                    self._advance_after_end()
                    return

            if position is None or duration is None:
                return

            if not math.isfinite(position) or not math.isfinite(duration):
                return

            if not self.seek_slider.isSliderDown():
                # Ensure range and value are within safe limits for QSlider (integers)
                safe_duration = max(0, int(duration))
                safe_position = max(0, min(safe_duration, int(position)))
                
                self.seek_slider.setRange(0, safe_duration)
                self.seek_slider.setValue(safe_position)

            current_str = format_duration(position)
            duration_str = format_duration(duration)
            self.time_label.setText(f"{current_str} / {duration_str}")
            
        except Exception:
            # Silently catch to keep the UI timer running
            pass

    def play_current(self):
        if not (0 <= self.current_index < len(self.playlist)):
            return

        current_file = self.playlist[self.current_index]
        self._pending_auto_next = False
        self.player.speed = 1.0
        self.player.command("loadfile", current_file, "replace")
        self.player.pause = False
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setRange(0, 0)
            self.seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.update_transport_icons()
        self.sync_shuffle_pos_to_current()
        self.highlight_current_item()

        title = f"[{self.current_index + 1}/{len(self.playlist)}] {Path(current_file).name}"
        self.setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.info_label.setText(title)


        # Resume logic
        resume_pos = load_resume_position(current_file)
        if resume_pos > 5: # Only resume if more than 5 seconds in
            # We need to wait a bit for file to load before seeking
            # Or use a property observer. Let's try a singleShot.
            QTimer.singleShot(100, lambda: self._safe_resume_seek(resume_pos))

        self._size_poll.start()
        QTimer.singleShot(120, self._try_sync_size)

    def _safe_resume_seek(self, pos):
        try:
            dur = self.player.duration
            if dur and pos < (dur - 10): # Don't resume if very close to end
                self.player.time_pos = pos
                self.show_status_overlay(tr("Resumed from {}").format(format_duration(pos)))
        except Exception:
            pass

    def _advance_after_end(self):
        self.next_video()

    def _try_sync_size(self):
        if self.isFullScreen():
            self._size_poll.stop()
            return

        width, height = self.player.dwidth, self.player.dheight
        if not width or not height:
            return

        self._size_poll.stop()
        self.sync_size()

    def sync_size(self):
        if self.isFullScreen():
            self.player.video_zoom = self.window_zoom
            return

        # Use video_params for intrinsic dimensions (actual source file specs)
        params = self.player.video_params
        if not params or not params.get('w'):
            # Fallback to display width/height if params not ready
            w, h = self.player.dwidth, self.player.dheight
            intrinsic_aspect = (w / h) if h else 1.77
            # Use 720p as a base for fallback height
            base_h = h if h else 720
        else:
            intrinsic_aspect = params.get('aspect') or (params.get('w') / params.get('h'))
            base_h = params.get('h')

        # 1. Calculate effective aspect ratio
        effective_aspect = intrinsic_aspect
        override = self.player.video_aspect_override
        if override and override != -1:
            if isinstance(override, str) and ":" in override:
                try:
                    num, den = map(float, override.split(":"))
                    effective_aspect = num / den
                except: pass
            elif isinstance(override, (int, float)) and override > 0:
                effective_aspect = float(override)

        # 2. Calculate zoom factor
        try:
            zoom_factor = 2 ** self.window_zoom
        except:
            zoom_factor = 1.0

        screen_rect = self.screen().availableGeometry()
        
        # 3. Calculate ideal size 
        clamped_base_h = min(base_h, screen_rect.height() * 0.7)
        ideal_h = clamped_base_h * zoom_factor
        ideal_w = ideal_h * effective_aspect
        
        target_h = ideal_h
        target_w = ideal_w
        
        # Absolute screen clamping (90%)
        limit_h = screen_rect.height() * 0.9
        if target_h > limit_h:
            target_h = limit_h
            target_w = target_h * effective_aspect
            
        # Width clamping (90%)
        limit_w = screen_rect.width() * 0.9
        if target_w > limit_w:
            target_w = limit_w
            target_h = target_w / effective_aspect

        # Ensure minimum window size
        if target_w < 400:
            target_w = 400
            target_h = target_w / effective_aspect
        if target_h < 300:
            target_h = 300
            target_w = target_h * effective_aspect

        # Resize the window
        self.resize(int(target_w), int(target_h))
        
        # 4. Overflow Zoom Factor (Handling PotPlayer Numpad limits)
        if target_h > 0:
            overflow_scale = ideal_h / target_h
            if abs(overflow_scale - 1.0) > 0.001:
                self.player.video_zoom = math.log2(overflow_scale)
            else:
                self.player.video_zoom = 0.0
                self.player.video_pan_x = 0.0
                self.player.video_pan_y = 0.0
        
        # Ensure it stays on screen
        new_geometry = self.geometry()
        if not screen_rect.contains(new_geometry):
            self.move(
                max(screen_rect.left(), min(new_geometry.left(), screen_rect.right() - new_geometry.width())),
                max(screen_rect.top(), min(new_geometry.top(), screen_rect.bottom() - new_geometry.height()))
            )

    def play_selected_item(self):
        row = self.playlist_widget.currentRow()
        if row < 0 or row >= len(self.playlist):
            return
        self.current_index = row
        self.play_current()

    def remove_playlist_indices(self, indices: list[int]):
        if not indices:
            return
            
        current_removed = self.current_index in indices
        current_path = (self.playlist[self.current_index] 
                        if 0 <= self.current_index < len(self.playlist) else None)
        
        # Remove in reverse order
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.playlist):
                self.playlist.pop(idx)
        
        if not self.playlist:
            self.current_index = -1
            self.player.stop()
            self.setWindowTitle("Cadre Player")
            if hasattr(self, "title_bar"):
                self.title_bar.info_label.setText("")
        elif current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        else:
            if self.current_index >= len(self.playlist):
                self.current_index = len(self.playlist) - 1
            if current_removed and self.current_index >= 0:
                self.play_current()
        
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()

    def remove_playlist_index(self, index: int):
        self.remove_playlist_indices([index])

    def remove_selected_from_playlist(self):
        selected = self.playlist_widget.selectedItems()
        if not selected:
            return
        indices = [self.playlist_widget.row(item) for item in selected]
        self.remove_playlist_indices(indices)

    def stop_playback(self):
        self.save_current_resume_info()
        self.player.command("stop")
        self.player.pause = True
        self.time_label.setText("00:00 / 00:00")
        self.seek_slider.setValue(0)
        self.seek_slider.setRange(0, 0)
        self.update_transport_icons()
        self.setWindowTitle("Cadre Player")
        if hasattr(self, "title_bar"):
            self.title_bar.info_label.setText("")


    def save_current_resume_info(self):
        if not self.playlist or self.current_index < 0:
            return
        try:
            pos = self.player.time_pos
            dur = self.player.duration
            path = self.playlist[self.current_index]
            if pos is not None and dur is not None:
                # If we are near the end, reset resume pos
                if pos > (dur - 15):
                    save_resume_position(path, 0)
                else:
                    save_resume_position(path, pos)
        except Exception:
            pass

    def delete_to_trash(self, indices=None):
        if not self.playlist:
            return
        if indices is None:
            indices = [self.playlist_widget.row(i) for i in self.playlist_widget.selectedItems()]
        if isinstance(indices, int):
            indices = [indices]
            
        indices = [i for i in indices if 0 <= i < len(self.playlist)]
        if not indices:
            return

        paths = [self.playlist[i] for i in indices]
        if len(paths) == 1:
            msg = tr("Recycle:\n{}?").format(Path(paths[0]).name)
        else:
            msg = tr("Recycle {} selected files?").format(len(paths))

        reply = QMessageBox.question(
            self, tr("Recycle Bin"), msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        deleted_indices = []
        for i, path in zip(indices, paths):
            if i == self.current_index:
                self.stop_playback()
            if util_delete_to_trash(path):
                deleted_indices.append(i)

        if deleted_indices:
            self.remove_playlist_indices(deleted_indices)
            self.show_status_overlay(tr("Deleted {} files").format(len(deleted_indices)))
        else:
            if len(paths) == 1:
                QMessageBox.warning(self, "Error", "Could not delete file.")

    def delete_selected_file_to_trash(self):
        self.delete_to_trash()

    def open_playlist_context_menu(self, pos):
        result = create_playlist_context_menu(self, pos)
        if not result:
            return
        menu, indices, path, play_act, rem_act, del_act, rev_act, copy_act = result
        
        action = menu.exec(self.playlist_widget.mapToGlobal(pos))
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
            menu.exec(self.mapToGlobal(pos))

    def add_subtitle_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self, tr("Add Subtitle"), "", tr("Subtitles (*.srt *.ass *.ssa *.sub *.vtt);;All files (*.*)")
        )
        if file:
            self.player.command("sub-add", file)

    def open_subtitle_settings(self):
        dialog = SubtitleSettingsDialog(self, self)
        dialog.exec()

    def open_video_settings(self):
        dialog = VideoSettingsDialog(self, self)
        dialog.exec()

    def apply_video_settings(self):
        config = load_video_settings()
        try:
            self.player.brightness = config.get("brightness", 0)
            self.player.contrast = config.get("contrast", 0)
            self.player.saturation = config.get("saturation", 0)
            self.player.gamma = config.get("gamma", 0)
            self.window_zoom = float(config.get("zoom", 0.0))
            self.player.video_rotate = config.get("rotate", 0)
            self.sync_size()
        except Exception as e:
            print(f"Error applying video settings: {e}")

    def set_aspect_ratio(self, ratio_str):
        # ratio_str can be "auto", "16:9", "4:3", etc.
        try:
            if ratio_str == "auto":
                # mpv internal: -1 resets the override
                self.player.video_aspect_override = -1
            else:
                # Can be a string like "16:9" or "4:3"
                self.player.video_aspect_override = ratio_str
            
            save_aspect_ratio(ratio_str)
            self.show_status_overlay(tr("Aspect: {}").format(ratio_str))
            # Give mpv a tiny moment to process then sync window size
            QTimer.singleShot(50, self.sync_size)
        except Exception as e:
            print(f"Error setting aspect ratio: {e}")

    def toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top
        save_always_on_top(self.always_on_top)
        
        # Safer way to toggle a single flag in modern Qt
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.always_on_top)
        
        # Re-showing is required when changing flags as it may recreate the window
        self.show()

    def change_language(self, lang_code: str):
        save_language_setting(lang_code)
        # We need to notify user that restart is required for full effect,
        # but we can also try to re-init i18n and force some updates.
        from .i18n import setup_i18n
        setup_i18n(lang_code)
        
        QMessageBox.information(
            self, 
            tr("Language Changed"), 
            tr("Language has been changed to {}. Some changes will take effect after restart.").format(lang_code.upper())
        )
        # Update what we can
        self.update_mode_buttons()
        self.update_transport_icons()
        self.update_mute_icon()

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

    def apply_subtitle_settings(self):
        config = load_sub_settings()
        try:
            self.player.sub_font_size = config.get("font_size", 34)
            self.player.sub_color = config.get("color", "#FFFFFFFF")
            self.player.sub_pos = config.get("pos", 95)
            self.player.sub_delay = config.get("delay", 0)
            
            style = config.get("back_style", "Shadow")
            
            # 1. Reset baseline (based on docs default: outline-and-shadow)
            self.player.sub_border_style = "outline-and-shadow"
            self.player.sub_border_size = 0
            self.player.sub_shadow_offset = 0
            self.player.sub_line_spacing = 0
            # Docs say alpha is #AARRGGBB, so #00000000 is fully transparent
            self.player.sub_back_color = "#00000000" 
            self.player.sub_border_color = "#00000000"
            
            if style == "None":
                pass # Already transparent from baseline reset
                
            elif style == "Outline":
                # Docs: The size of the outline is determined by --sub-outline-size
                self.player.sub_border_size = 3
                # Docs: The outline is colored by --sub-outline-color (--sub-border-color is alias)
                self.player.sub_border_color = "#FF000000" # Opaque black
                
            elif style == "Shadow":
                # Docs: The offset of the shadow is determined by --sub-shadow-offset.
                self.player.sub_border_size = 0 # No outline
                self.player.sub_shadow_offset = 3
                # Docs: ...and the shadow is colored by --sub-back-color (--sub-shadow-color is alias)
                self.player.sub_back_color = "#FF000000" # Opaque black shadow
                
            elif style == "Opaque Box":
                # Docs: opaque-box: draw outline and shadow as opaque boxes
                self.player.sub_border_style = "opaque-box"
                
                # Docs: The margin of the outline opaque box is determined by --sub-outline-size
                self.player.sub_border_size = 1 # Gives the box some padding
                self.player.sub_shadow_offset = 0
                
                # Docs: The outline opaque box is colored by --sub-outline-color (--sub-border-color)
                # We set the border color to 50% transparent black (#80000000)
                self.player.sub_border_color = "#80000000"
                self.player.sub_line_spacing = 4
                
        except Exception as e:
            print(f"Error applying subtitle settings: {e}")


    def prev_video(self):
        next_index = self.get_adjacent_index(forward=False)
        if next_index is None:
            return
        self.current_index = next_index
        self.play_current()
        self.show_status_overlay("Previous")

    def next_video(self):
        next_index = self.get_adjacent_index(forward=True)
        if next_index is None:
            return False
        self.current_index = next_index
        self.play_current()
        self.show_status_overlay("Next")
        return True

    def _on_mpv_event(self, event):
        try:
            # Flexible event parsing to handle multiple mpv/python-mpv versions
            name = None
            if hasattr(event, 'event_id') and hasattr(event.event_id, 'name'):
                name = event.event_id.name
            
            data = {}
            if hasattr(event, 'as_dict'):
                data = event.as_dict()
                if not name:
                    name = data.get('event')
            elif isinstance(event, dict):
                data = event
                if not name:
                    name = data.get('event')

            if isinstance(name, bytes):
                name = name.decode(errors='ignore')
            
            if name == "end-file":
                reason = data.get("reason")
                if isinstance(reason, bytes):
                    reason = reason.decode(errors="ignore")
                self._pending_auto_next = reason in (None, 0, "eof", "EOF")
            elif name == "start-file":
                self._pending_auto_next = False
        except Exception:
            pass

    def seek_relative(self, seconds: int):
        position = self.player.time_pos or 0
        new_pos = max(0, position + seconds)
        self.player.time_pos = new_pos
        dur = self.player.duration or 0
        self.show_status_overlay(tr("Seek: {} / {}").format(format_duration(new_pos), format_duration(dur)))

    def toggle_play(self):
        # If nothing is currently loaded in MPV but we have items in the playlist, start playing
        is_idle = self.player.time_pos is None
        if is_idle and self.playlist:
            if self.current_index < 0:
                self.current_index = 0
            self.play_current()
            return
            
        self.player.pause = not self.player.pause
        self.update_transport_icons()
        self.show_status_overlay(tr("Paused") if self.player.pause else tr("Playing"))

    def toggle_mute(self):
        self.player.mute = not self.player.mute
        save_muted(bool(self.player.mute))
        self.update_mute_icon()
        status = tr("Muted") if self.player.mute else tr("Unmuted")
        self.show_status_overlay(status)


    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.player.fullscreen = False
        else:
            self.showFullScreen()
            self.player.fullscreen = True
        self.update_fullscreen_icon()

    def screenshot_save_as(self):
        if not self.playlist or self.current_index < 0:
            return

        base = Path(self.playlist[self.current_index]).stem
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        default_name = f"{base}_{timestamp}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save screenshot"),
            str(Path.home() / "Pictures" / default_name),
            tr("PNG (*.png);;JPEG (*.jpg *.jpeg);;All files (*.*)"),
        )
        if not path:
            return

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.player.command("screenshot-to-file", str(target), "video")

    def wheelEvent(self, event):
        # Only change volume if not inside the playlist
        if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible() and self.playlist_overlay.geometry().contains(QCursor.pos()):
            super().wheelEvent(event)
            return
            
        delta = event.angleDelta().y()
        if delta > 0:
            self.vol_slider.setValue(self.vol_slider.value() + 5)
        elif delta < 0:
            self.vol_slider.setValue(self.vol_slider.value() - 5)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Check if click is in the bottom-right 20x20 pixel area
            if event.position().x() >= self.width() - 20 and event.position().y() >= self.height() - 20:
                self._is_resizing = True
                self.dragpos = event.globalPosition().toPoint()
                self._start_size = self.size()
                event.accept()
                return
                
            # RESTORED: Hide playlist if clicking outside of it
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible() and not getattr(self, "pinned_playlist", False):
                if not self.playlist_overlay.geometry().contains(event.position().toPoint()):
                    self.playlist_overlay.hide()
                    
            # Existing logic for moving the window from the top bar
            if event.position().y() <= 60:
                self.dragpos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
                
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragpos is not None:
            if hasattr(self, '_is_resizing') and self._is_resizing:
                # Handle resizing
                delta = event.globalPosition().toPoint() - self.dragpos
                new_width = max(self.minimumWidth(), self._start_size.width() + delta.x())
                new_height = max(self.minimumHeight(), self._start_size.height() + delta.y())
                self.resize(new_width, new_height)
            else:
                # Existing logic for moving
                self.move(event.globalPosition().toPoint() - self.dragpos)
                
            event.accept()
            return
            
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.dragpos = None
        self._is_resizing = False # Add this
        super().mouseReleaseEvent(event)


    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible() and not self.pinned_playlist:
                self.playlist_overlay.hide()
                return
            elif self.isFullScreen():
                self.toggle_fullscreen()
                return
        if key == Qt.Key_Right:
            self.seek_relative(5)
        elif key == Qt.Key_Left:
            self.seek_relative(-5)
        elif key == Qt.Key_Up:
            self.vol_slider.setValue(self.vol_slider.value() + 5)
        elif key == Qt.Key_Down:
            self.vol_slider.setValue(self.vol_slider.value() - 5)
        elif key == Qt.Key_PageUp:
            self.next_video()
        elif key == Qt.Key_PageDown:
            self.prev_video()
        elif key == Qt.Key_Space:
            self.toggle_play()
        elif key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_F):
            self.toggle_fullscreen()
        elif key == Qt.Key_Delete:
            self.delete_to_trash()
        elif key == Qt.Key_Period:
            self.player.command("frame-step")
        elif key == Qt.Key_Comma:
            self.player.command("frame-back-step")
        elif key == Qt.Key_BracketRight:
            self.change_speed_step(1)
        elif key == Qt.Key_BracketLeft:
            self.change_speed_step(-1)
        # New Navigation/Zoom Shortcuts
        elif key == Qt.Key_Plus or key == Qt.Key_Equal:
            self.window_zoom += 0.1
            self.show_status_overlay(tr("Zoom: {}").format(f"{self.window_zoom:.1f}"))
            self._save_zoom_setting()
            self.sync_size()
        elif key == Qt.Key_Minus:
            self.window_zoom = max(-2.0, self.window_zoom - 0.1)
            self.show_status_overlay(tr("Zoom: {}").format(f"{self.window_zoom:.1f}"))
            self._save_zoom_setting()
            self.sync_size()
        elif key == Qt.Key_0:
            self.window_zoom = 0.0
            self.show_status_overlay(tr("Zoom Reset"))
            self._save_zoom_setting()
            self.player.video_pan_x = 0.0
            self.player.video_pan_y = 0.0
            self.sync_size()
        elif key == Qt.Key_4:
            if (self.player.video_zoom or 0.0) > 0.0:
                self.player.video_pan_x = min(3.0, (self.player.video_pan_x or 0.0) + 0.05)
                self.show_status_overlay(tr("Pan Left"))
        elif key == Qt.Key_6:
            if (self.player.video_zoom or 0.0) > 0.0:
                self.player.video_pan_x = max(-3.0, (self.player.video_pan_x or 0.0) - 0.05)
                self.show_status_overlay(tr("Pan Right"))
        elif key == Qt.Key_8:
            if (self.player.video_zoom or 0.0) > 0.0:
                self.player.video_pan_y = min(3.0, (self.player.video_pan_y or 0.0) + 0.05)
                self.show_status_overlay(tr("Pan Up"))
        elif key == Qt.Key_2:
            if (self.player.video_zoom or 0.0) > 0.0:
                self.player.video_pan_y = max(-3.0, (self.player.video_pan_y or 0.0) - 0.05)
                self.show_status_overlay(tr("Pan Down"))
        elif key == Qt.Key_R and (event.modifiers() & Qt.ControlModifier):
            current = self.player.video_rotate or 0
            self.player.video_rotate = (current + 90) % 360
            self.show_status_overlay(tr("Rotate: {}°").format(self.player.video_rotate))
        elif key == Qt.Key_B: # Brightness shortcuts
            if event.modifiers() & Qt.ShiftModifier:
                self.player.brightness = max(-100, self.player.brightness - 5)
            else:
                self.player.brightness = min(100, self.player.brightness + 5)
            self.show_status_overlay(tr("Brightness: {}").format(self.player.brightness))
        elif key == Qt.Key_M:
            self.toggle_mute()
        elif key == Qt.Key_S:
            self.screenshot_save_as()
        elif key == Qt.Key_P:
            self.toggle_playlist_panel()
        elif key == Qt.Key_V:
            self.open_video_settings()
        elif key == Qt.Key_R:
            current = self.player.video_rotate or 0
            self.player.video_rotate = (current + 90) % 360
            self.show_status_overlay(tr("Rotate: {}°").format(self.player.video_rotate))
        elif key == Qt.Key_G: # Subtitle Delay decrease
            self.player.sub_delay -= 0.1
            self.show_status_overlay(tr("Delay: {}s").format(f"{self.player.sub_delay:.1f}"))
        elif key == Qt.Key_H: # Subtitle Delay increase
            self.player.sub_delay += 0.1
            self.show_status_overlay(tr("Delay: {}s").format(f"{self.player.sub_delay:.1f}"))
        elif key == Qt.Key_J: # Subtitle Size decrease
            self.player.sub_font_size = max(1, self.player.sub_font_size - 1)
            self.show_status_overlay(tr("Size: {}").format(self.player.sub_font_size))
        elif key == Qt.Key_K: # Subtitle Size increase
            self.player.sub_font_size = min(120, self.player.sub_font_size + 1)
            self.show_status_overlay(tr("Size: {}").format(self.player.sub_font_size))
        elif key == Qt.Key_U: # Subtitle Position decrease
            self.player.sub_pos = max(0, self.player.sub_pos - 1)
            self.show_status_overlay(tr("Pos: {}").format(self.player.sub_pos))
        elif key == Qt.Key_I: # Subtitle Position increase
            self.player.sub_pos = min(100, self.player.sub_pos + 1)
            self.show_status_overlay(tr("Pos: {}").format(self.player.sub_pos))
        else:
            super().keyPressEvent(event)
