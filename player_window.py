import os
import re
import base64
import logging
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
import time

import math
import mpv

from PySide6.QtCore import QDateTime, QTimer, Qt, QEvent, QPoint, QThread, Signal
from PySide6.QtGui import QColor, QCursor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    load_equalizer_settings,
    load_stream_auth_settings,
    load_stream_quality,
    save_stream_quality,
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
    icon_search,
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
    icon_settings,
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
    PlaylistFilterProxyModel,
    PlaylistItemDelegate,
    PlaylistListModel,
    PlaylistWidget,
    RoundedPanel,
    TitleBarOverlay,
)


from .utils import (
    VIDEO_EXTENSIONS,
    AUDIO_EXTENSIONS,
    SPEED_STEPS,
    REPEAT_OFF,
    REPEAT_ONE,
    REPEAT_ALL,
    format_duration,
    is_video_file,
    is_audio_file,
    list_folder_media,
    collect_paths,
    reveal_path,
    delete_to_trash as util_delete_to_trash,
)
from .playlist import DurationScanner
from .ui.menus import create_main_context_menu, create_playlist_context_menu
from .logic import PlayerLogic

try:
    import yt_dlp
except Exception:
    yt_dlp = None


def _is_stream_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _looks_like_m3u_url(url: str) -> bool:
    lower = url.split("?", 1)[0].split("#", 1)[0].lower()
    return lower.endswith(".m3u") or lower.endswith(".m3u8")


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(h in host for h in ("youtube.com", "youtu.be", "music.youtube.com"))


def _parse_m3u_text(text: str, base_url: str) -> list[str]:
    items = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" not in line:
            line = urljoin(base_url, line)
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            items.append(line)
    return items

def _auth_header(auth: Optional[dict]) -> Optional[str]:
    if not auth:
        return None
    if not auth.get("enabled"):
        return None
    username = str(auth.get("username") or "")
    password = str(auth.get("password") or "")
    if not username:
        return None
    token = f"{username}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


def _fetch_remote_m3u(url: str, auth: Optional[dict] = None) -> list[str]:
    headers = {
        "User-Agent": "CadrePlayer/1.0 (+https://github.com/)",
        "Accept": "application/x-mpegURL, audio/mpegurl, text/plain, */*",
    }
    auth_value = _auth_header(auth)
    if auth_value:
        headers["Authorization"] = auth_value
    req = Request(
        url,
        headers=headers,
    )
    with urlopen(req, timeout=6) as resp:
        body = resp.read()
    text = body.decode("utf-8-sig", errors="replace")
    return _parse_m3u_text(text, url)


def _looks_like_directory_stream_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path or "/"
    host = (parsed.netloc or "").lower()
    if path.endswith("/"):
        return True
    if "." not in Path(path).name:
        return True
    return "dav." in host or "webdav" in host


def _fetch_webdav_listing(url: str, auth: Optional[dict] = None) -> tuple[list[str], list[str]]:
    headers = {
        "User-Agent": "CadrePlayer/1.0 (+https://github.com/)",
        "Depth": "1",
        "Content-Type": "text/xml; charset=utf-8",
    }
    auth_value = _auth_header(auth)
    if auth_value:
        headers["Authorization"] = auth_value

    body = (
        b'<?xml version="1.0" encoding="utf-8" ?>'
        b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
    )
    req = Request(url, data=body, headers=headers, method="PROPFIND")
    with urlopen(req, timeout=4) as resp:
        raw = resp.read()
    xml_text = raw.decode("utf-8", errors="replace")
    root = ET.fromstring(xml_text)

    files = []
    dirs = []
    base_norm = url.rstrip("/") + "/"
    for resp in root.findall(".//{DAV:}response"):
        href_node = resp.find("{DAV:}href")
        if href_node is None or not href_node.text:
            continue
        href = unquote(href_node.text.strip())
        absolute = urljoin(url, href)
        norm = absolute.rstrip("/") + "/"
        if norm == base_norm:
            continue

        is_dir = resp.find(".//{DAV:}resourcetype/{DAV:}collection") is not None
        if is_dir:
            dirs.append(absolute.rstrip("/") + "/")
        else:
            files.append(absolute)
    return files, dirs


def _fetch_webdav_files_recursive(
    url: str,
    auth: Optional[dict] = None,
    max_depth: int = 2,
    max_items: int = 1200,
    max_requests: int = 8,
    max_seconds: int = 15,
) -> list[str]:
    files = []
    queue = [(url.rstrip("/") + "/", 0)]
    seen_dirs = set()
    requests_done = 0
    deadline = time.monotonic() + max_seconds

    while queue and len(files) < max_items:
        if requests_done >= max_requests:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("WebDAV listing timed out")
        current, depth = queue.pop(0)
        key = current.casefold()
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        try:
            level_files, level_dirs = _fetch_webdav_listing(current, auth=auth)
            requests_done += 1
        except Exception:
            continue

        for item in level_files:
            if len(files) >= max_items:
                break
            files.append(item)

        if depth < max_depth:
            for d in level_dirs:
                queue.append((d, depth + 1))
    return files


def _extract_youtube_entries(url: str) -> tuple[list[dict], str]:
    if yt_dlp is None:
        return ([{"url": url}], "yt-dlp not available")

    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "ignoreerrors": True,
        "playlist_items": "1-2000",
    }
    results = []
    seen = set()
    def _push_entry(item_url, title=None, duration=None):
        if not item_url:
            return
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", str(item_url)):
            item_url = f"https://www.youtube.com/watch?v={item_url}"
        key = str(item_url).casefold()
        if key in seen:
            return
        seen.add(key)
        payload = {"url": str(item_url)}
        if title:
            payload["title"] = str(title)
        if duration is not None:
            try:
                payload["duration"] = float(duration)
            except Exception:
                pass
        results.append(payload)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return ([{"url": url}], "no info")

    entries = info.get("entries") if isinstance(info, dict) else None
    if entries:
        for entry in entries:
            if not entry:
                continue
            item_url = entry.get("webpage_url") or entry.get("url")
            _push_entry(item_url, title=entry.get("title"), duration=entry.get("duration"))
        if results:
            return (results, "")

    # Fallback pass without extract_flat for edge cases
    try:
        opts2 = dict(opts)
        opts2["extract_flat"] = False
        with yt_dlp.YoutubeDL(opts2) as ydl:
            info2 = ydl.extract_info(url, download=False)
        entries2 = info2.get("entries") if isinstance(info2, dict) else None
        if entries2:
            for entry in entries2:
                if not entry:
                    continue
                item_url = entry.get("webpage_url") or entry.get("url")
                _push_entry(item_url, title=entry.get("title"), duration=entry.get("duration"))
            if results:
                return (results, "")
    except Exception:
        pass

    single = info.get("webpage_url") or info.get("url")
    if single:
        _push_entry(single, title=info.get("title"), duration=info.get("duration"))
        return (results or [{"url": str(single)}], "")
    return ([{"url": url}], "could not extract playlist entries")


class URLResolveWorker(QThread):
    finished_urls = Signal(list, dict, dict, str)
    progress_count = Signal(int)

    def __init__(self, raw_urls, auth=None):
        super().__init__()
        self.raw_urls = list(raw_urls)
        self.auth = auth or {}

    def run(self):
        all_items = []
        title_map = {}
        duration_map = {}
        seen = set()
        last_error = ""
        self.progress_count.emit(0)
        for raw in self.raw_urls:
            if self.isInterruptionRequested():
                break
            url = str(raw).strip()
            if not url:
                continue

            try:
                if _is_youtube_url(url):
                    entries, yt_error = _extract_youtube_entries(url)
                    if yt_error and not last_error:
                        last_error = yt_error
                    resolved = []
                    for e in entries:
                        item_url = e.get("url")
                        if not item_url:
                            continue
                        resolved.append(str(item_url))
                        if e.get("title"):
                            title_map[str(item_url)] = str(e["title"])
                        if e.get("duration") is not None:
                            try:
                                duration_map[str(item_url)] = float(e["duration"])
                            except Exception:
                                pass
                elif _looks_like_m3u_url(url):
                    resolved = _fetch_remote_m3u(url, auth=self.auth)
                    if not resolved:
                        resolved = [url]
                elif _looks_like_directory_stream_url(url):
                    resolved = _fetch_webdav_files_recursive(url, auth=self.auth)
                    if not resolved:
                        resolved = [url]
                else:
                    resolved = [url]
            except HTTPError as e:
                if e.code in (401, 403):
                    last_error = "authentication failed"
                else:
                    last_error = f"http {e.code}"
                resolved = []
            except TimeoutError:
                last_error = "timeout"
                resolved = [url]
            except (URLError, ValueError):
                last_error = "invalid or unreachable URL"
                resolved = [url]
            except Exception:
                last_error = "could not resolve URL"
                resolved = [url]

            for item in resolved:
                key = str(item).casefold()
                if key not in seen:
                    seen.add(key)
                    all_items.append(str(item))
                    if len(all_items) % 20 == 0:
                        self.progress_count.emit(len(all_items))

        self.progress_count.emit(len(all_items))
        self.finished_urls.emit(all_items, title_map, duration_map, last_error)


def _normalize_playlist_entry(value) -> tuple[str, str]:
    raw = str(value).strip()
    if _is_stream_url(raw):
        return raw, raw.casefold()
    abs_path = os.path.abspath(raw)
    key = os.path.normcase(os.path.normpath(abs_path))
    return abs_path, key


class PlaylistPrepareWorker(QThread):
    finished_paths = Signal(list)
    progress_count = Signal(int)

    def __init__(self, raw_paths, existing_keys, recursive=False, use_collect=False):
        super().__init__()
        self.raw_paths = list(raw_paths)
        self.existing_keys = set(existing_keys)
        self.recursive = recursive
        self.use_collect = use_collect

    def run(self):
        if self.use_collect:
            candidates = collect_paths(
                [Path(p) for p in self.raw_paths],
                recursive=self.recursive,
                progress_cb=self.progress_count.emit,
                progress_step=100,
            )
        else:
            candidates = [str(p) for p in self.raw_paths]

        unique_paths = []
        seen = set(self.existing_keys)
        last_emitted = 0
        for candidate in candidates:
            if self.isInterruptionRequested():
                break
            p_str, key = _normalize_playlist_entry(candidate)
            if key not in seen:
                unique_paths.append(p_str)
                seen.add(key)
            if len(unique_paths) - last_emitted >= 200:
                last_emitted = len(unique_paths)
                self.progress_count.emit(last_emitted)
        self.progress_count.emit(len(unique_paths))
        self.finished_paths.emit(unique_paths)


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
        self._track_switch_cooldown = 0.22
        self._manual_switch_delay_ms = 140
        self._switch_request_id = 0
        self._mpv_event_callback_enabled = False
        self._last_track_switch_time = 0.0
        self._next_duration_scan_attempt_at = 0.0
        self._last_position = 0.0
        self._last_duration = 0.0
        self._last_progress_time = 0.0
        self._last_seek_cmd_time = 0.0
        self._auto_next_deadline = 0.0
        self._user_paused = False
        self._pending_duration_paths = []
        self._pending_model_appends = []
        self._active_prepare_worker = None
        self._active_prepare_request = None
        self._prepare_queue = []
        self._active_url_worker = None
        self._active_url_request = None
        self._url_queue = []
        self._url_resolve_active = False
        self._url_status_timer = QTimer(self)
        self._url_status_timer.setInterval(450)
        self._url_status_timer.timeout.connect(self._refresh_url_resolve_status)
        self._stream_auth_by_host = {}
        self._stream_quality_cache = {}
        self._url_progress_count = 0

        self._append_chunk_timer = QTimer(self)
        self._append_chunk_timer.setInterval(0)
        self._append_chunk_timer.timeout.connect(self._drain_model_append_queue)
        self._import_status_timer = QTimer(self)
        self._import_status_timer.setInterval(350)
        self._import_status_timer.timeout.connect(self._refresh_import_status)
        self._import_progress_active = False
        self._import_progress_count = 0
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
        
        
        self.player = mpv.MPV(
            wid=str(int(self.video_container.winId())),
            vo=v_config.get("renderer", "gpu"),
            hwdec=v_config.get("hwdec", "auto-safe"),
            hr_seek="yes",
            input_cursor="yes",
            input_vo_keyboard="yes",
            config=False,
        )
        self.player.pause = True # Ensure we start in "Ready" state, not "Playing" ghost state
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
            self.set_aspect_ratio(load_aspect_ratio())
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
        if self.current_index < 0:
            self.title_bar.show()
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
        self._context_menu_open = False
        self._fullscreen_transition_active = False


    def _save_zoom_setting(self):
        config = load_video_settings()
        config["zoom"] = self.window_zoom
        save_video_settings(config)

    def _apply_mpv_startup_commands(self):
        try:
            self.player.command("script-message", "osc-visibility", "never")
            self.player.command("set", "osc", "no")
            self.player.command("set", "osd-level", "0")
        except Exception:
            pass

    def apply_stream_quality_setting(self):
        mapping = {
            "best": "bestvideo+bestaudio/best",
            "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480": "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "360": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        }
        fmt = mapping.get(self.stream_quality, mapping["best"])
        try:
            self.player.command("set", "ytdl-format", fmt)
        except Exception:
            pass

    def _quality_label(self, value: str) -> str:
        if value == "best":
            return tr("Auto (Best)")
        if value.isdigit():
            return f"{value}p"
        return value

    def _resolve_quality_options_for_url(self, url: str) -> list[str]:
        if not _is_stream_url(url):
            return []
        if not _is_youtube_url(url):
            return []
        if yt_dlp is None:
            return ["best"]

        key = url.casefold()
        if key in self._stream_quality_cache:
            return list(self._stream_quality_cache[key])

        options = ["best"]
        try:
            opts = {
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "extract_flat": False,
                "ignoreerrors": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats", []) if isinstance(info, dict) else []
            heights = set()
            for f in formats:
                if not isinstance(f, dict):
                    continue
                if f.get("vcodec") in (None, "none"):
                    continue
                h = f.get("height")
                if isinstance(h, int) and h > 0:
                    heights.add(h)
            for h in sorted(heights, reverse=True):
                options.append(str(h))
        except Exception:
            pass

        # Keep menu practical and stable
        dedup = []
        seen = set()
        for v in options:
            if v not in seen:
                seen.add(v)
                dedup.append(v)
        self._stream_quality_cache[key] = dedup
        return dedup

    def get_stream_quality_menu_options(self):
        if not (0 <= self.current_index < len(self.playlist)):
            return []
        current_item = str(self.playlist[self.current_index])
        values = self._resolve_quality_options_for_url(current_item)
        if not values:
            return []
        options = []
        for value in values:
            options.append((value, self._quality_label(value), value == self.stream_quality))
        return options

    def set_stream_quality(self, quality: str):
        self.stream_quality = str(quality or "best")
        save_stream_quality(self.stream_quality)
        self.apply_stream_quality_setting()
        shown = self._quality_label(self.stream_quality)
        reloaded = False
        if 0 <= self.current_index < len(self.playlist):
            current_item = str(self.playlist[self.current_index])
            if _is_stream_url(current_item):
                pos = float(self.player.time_pos or 0.0)
                try:
                    self.player.command("loadfile", current_item, "replace")
                    if pos > 1.0:
                        QTimer.singleShot(
                            200,
                            lambda p=pos: self.player.command("seek", p, "absolute", "keyframes"),
                        )
                    reloaded = True
                except Exception:
                    reloaded = False
        if reloaded:
            self.show_status_overlay(tr("Quality: {} (reloaded)").format(shown))
        else:
            self.show_status_overlay(tr("Quality: {}").format(shown))

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

        self.mute_btn = IconButton(parent=self)
        self.mute_btn.clicked.connect(self.toggle_mute)

        self.seek_slider = ClickableSlider(Qt.Horizontal)
        self.seek_slider.setFocusPolicy(Qt.NoFocus)
        self.seek_slider.sliderMoved.connect(self.seek_absolute)
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(120)
        self.time_label.setAlignment(Qt.AlignCenter)

        self.vol_slider = ClickableSlider(Qt.Horizontal)
        self.vol_slider.setFocusPolicy(Qt.NoFocus)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(self.saved_volume)
        self.vol_slider.setFixedWidth(70)
        self.vol_slider.valueChanged.connect(self.on_volume_changed)

        self.player.volume = self.saved_volume
        self.player.mute = self.saved_muted
        self._cached_muted = bool(self.saved_muted)

        layout = QHBoxLayout(self.overlay.panel)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(6)
        layout.addWidget(self.prev_btn)
        layout.addWidget(self.play_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.next_btn)
        layout.addSpacing(5)
        layout.addWidget(self.seek_slider, 1)
        layout.addSpacing(5)
        layout.addWidget(self.time_label)
        layout.addWidget(self.mute_btn)
        layout.addWidget(self.vol_slider)
        layout.addSpacing(4)
        layout.addWidget(self.settings_btn)
        layout.addWidget(self.add_main_btn)
        layout.addWidget(self.fullscreen_btn)
        layout.addWidget(self.playlist_btn)

        self.update_transport_icons()
        self.update_mute_icon()

    def show_settings_menu(self):
        from .ui.menus import create_main_context_menu
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
        if had_title_bar:
            self.title_bar.hide()
        try:
            menu.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            menu.setAttribute(Qt.WA_AlwaysStackOnTop, True)
            menu.raise_()
        except Exception:
            pass
        try:
            return menu.exec(global_pos)
        finally:
            self._context_menu_open = False
            if had_title_bar:
                QTimer.singleShot(0, self._restore_title_bar_after_menu)

    def _restore_title_bar_after_menu(self):
        if not hasattr(self, "title_bar"):
            return
        # Do not re-show the floating title bar over modal dialogs opened from menu actions.
        if QApplication.activeModalWidget() is not None:
            return
        if self._context_menu_open or self.isFullScreen() or not self._is_app_focused():
            return
        self._sync_title_bar_geometry()
        self.title_bar.show()
        self.title_bar.raise_()

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
        
        controls.addStretch(1)
        
        # Group 3: Sort/Remove/Recycle
        controls.addWidget(self.sort_btn)
        controls.addWidget(self.remove_btn)
        controls.addWidget(self.delete_file_btn)
        
        layout.addLayout(controls)
        self.update_mode_buttons()

    def show_add_menu(self):
        # Show menu below the playlist add button
        self._exec_menu_on_top(
            self.add_menu,
            self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()),
        )

    def show_add_menu_main(self):
        # Show menu above the main transport add button
        pos = self.add_main_btn.mapToGlobal(self.add_main_btn.rect().topLeft())
        pos.setY(pos.y() - self.add_menu.sizeHint().height())
        self._exec_menu_on_top(self.add_menu, pos)

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
        self.play_btn.setIcon(icon_play(22) if self._cached_paused else icon_pause(22))
        self.prev_btn.setText("")
        self.next_btn.setText("")
        self.stop_btn.setText("")
        self.play_btn.setText("")

    def update_mute_icon(self):
        pixmap = icon_volume_muted(22) if self._cached_muted else icon_volume(22)
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

    def _is_app_focused(self) -> bool:
        active_win = QApplication.activeWindow()
        if active_win is None:
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


    def check_mouse_pos(self):
        if not self._is_app_focused():
            if hasattr(self, "title_bar") and self.title_bar.isVisible():
                self.title_bar.hide()
            return
        if getattr(self, "_fullscreen_transition_active", False):
            return

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
            if self.current_index < 0 or self._cached_paused:
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

    def resizeEvent(self, event):
        self.video_container.setGeometry(0, 0, self.width(), self.height())
        self.background_widget.setGeometry(0, 0, self.width(), self.height())
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
        if event.type() == QEvent.ActivationChange:
            if not self._is_app_focused() and hasattr(self, "title_bar"):
                self.title_bar.hide()

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
        if hasattr(self, "_append_chunk_timer"): self._append_chunk_timer.stop()
        if hasattr(self, "_import_status_timer"): self._import_status_timer.stop()
        if hasattr(self, "_url_status_timer"): self._url_status_timer.stop()
        self._stop_import_progress()
        self._stop_url_resolve_status()

        if self._active_url_worker is not None:
            self._active_url_worker.requestInterruption()
            self._active_url_worker.wait(1500)
            self._active_url_worker = None
            self._active_url_request = None
            self._url_queue.clear()

        if self._active_prepare_worker is not None:
            self._active_prepare_worker.requestInterruption()
            self._active_prepare_worker.wait(1500)
            self._active_prepare_worker = None
            self._active_prepare_request = None
            self._prepare_queue.clear()
        if self.scanners:
            for scanner in list(self.scanners):
                try:
                    scanner.requestInterruption()
                    scanner.wait(300)
                except Exception:
                    pass
            self.scanners.clear()
            self._pending_duration_paths.clear()
        
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

        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)

        super().closeEvent(event)
        QApplication.quit()

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
        except Exception:
            return False
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
                return super().eventFilter(obj, event)

            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit):
                return super().eventFilter(obj, event)
            if self._is_playlist_search_focused() or self._is_playlist_widget_focused():
                return super().eventFilter(obj, event)

            self.keyPressEvent(event)
            return True
        return super().eventFilter(obj, event)

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

        subtitle_exts = {'.srt', '.ass', '.ssa', '.sub', '.vtt'}
        media_files = []
        subtitle_files = []
        folders = []
        for p in paths:
            if p.is_file():
                ext = p.suffix.lower()
                if ext in subtitle_exts:
                    subtitle_files.append(str(p.resolve()))
                elif self.is_video_file(p) or self.is_audio_file(p):
                    media_files.append(str(p.resolve()))
            elif p.is_dir():
                folders.append(p)

        # If only subtitle(s) dropped and a media file is open, add subtitle(s)
        if subtitle_files and not media_files and not folders:
            if self.player.time_pos is not None:
                for sub in subtitle_files:
                    self.player.command("sub-add", sub)
                self.show_status_overlay(tr("Subtitle(s) added"))
            else:
                self.show_status_overlay(tr("Open a video before adding subtitles"))
            return

        # If media file(s) dropped, handle as before
        if media_files or folders:
            raw_inputs = [Path(f) for f in media_files] + folders
            recursive = True
            if folders:
                recursive = self._ask_recursive_import()
            # Play if nothing currently playing (idle)
            is_idle = self._player_is_idle()
            self.append_to_playlist_async(
                raw_inputs,
                play_new=is_idle,
                recursive=recursive,
                use_collect=True,
                on_done=lambda new_items: self.show_status_overlay(tr("Added {}".format(len(new_items)))),
            )

    def _ask_recursive_import(self) -> bool:
        res = QMessageBox.question(
            self,
            tr("Include Subfolders"),
            tr("Do you want to include media from subfolders as well?"),
            QMessageBox.Yes | QMessageBox.No,
        )
        return res == QMessageBox.Yes


    def is_video_file(self, path: Path) -> bool:
        return is_video_file(path)

    def is_audio_file(self, path: Path) -> bool:
        return is_audio_file(path)


    # list_folder_videos is obsolete; use list_folder_media instead

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
        logging.info(
            "Playlist remove: removed=%d now=%d current_index=%d",
            len(indices),
            len(self.playlist),
            self.current_index,
        )
        self.play_current()
        self.scan_durations(loaded)

    def add_files_dialog(self):
        filter_str = (
            tr("Media Files ({})").format(
                " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS + AUDIO_EXTENSIONS)
            )
            + ";;"
            + tr("Video Files ({})").format(" ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS))
            + ";;"
            + tr("Audio Files ({})").format(" ".join(f"*{ext}" for ext in AUDIO_EXTENSIONS))
            + ";;"
            + tr("All files (*.*)")
        )
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("Select files to open"),
            "",
            filter_str
        )
        if files:
            self.append_to_playlist_async(
                files,
                play_new=False,
                on_done=lambda new_items: self.show_status_overlay(tr("Added {}".format(len(new_items)))),
            )

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Select folder to open"))
        if folder:
            recursive = self._ask_recursive_import()
            self.append_to_playlist_async(
                [folder],
                play_new=False,
                recursive=recursive,
                use_collect=True,
                on_done=lambda new_items: self.show_status_overlay(tr("Added {}".format(len(new_items)))),
            )

    def open_url_dialog(self):
        diag = URLInputDialog(self)
        if diag.exec():
            url = diag.get_url()
            if url:
                auth = diag.get_auth()
                is_idle = self._player_is_idle()
                self.import_stream_sources_async([url], play_new=is_idle, auth=auth)

    def import_stream_sources_async(self, urls, play_new: bool = False, auth=None):
        cleaned = [str(u).strip() for u in urls if str(u).strip()]
        if not cleaned:
            return
        if auth is None:
            auth = load_stream_auth_settings()
        self._url_queue.append({"urls": cleaned, "play_new": play_new, "auth": auth})
        self._start_next_url_worker()

    def _start_next_url_worker(self):
        if self._active_url_worker is not None:
            return
        if not self._url_queue:
            return
        self._active_url_request = self._url_queue.pop(0)
        req = self._active_url_request
        self._url_progress_count = 0
        self._start_url_resolve_status()
        worker = URLResolveWorker(req["urls"], auth=req.get("auth"))
        worker.progress_count.connect(self._on_url_worker_progress)
        worker.finished_urls.connect(self._on_url_worker_finished)
        worker.finished.connect(lambda: worker.deleteLater())
        self._active_url_worker = worker
        worker.start()

    def _start_url_resolve_status(self):
        self._url_resolve_active = True
        self._refresh_url_resolve_status()
        if not self._url_status_timer.isActive():
            self._url_status_timer.start()

    def _refresh_url_resolve_status(self):
        if self._url_resolve_active:
            self.show_status_overlay(
                tr("Resolving stream URLs... {}").format(self._url_progress_count)
            )

    def _on_url_worker_progress(self, count):
        self._url_progress_count = max(0, int(count))

    def _stop_url_resolve_status(self):
        self._url_resolve_active = False
        if self._url_status_timer.isActive():
            self._url_status_timer.stop()

    def _register_stream_auth_rules(self, urls, auth):
        if not auth or not auth.get("enabled"):
            return
        auth_value = _auth_header(auth)
        if not auth_value:
            return
        for item in urls:
            parsed = urlparse(str(item))
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                host = parsed.netloc.split("@")[-1].lower()
                self._stream_auth_by_host[host] = auth_value

    def _on_url_worker_finished(self, resolved_urls, title_map, duration_map, error_msg):
        req = self._active_url_request or {}
        self._active_url_worker = None
        self._active_url_request = None
        self._stop_url_resolve_status()
        if not resolved_urls:
            if error_msg:
                self.show_status_overlay(tr("Stream import failed: {}").format(error_msg))
            else:
                self.show_status_overlay(tr("No stream URLs found"))
            self._start_next_url_worker()
            return

        play_new = bool(req.get("play_new", False))
        for path, title in (title_map or {}).items():
            self.playlist_titles[path] = title
        for path, seconds in (duration_map or {}).items():
            try:
                sec = float(seconds)
                self.playlist_raw_durations[path] = sec
                self.playlist_durations[path] = format_duration(sec)
            except Exception:
                pass
        self._register_stream_auth_rules(resolved_urls, req.get("auth"))
        self.append_to_playlist_async(
            resolved_urls,
            play_new=play_new,
            title_map=title_map,
            duration_map=duration_map,
            on_done=lambda new_items: self.show_status_overlay(
                tr("Imported {} stream items").format(len(new_items))
            )
            if new_items
            else self.show_status_overlay(
                tr("No new items imported")
                if not error_msg
                else tr("Stream import failed: {}").format(error_msg)
            ),
        )
        self._start_next_url_worker()

    def quick_open_file(self, file_path: Path):
        # Resolve to absolute normalized path
        selected = file_path.resolve()
        sel_str = os.path.normpath(str(selected))
        sel_lower = sel_str.lower()

        # Get all media (video/audio) in same folder
        siblings = list_folder_media(selected.parent)
        
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

        existing_keys = {_normalize_playlist_entry(existing)[1] for existing in self.playlist}
        unique_paths = []
        seen = set(existing_keys)
        for p in paths:
            p_str, key = _normalize_playlist_entry(p)
            if key not in seen:
                unique_paths.append(p_str)
                seen.add(key)

        return self._apply_prepared_playlist_paths(unique_paths, play_new=play_new)

    def append_to_playlist_async(
        self,
        paths,
        play_new: bool = False,
        on_done=None,
        recursive: bool = False,
        use_collect: bool = False,
        title_map: dict = None,
        duration_map: dict = None,
    ):
        if not paths:
            if callable(on_done):
                on_done([])
            return

        self._prepare_queue.append(
            {
                "paths": list(paths),
                "play_new": play_new,
                "on_done": on_done,
                "recursive": recursive,
                "use_collect": use_collect,
                "title_map": dict(title_map or {}),
                "duration_map": dict(duration_map or {}),
            }
        )
        self._start_next_prepare_worker()

    def _start_next_prepare_worker(self):
        if self._active_prepare_worker is not None:
            return
        if not self._prepare_queue:
            return

        self._active_prepare_request = self._prepare_queue.pop(0)
        req = self._active_prepare_request
        existing_keys = {_normalize_playlist_entry(existing)[1] for existing in self.playlist}
        for path, title in req.get("title_map", {}).items():
            self.playlist_titles[path] = title
        for path, seconds in req.get("duration_map", {}).items():
            try:
                sec = float(seconds)
                self.playlist_raw_durations[path] = sec
                self.playlist_durations[path] = format_duration(sec)
            except Exception:
                pass
        worker = PlaylistPrepareWorker(
            req["paths"],
            existing_keys,
            recursive=req["recursive"],
            use_collect=req["use_collect"],
        )
        self._start_import_progress(0)
        worker.progress_count.connect(self._on_prepare_worker_progress)
        worker.finished_paths.connect(self._on_prepare_worker_finished)
        worker.finished.connect(lambda: worker.deleteLater())
        self._active_prepare_worker = worker
        worker.start()

    def _on_prepare_worker_progress(self, count):
        self._import_progress_count = max(self._import_progress_count, max(0, int(count)))

    def _on_prepare_worker_finished(self, unique_paths):
        req = self._active_prepare_request or {}
        self._active_prepare_worker = None
        self._active_prepare_request = None
        self._import_progress_count = len(unique_paths)

        added = self._apply_prepared_playlist_paths(unique_paths, play_new=req.get("play_new", False))
        callback = req.get("on_done")
        if callable(callback):
            callback(added)

        self._start_next_prepare_worker()
        if self._active_prepare_worker is None and not self._prepare_queue and not self._pending_model_appends:
            self._stop_import_progress()

    def _start_import_progress(self, initial_count=0):
        self._import_progress_active = True
        self._import_progress_count = max(0, int(initial_count))
        self._refresh_import_status()
        if not self._import_status_timer.isActive():
            self._import_status_timer.start()

    def _refresh_import_status(self):
        if not self._import_progress_active:
            return
        self.show_status_overlay(tr("Adding files... {}").format(self._import_progress_count))

    def _stop_import_progress(self):
        self._import_progress_active = False
        self._import_progress_count = 0
        if self._import_status_timer.isActive():
            self._import_status_timer.stop()

    def _player_is_idle(self) -> bool:
        if self.current_index < 0 or not self.playlist:
            return True
        try:
            filename = self.player.filename
            if filename:
                return False
            return (
                self.player.time_pos is None
                and self.player.duration is None
                and bool(self._cached_paused)
            )
        except Exception:
            return False

    def _can_switch_track_now(self, manual: bool = True) -> bool:
        if not manual:
            return True
        now = time.monotonic()
        if now < self._next_track_switch_allowed_at:
            return False
        self._next_track_switch_allowed_at = now + self._track_switch_cooldown
        return True

    def _schedule_play_current(self, delay_ms: int = 0):
        self._switch_request_id += 1
        req_id = self._switch_request_id
        target_index = self.current_index

        def _run():
            if req_id != self._switch_request_id:
                return
            if target_index != self.current_index:
                return
            self.play_current()

        if delay_ms <= 0:
            _run()
        else:
            QTimer.singleShot(int(delay_ms), _run)

    def _apply_prepared_playlist_paths(self, unique_paths, play_new: bool = False):
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
        elif start_count == 0 and self._player_is_idle() and self.playlist:
            # Auto-play: player is idle and we just got new content — start from the first item
            if self.current_index < 0:
                self.current_index = 0
            self.play_current()

        logging.info(
            "Playlist add: added=%d start_count=%d now=%d current_index=%d play_new=%s",
            len(unique_paths),
            start_count,
            len(self.playlist),
            self.current_index,
            play_new,
        )
        # Start scanning for durations in the background
        self.scan_durations(unique_paths)
        return unique_paths

    def scan_durations(self, paths=None):
        if paths:
            local_paths = [p for p in paths if not _is_stream_url(str(p))]
            existing = set(str(p) for p in self._pending_duration_paths)
            cap = 5000
            for p in local_paths:
                if len(self._pending_duration_paths) >= cap:
                    break
                p_str = str(p)
                if p_str not in existing:
                    self._pending_duration_paths.append(p_str)
                    existing.add(p_str)
        # Stability-first: run ffprobe scanning only while paused/idle.
        if not self._cached_paused and self.current_index >= 0:
            return
        if self.scanners:
            return
        if len(self.playlist) > 1000 and not self._cached_paused:
            batch_size = 1
        elif len(self.playlist) > 1000:
            batch_size = 25
        elif len(self.playlist) > 800 and not self._cached_paused:
            batch_size = 3
        else:
            batch_size = 80
        batch = list(self._pending_duration_paths[:batch_size])
        self._pending_duration_paths = self._pending_duration_paths[len(batch):]
        if not batch:
            return
        scanner = DurationScanner(batch)
        scanner.finished_item.connect(self._on_duration_found)
        scanner.finished.connect(lambda s=scanner: self._on_duration_scanner_finished(s))
        self.scanners.append(scanner)
        scanner.start()

    def _on_duration_scanner_finished(self, scanner):
        if scanner in self.scanners:
            self.scanners.remove(scanner)
        if self._cached_paused:
            self.scan_durations(None)
        else:
            self._next_duration_scan_attempt_at = max(
                self._next_duration_scan_attempt_at,
                time.monotonic() + 1.2,
            )

    def _on_duration_found(self, path, dur_str, seconds):
        self.playlist_durations[path] = dur_str
        self.playlist_raw_durations[path] = seconds
        if hasattr(self, "playlist_model"):
            self.playlist_model.update_duration(path, dur_str)

    def refresh_playlist_view(self):
        if not hasattr(self, "playlist_widget"):
            return

        self._playlist_refresh_lock = True
        self.playlist_model.set_paths([], self.playlist_durations, self.playlist_titles)
        self._append_to_view(self.playlist, 1, apply_filter=False)
        self._playlist_refresh_lock = False
        self.apply_playlist_filter()
        self.highlight_current_item()

    def _append_to_view(self, paths, start_idx, apply_filter: bool = True):
        if not hasattr(self, "playlist_widget") or not paths:
            return
        self._pending_model_appends.extend(paths)
        if apply_filter:
            self._append_chunk_timer.setProperty("apply_filter_on_complete", True)
        if not self._append_chunk_timer.isActive():
            self._append_chunk_timer.start()

    def _drain_model_append_queue(self):
        if not self._pending_model_appends:
            self._append_chunk_timer.stop()
            if self._append_chunk_timer.property("apply_filter_on_complete"):
                self._append_chunk_timer.setProperty("apply_filter_on_complete", False)
                self.apply_playlist_filter()
            else:
                self.highlight_current_item()
            if self._active_prepare_worker is None and not self._prepare_queue:
                self._stop_import_progress()
            return

        chunk_size = 250
        chunk = self._pending_model_appends[:chunk_size]
        del self._pending_model_appends[:chunk_size]
        self.playlist_model.append_paths(chunk, self.playlist_durations, self.playlist_titles)

    def toggle_playlist_search(self):
        if not hasattr(self, "playlist_search_input"):
            return

        if self.playlist_search_input.isVisible():
            if self._search_debounce_timer.isActive():
                self._search_debounce_timer.stop()
            self.playlist_search_input.clear()
            self.playlist_search_input.setVisible(False)
            self.search_btn.setChecked(False)
            self.search_btn.setToolTip(tr("Search playlist"))
            self.apply_playlist_filter()
            return

        self.playlist_search_input.setVisible(True)
        self.search_btn.setChecked(True)
        self.search_btn.setToolTip(tr("Hide search"))
        self.playlist_search_input.setFocus()
        self.playlist_search_input.selectAll()

    def schedule_playlist_filter(self):
        # Filter from the first character; only debounce to keep typing smooth.
        self._search_debounce_timer.start()

    def apply_playlist_filter(self):
        if not hasattr(self, "playlist_widget"):
            return

        term = ""
        if hasattr(self, "playlist_search_input"):
            term = self.playlist_search_input.text().strip().casefold()

        self.playlist_filter_model.set_query(term)

        can_reorder = not bool(term)
        self.playlist_widget.setDragEnabled(can_reorder)
        self.playlist_widget.setDragDropMode(
            QAbstractItemView.InternalMove if can_reorder else QAbstractItemView.NoDragDrop
        )
        self.highlight_current_item()

    def highlight_current_item(self):
        if not hasattr(self, "playlist_widget"):
            return
        try:
            self.playlist_widget.setProperty("current_playlist_index", self.current_index)
            self.playlist_widget.viewport().update()
            if self.current_index < 0 or self.current_index >= len(self.playlist):
                return
            source_idx = self.playlist_model.index(self.current_index, 0)
            if not source_idx.isValid():
                return
            proxy_idx = self.playlist_filter_model.mapFromSource(source_idx)
            if not proxy_idx.isValid():
                return
            # Keep selection logic independent; only ensure visibility.
            self.playlist_widget.scrollTo(proxy_idx, QAbstractItemView.PositionAtCenter)
        except Exception:
            logging.exception("highlight_current_item failed")

    def sync_playlist_from_widget(self):
        if self._playlist_refresh_lock:
            return

        current_path = (
            self.playlist[self.current_index]
            if 0 <= self.current_index < len(self.playlist)
            else None
        )
        reordered = self.playlist_model.paths()
        if not reordered and len(self.playlist) > 0:
            return

        self.playlist = reordered
        if current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        else:
            self.current_index = -1
        self.rebuild_shuffle_order(keep_current=True)
        self.highlight_current_item()

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
        self._exec_menu_on_top(menu, btn_pos)

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
            if self._pending_show_background:
                self._pending_show_background = False
                self.background_widget.show()

            if self._pending_auto_next:
                self._pending_auto_next = False
                self._advance_after_end()
                return

            now = time.monotonic()
            if now < self._suspend_ui_poll_until:
                return
            if (
                self._pending_duration_paths
                and not self.scanners
                and now >= self._next_duration_scan_attempt_at
            ):
                self._next_duration_scan_attempt_at = now + 1.2
                self.scan_durations(None)
            if now < self._next_ui_poll_at:
                return
            self._next_ui_poll_at = now + (0.45 if self._cached_paused else 0.25)

            position = self.player.time_pos
            duration = self.player.duration
            if position is not None and math.isfinite(position):
                if position > (self._last_position + 0.02):
                    self._last_progress_time = now
                self._last_position = float(position)
            if duration is not None and math.isfinite(duration) and duration > 0:
                self._last_duration = float(duration)

            # Update duration in playlist durations and widget
            if duration is not None and 0 <= self.current_index < len(self.playlist):
                if math.isfinite(duration):
                    path = self.playlist[self.current_index]
                    dur_str = format_duration(duration)
                    if self.playlist_durations.get(path) != dur_str:
                        self.playlist_durations[path] = dur_str
                        self.playlist_raw_durations[path] = duration
                        if hasattr(self, "playlist_model"):
                            self.playlist_model.update_duration(path, dur_str)

            # Check for end of file
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
            ):
                if self._auto_next_deadline <= 0:
                    self._auto_next_deadline = now + 0.4
                elif now >= self._auto_next_deadline:
                    is_at_end = True
            else:
                self._auto_next_deadline = 0.0

            # Watchdog fallback: if playback had progressed, then player goes idle/black
            # without user pause, treat it as ended and advance.
            if (
                not is_at_end
                and not self._user_paused
                and self.current_index >= 0
                and self._last_progress_time > 0
                and (position is None or duration is None)
                and (now - self._last_progress_time) > 0.8
                and (now - self._last_track_switch_time) > 1.0
            ):
                is_at_end = True
            # Secondary watchdog: if progress reached near end and then stops advancing.
            if (
                not is_at_end
                and not self._user_paused
                and self.current_index >= 0
                and self._last_duration > 0
                and self._last_position >= (self._last_duration - 0.6)
                and (now - self._last_progress_time) > 1.2
            ):
                is_at_end = True
            if is_at_end:
                advanced = self._advance_after_end()
                if not advanced:
                    self._cached_paused = True
                    self._pending_show_background = True
                    self.update_transport_icons()
                self._auto_next_deadline = 0.0
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
        try:
            parsed = urlparse(str(current_file))
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                host = parsed.netloc.split("@")[-1].lower()
                auth_value = self._stream_auth_by_host.get(host)
                if auth_value:
                    self.player.http_header_fields = f"Authorization: {auth_value}"
                else:
                    self.player.http_header_fields = ""
            else:
                self.player.http_header_fields = ""
        except Exception:
            pass
        self._pending_auto_next = False
        self._pending_show_background = False
        self._last_track_switch_time = time.monotonic()
        self._auto_next_deadline = 0.0
        self._user_paused = False
        self._last_position = 0.0
        self._last_duration = 0.0
        self._last_progress_time = 0.0
        self.player.speed = 1.0
        self._suspend_ui_poll_until = time.monotonic() + 0.45
        self._next_ui_poll_at = self._suspend_ui_poll_until
        self.player.command("loadfile", current_file, "replace")
        self.background_widget.hide()
        self.player.pause = False
        self._cached_paused = False
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setRange(0, 0)
            self.seek_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.update_transport_icons()
        self.sync_shuffle_pos_to_current()
        QTimer.singleShot(0, self.highlight_current_item)

        display_name = self.playlist_titles.get(str(current_file))
        if not display_name:
            try:
                parsed = urlparse(str(current_file))
                if parsed.scheme and parsed.netloc:
                    display_name = unquote(Path(parsed.path.rstrip("/")).name) or parsed.netloc
                else:
                    display_name = Path(str(current_file)).name
            except Exception:
                display_name = str(current_file)
        title = f"[{self.current_index + 1}/{len(self.playlist)}] {display_name}"
        self.setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.info_label.setText(title)


        # Resume logic
        resume_pos = load_resume_position(current_file)
        if resume_pos > 5: # Only resume if more than 5 seconds in
            # We need to wait a bit for file to load before seeking
            # Or use a property observer. Let's try a singleShot.
            QTimer.singleShot(100, lambda: self._safe_resume_seek(resume_pos))

        # Avoid frequent mpv property reads here; explicit sync_size calls remain available.
        self._size_poll.stop()

    def _safe_resume_seek(self, pos):
        try:
            dur = self.player.duration
            if dur and pos < (dur - 10): # Don't resume if very close to end
                self.player.time_pos = pos
                self.show_status_overlay(tr("Resumed from {}").format(format_duration(pos)))
        except Exception:
            pass

    def _advance_after_end(self):
        return self.next_video(manual=False)

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

    def _proxy_index_to_playlist_row(self, proxy_index):
        if not proxy_index or not proxy_index.isValid():
            return -1
        source_idx = self.playlist_filter_model.mapToSource(proxy_index)
        if not source_idx.isValid():
            return -1
        row = source_idx.row()
        if row < 0 or row >= len(self.playlist):
            return -1
        return row

    def get_selected_playlist_indices(self):
        if not hasattr(self, "playlist_widget"):
            return []
        selection_model = self.playlist_widget.selectionModel()
        if not selection_model:
            return []
        selected_rows = []
        for idx in selection_model.selectedRows():
            row = self._proxy_index_to_playlist_row(idx)
            if row >= 0:
                selected_rows.append(row)
        return sorted(set(selected_rows))

    def play_selected_item(self, _index=None):
        if not self._can_switch_track_now(manual=True):
            return
        proxy_index = _index if (_index is not None and _index.isValid()) else self.playlist_widget.currentIndex()
        row = self._proxy_index_to_playlist_row(proxy_index)
        if row < 0:
            return
        self.save_current_resume_info()
        self._user_paused = False
        self.current_index = row
        self._schedule_play_current(self._manual_switch_delay_ms)

    def remove_playlist_indices(self, indices: list[int]):
        if not indices:
            return
            
        current_removed = self.current_index in indices
        current_path = (self.playlist[self.current_index] 
                        if 0 <= self.current_index < len(self.playlist) else None)
        
        # Remove in reverse order
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.playlist):
                removed_path = self.playlist.pop(idx)
                self.playlist_titles.pop(removed_path, None)
        
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
        indices = self.get_selected_playlist_indices()
        self.remove_playlist_indices(indices)

    def stop_playback(self):
        self.save_current_resume_info()
        self.player.command("stop")
        self.background_widget.show()
        self.player.pause = True
        self._cached_paused = True
        self._user_paused = True
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
            indices = self.get_selected_playlist_indices()
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

    def open_equalizer_dialog(self):
        from .ui.dialogs import EqualizerDialog
        dialog = EqualizerDialog(self, self)
        dialog.exec()

    def apply_equalizer_settings(self):
        data = load_equalizer_settings()
        try:
            if data["enabled"]:
                freqs = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
                gains = data["gains"]
                
                # Build a simple, clean filter string
                af_str = ",".join(
                    f"equalizer=f={f}:width_type=o:w=1:g={g}"
                    for f, g in zip(freqs, gains)
                )
                self.player.command("set", "af", af_str)
            else:
                self.player.command("set", "af", "")
        except Exception as e:
            print("Apply EQ Error:", e)

    def update_equalizer_gains(self, gains):
        # We drop af-command completely! 
        # Whenever a slider moves, just do exactly what the checkbox does:
        self.apply_equalizer_settings()



    def open_about_dialog(self):
        from .ui.dialogs import AboutDialog
        dialog = AboutDialog(self)
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
            renderer = config.get("renderer", "gpu")
            try:
                self.player.command("set", "vo", renderer)
            except Exception:
                pass
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


    def prev_video(self, manual: bool = True):
        if not self._can_switch_track_now(manual=manual):
            return
        next_index = self.get_adjacent_index(forward=False)
        if next_index is None:
            return
        self.save_current_resume_info()
        self._user_paused = False
        self.current_index = next_index
        self._schedule_play_current(self._manual_switch_delay_ms if manual else 0)
        self.show_status_overlay("Previous")
        logging.info("Prev video: current_index=%d playlist=%d", self.current_index, len(self.playlist))

    def next_video(self, manual: bool = True):
        if not self._can_switch_track_now(manual=manual):
            return False
        next_index = self.get_adjacent_index(forward=True)
        if next_index is None:
            return False
        self.save_current_resume_info()
        self._user_paused = False
        self.current_index = next_index
        self._schedule_play_current(self._manual_switch_delay_ms if manual else 0)
        self.show_status_overlay("Next")
        logging.info("Next video: current_index=%d playlist=%d", self.current_index, len(self.playlist))
        return True

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

            if name == "end-file":
                self._pending_auto_next = True
                self._cached_paused = True
            elif name == "start-file":
                self._pending_auto_next = False
                self._pending_show_background = False
                self._cached_paused = False
        except Exception:
            pass

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
            # Ignore transient seek failures while mpv is switching/loading.
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
            # Avoid flooding overlay updates during key-repeat seeks.
            if (now - self._last_track_switch_time) > 0.2:
                self.show_status_overlay(tr("Seek {}s").format(seconds))
        except Exception:
            return

    def toggle_play(self):
        # If nothing is currently loaded in MPV but we have items in the playlist, start playing
        is_idle = self._player_is_idle()
        if is_idle and self.playlist:
            if self.current_index < 0:
                self.current_index = 0
            self.play_current()
            return
            
        new_paused = not self._cached_paused
        self.player.pause = new_paused
        self._cached_paused = new_paused
        self._user_paused = new_paused
        if new_paused:
            self.scan_durations(None)
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


    def toggle_fullscreen(self):
        if self._fullscreen_transition_active:
            return
        self._fullscreen_transition_active = True

        if hasattr(self, "title_bar"):
            self.title_bar.hide()
        if hasattr(self, "overlay"):
            self.overlay.hide()
        if hasattr(self, "playlist_overlay") and not self.pinned_playlist:
            self.playlist_overlay.hide()

        target_fullscreen = not self.isFullScreen()
        # Reduce one-frame geometry flicker during state transition.
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


    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible() and not self.pinned_playlist:
                self.playlist_overlay.hide()
                return
            elif self.isFullScreen():
                self.toggle_fullscreen()
                return
        if self._is_playlist_search_focused():
            super().keyPressEvent(event)
            return
        if self._is_playlist_widget_focused():
            if key in (Qt.Key_Enter, Qt.Key_Return):
                self.play_selected_item()
                return
            if key == Qt.Key_Delete:
                if event.modifiers() & Qt.ShiftModifier:
                    self.delete_to_trash()
                else:
                    self.remove_selected_from_playlist()
                return
            super().keyPressEvent(event)
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
            self.prev_video()
        elif key == Qt.Key_PageDown:
            self.next_video()
        elif key == Qt.Key_Space:
            self.toggle_play()
        elif key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_F):
            self.toggle_fullscreen()
        elif key == Qt.Key_Delete:
            if event.modifiers() & Qt.ShiftModifier:
                self.delete_to_trash()
            else:
                self.remove_selected_from_playlist()
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
