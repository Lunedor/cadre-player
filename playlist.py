import os
import subprocess
import logging
import time
import base64
import re
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QMenu, QMessageBox

from .i18n import tr
from .settings import load_stream_auth_settings, save_resume_position
from .ui.styles import MENU_STYLE
from .utils import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    collect_paths,
    delete_to_trash as util_delete_to_trash,
    format_duration,
    get_user_data_path,
    is_media_file,
    is_audio_file,
    list_folder_media,
    is_video_file,
    is_stream_url as _is_stream_url,
)

try:
    import yt_dlp
except Exception:
    yt_dlp = None

YTDLP_REMOTE_COMPONENTS = "ejs:github"


def _build_ytdlp_opts(extra: Optional[dict] = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "remote_components": YTDLP_REMOTE_COMPONENTS,
    }
    if extra:
        opts.update(extra)
    return opts


def normalize_playlist_entry(value) -> tuple[str, str]:
    raw = str(value).strip()
    if _is_stream_url(raw):
        return raw, raw.casefold()
    abs_path = os.path.abspath(raw)
    key = os.path.normcase(os.path.normpath(abs_path))
    return abs_path, key


def parse_local_m3u_with_meta(path: str) -> tuple[list[str], dict[str, str], dict[str, float]]:
    items = []
    seen = set()
    title_map: dict[str, str] = {}
    duration_map: dict[str, float] = {}
    pending_title = ""
    pending_duration: float | None = None
    playlist_path = os.path.abspath(str(path))
    base_dir = os.path.dirname(playlist_path)
    with open(playlist_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF:"):
                payload = line[len("#EXTINF:") :].strip()
                dur_part, sep, title_part = payload.partition(",")
                pending_title = title_part.strip() if sep else ""
                pending_duration = None
                try:
                    dur_value = float(dur_part.strip())
                    if dur_value >= 0:
                        pending_duration = dur_value
                except Exception:
                    pending_duration = None
                continue
            if line.startswith("#"):
                continue
            if _is_stream_url(line):
                entry = line
            else:
                file_url = QUrl(line)
                if file_url.isValid() and file_url.isLocalFile():
                    line = file_url.toLocalFile()
                expanded = os.path.expandvars(os.path.expanduser(line))
                candidate = (
                    expanded if os.path.isabs(expanded) else os.path.join(base_dir, expanded)
                )
                candidate = os.path.abspath(os.path.normpath(candidate))
                if not os.path.exists(candidate):
                    continue
                entry = candidate
            _, key = normalize_playlist_entry(entry)
            if key not in seen:
                seen.add(key)
                items.append(entry)
                if pending_title:
                    if not (_is_youtube_url(entry) and _is_placeholder_title(pending_title)):
                        title_map[entry] = pending_title
                if pending_duration is not None:
                    duration_map[entry] = float(pending_duration)
            pending_title = ""
            pending_duration = None
    return items, title_map, duration_map


def parse_local_m3u(path: str) -> list[str]:
    items, _, _ = parse_local_m3u_with_meta(path)
    return items


def _looks_like_m3u_url(url: str) -> bool:
    lower = str(url or "").split("?", 1)[0].split("#", 1)[0].lower()
    return lower.endswith(".m3u") or lower.endswith(".m3u8")


def _looks_like_m3u_path(path: str) -> bool:
    lower = str(path or "").strip().lower()
    return lower.endswith(".m3u") or lower.endswith(".m3u8")


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(h in host for h in ("youtube.com", "youtu.be", "music.youtube.com"))


def _youtube_truncated_id_hint(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            yid = parsed.path.strip("/").split("/", 1)[0]
            if yid and len(yid) != 11:
                return "incomplete YouTube ID"
        query_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        if query_id and len(query_id) != 11:
            return "incomplete YouTube ID"
    except Exception:
        pass
    return ""


def _normalize_youtube_item_url(item_url: str) -> str:
    raw = str(item_url or "").strip()
    if not raw:
        return ""
    if _is_youtube_url(raw):
        parsed = urlparse(raw)
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            vid = parsed.path.strip("/").split("/", 1)[0]
        else:
            vid = parse_qs(parsed.query).get("v", [""])[0].strip()
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    return raw


def _youtube_direct_video_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            vid = parsed.path.strip("/").split("/", 1)[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        q = parse_qs(parsed.query)
        vid = q.get("v", [""])[0].strip()
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    return ""


def _youtube_video_id(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            return parsed.path.strip("/").split("/", 1)[0].strip()
        return parse_qs(parsed.query).get("v", [""])[0].strip()
    except Exception:
        return ""


def _is_placeholder_title(title: str) -> bool:
    token = str(title or "").strip().casefold()
    if not token:
        return True
    return token in {"watch", "youtube", "youtube?", "video", "untitled", "unknown"}


def _fallback_stream_title(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if _is_youtube_url(raw):
        vid = _youtube_video_id(raw)
        return f"YouTube {vid}" if vid else "YouTube"
    try:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            name = Path(unquote(parsed.path.rstrip("/"))).name
            return name or parsed.netloc
    except Exception:
        pass
    return raw


def _short_youtube_error_message(err: str) -> str:
    text = str(err or "").strip()
    if not text:
        return "could not access YouTube video"
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"^ERROR:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    lower = text.casefold()
    if "members" in lower and "only" in lower:
        return "members-only YouTube video"
    if "private video" in lower:
        return "private YouTube video"
    if "video unavailable" in lower:
        return "YouTube video unavailable"
    if "sign in to confirm your age" in lower or "age-restricted" in lower:
        return "age-restricted YouTube video"
    if "not available in your country" in lower or "geo" in lower:
        return "geo-restricted YouTube video"
    return text[:140]


def _extract_youtube_single_metadata(url: str) -> tuple[str, float | None, str]:
    if yt_dlp is None:
        return "", None, "yt-dlp not installed"
    title = ""
    duration = None
    error = ""
    try:
        opts = _build_ytdlp_opts(
            {
                "noplaylist": True,
                "extract_flat": False,
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if isinstance(info, dict):
            title = str(info.get("title") or "").strip()
            try:
                raw_duration = info.get("duration")
                if raw_duration is not None:
                    duration = float(raw_duration)
            except Exception:
                duration = None
    except Exception as e:
        logging.info("YouTube single metadata fetch failed: url=%s err=%s", url, e)
        error = _short_youtube_error_message(e)
    return title, duration, error


def _youtube_looks_like_playlist_url(url: str) -> bool:
    try:
        if not _is_youtube_url(url):
            return False
        parsed = urlparse(str(url or "").strip())
        q = parse_qs(parsed.query)
        path = (parsed.path or "").lower()
        return (
            bool(q.get("list"))
            or "playlist" in path
            or "/channel/" in path
            or "/@" in path
            or "/c/" in path
            or "/user/" in path
        )
    except Exception:
        return False


def _sanitize_http_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return raw
    try:
        parts = urlsplit(raw)
        if parts.scheme not in {"http", "https"}:
            return raw
        path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="=&%:@!$'()*+,;/?-._~")
        fragment = quote(parts.fragment, safe="=&%:@!$'()*+,;/?-._~")
        return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))
    except Exception:
        return raw


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
    safe_url = _sanitize_http_url(url)
    headers = {
        "User-Agent": "CadrePlayer/1.0 (+https://github.com/)",
        "Accept": "application/x-mpegURL, audio/mpegurl, text/plain, */*",
    }
    auth_value = _auth_header(auth)
    if auth_value:
        headers["Authorization"] = auth_value
    req = Request(safe_url, headers=headers)
    with urlopen(req, timeout=6) as resp:
        body = resp.read()
    text = body.decode("utf-8-sig", errors="replace")
    items = _parse_m3u_text(text, safe_url)
    if items:
        return items
    probe = text.lstrip().lower()
    if probe.startswith("<?xml") or "<html" in probe[:300]:
        raise ValueError("URL did not return an M3U playlist")
    raise ValueError("Remote playlist is empty or invalid")


def _looks_like_directory_stream_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        path = parsed.path or "/"
        if path.endswith("/"):
            return True
        ext = Path(unquote(path)).suffix.lower()
        if ext in {".m3u", ".m3u8"}:
            return False
        return not ext
    except Exception:
        return False


def _fetch_webdav_listing(url: str, auth: Optional[dict] = None) -> tuple[list[str], list[str]]:
    safe_url = _sanitize_http_url(url)
    if not safe_url.endswith("/"):
        safe_url += "/"
    headers = {
        "Depth": "1",
        "User-Agent": "CadrePlayer/1.0 (+https://github.com/)",
    }
    auth_value = _auth_header(auth)
    if auth_value:
        headers["Authorization"] = auth_value
    req = Request(
        safe_url,
        method="PROPFIND",
        data=(
            b'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:">'
            b"<d:prop><d:resourcetype/><d:getcontenttype/></d:prop></d:propfind>"
        ),
        headers=headers,
    )
    with urlopen(req, timeout=8) as resp:
        body = resp.read()
    root = ET.fromstring(body)
    ns = {"d": "DAV:"}
    files, dirs = [], []
    base_path = urlparse(safe_url).path.rstrip("/")
    for response in root.findall(".//d:response", ns):
        href = response.findtext("d:href", default="", namespaces=ns)
        if not href:
            continue
        full = urljoin(safe_url, href)
        full = _sanitize_http_url(full)
        parsed = urlparse(full)
        rel_path = parsed.path
        if rel_path.rstrip("/") == base_path.rstrip("/"):
            continue
        is_collection = response.find(".//d:collection", ns) is not None
        if is_collection:
            if not full.endswith("/"):
                full += "/"
            dirs.append(full)
            continue
        ext = Path(unquote(parsed.path)).suffix.lower()
        if ext in VIDEO_EXTENSIONS or ext in AUDIO_EXTENSIONS:
            files.append(full)
    seen = set()
    files_unique = []
    for item in files:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            files_unique.append(item)
    seen_dirs = set()
    dirs_unique = []
    for item in dirs:
        key = item.casefold()
        if key not in seen_dirs:
            seen_dirs.add(key)
            dirs_unique.append(item)
    return files_unique, dirs_unique


def _fetch_webdav_files_recursive(
    root_url: str,
    auth: Optional[dict] = None,
    *,
    max_dirs: int = 400,
    max_files: int = 20000,
) -> list[str]:
    start = _sanitize_http_url(root_url)
    if not start.endswith("/"):
        start += "/"
    pending = [start]
    seen_dirs = {start.casefold()}
    all_files = []
    while pending:
        current = pending.pop(0)
        try:
            level_files, level_dirs = _fetch_webdav_listing(current, auth=auth)
        except HTTPError:
            raise
        except Exception:
            continue
        for f in level_files:
            all_files.append(f)
            if len(all_files) >= max_files:
                return all_files
        for d in level_dirs:
            key = d.casefold()
            if key in seen_dirs:
                continue
            if len(seen_dirs) >= max_dirs:
                continue
            seen_dirs.add(key)
            pending.append(d)
    return all_files


def _extract_youtube_entries(url: str) -> tuple[list[dict], str]:
    if yt_dlp is None:
        return ([], "yt-dlp not installed")
    results = []

    def _push_entry(item_url, title=None, duration=None):
        if not item_url:
            return
        norm_url = _normalize_youtube_item_url(item_url)
        if not norm_url:
            return
        entry = {"url": norm_url}
        if title:
            entry["title"] = str(title)
        if duration is not None:
            try:
                entry["duration"] = float(duration)
            except Exception:
                pass
        results.append(entry)

    try:
        opts = _build_ytdlp_opts(
            {
                "extract_flat": "in_playlist",
                "noplaylist": False,
                "playlistend": 10000,
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logging.exception("YouTube extract failed: url=%s err=%s", url, e)
        return ([], f"{e}")

    if not isinstance(info, dict):
        return ([], "invalid yt-dlp response")

    entries = info.get("entries")
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            item_url = item.get("url") or item.get("webpage_url")
            _push_entry(item_url, title=item.get("title"), duration=item.get("duration"))
        if results:
            logging.info("YouTube extract success: url=%s items=%d", url, len(results))
            return (results, "")

    try:
        opts = _build_ytdlp_opts(
            {
                "extract_flat": False,
                "noplaylist": False,
                "playlistend": 10000,
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info2 = ydl.extract_info(url, download=False)
        entries2 = info2.get("entries") if isinstance(info2, dict) else None
        if isinstance(entries2, list):
            for item in entries2:
                if not isinstance(item, dict):
                    continue
                item_url = item.get("url") or item.get("webpage_url")
                _push_entry(item_url, title=item.get("title"), duration=item.get("duration"))
            if results:
                logging.info("YouTube extract success (non-flat pass): url=%s items=%d", url, len(results))
                return (results, "")
    except Exception as e:
        logging.exception("YouTube extract fallback failed: url=%s err=%s", url, e)

    single = info.get("webpage_url") or info.get("url")
    if single:
        _push_entry(single, title=info.get("title"), duration=info.get("duration"))
        if results:
            logging.info("YouTube extract success (single item): url=%s", url)
            return (results, "")
    truncated_hint = _youtube_truncated_id_hint(url)
    if truncated_hint:
        logging.warning("YouTube extract rejected truncated ID: url=%s reason=%s", url, truncated_hint)
        return ([], truncated_hint)
    logging.warning("YouTube extract produced no playable entries: url=%s", url)
    return ([], "no playable YouTube entries found")


class URLResolveWorker(QThread):
    finished_urls = Signal(list, dict, dict, str, list)
    progress_count = Signal(int)

    def __init__(self, raw_urls, auth=None):
        super().__init__()
        self.raw_urls = list(raw_urls)
        self.auth = auth or {}

    def run(self):
        all_items = []
        title_map = {}
        duration_map = {}
        failures = []
        failure_seen = set()
        seen = set()
        last_error = ""

        def _set_error(msg: str):
            nonlocal last_error
            if msg and not last_error:
                last_error = str(msg)

        self.progress_count.emit(0)
        logging.info("URL resolve worker started: raw_count=%d", len(self.raw_urls))

        def _record_failure(source: str, reason: str):
            src = str(source or "").strip()
            msg = str(reason or "").strip()
            if not src or not msg:
                return
            key = (src.casefold(), msg.casefold())
            if key in failure_seen:
                return
            failure_seen.add(key)
            failures.append({"source": src, "reason": msg})

        try:
            for raw in self.raw_urls:
                if self.isInterruptionRequested():
                    logging.debug("URL resolve worker interrupted")
                    break
                url = str(raw).strip()
                if not url:
                    continue
                source_kind = "direct"
                source_error = ""
                logging.debug("Resolving URL: kind=unknown raw=%s", url)

                try:
                    if _is_youtube_url(url):
                        source_kind = "youtube"
                        direct_video = _youtube_direct_video_url(url)
                        if direct_video and not _youtube_looks_like_playlist_url(url):
                            yt_title, yt_duration, yt_single_error = _extract_youtube_single_metadata(direct_video)
                            if yt_single_error:
                                resolved = []
                                source_error = yt_single_error
                                _set_error(source_error)
                                logging.warning(
                                    "YouTube direct video rejected: url=%s reason=%s",
                                    url,
                                    yt_single_error,
                                )
                            else:
                                resolved = [direct_video]
                                if yt_title and not _is_placeholder_title(yt_title):
                                    title_map[direct_video] = yt_title
                                if yt_duration is not None and yt_duration >= 0:
                                    duration_map[direct_video] = float(yt_duration)
                            logging.debug("Resolving URL as direct YouTube video: %s", url)
                        else:
                            logging.debug("Resolving URL as YouTube extract: %s", url)
                            entries, yt_error = _extract_youtube_entries(url)
                            _set_error(yt_error)
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
                            if not resolved:
                                source_error = yt_error or "no playable YouTube entries found"
                                _set_error(source_error)
                            logging.info(
                                "YouTube resolve result: url=%s items=%d error=%s",
                                url,
                                len(resolved),
                                yt_error or "",
                            )
                    elif _looks_like_m3u_url(url):
                        source_kind = "m3u"
                        logging.debug("Resolving URL as remote playlist: %s", url)
                        resolved = _fetch_remote_m3u(url, auth=self.auth)
                        if not resolved:
                            raise ValueError("no entries found in remote playlist")
                    elif _looks_like_directory_stream_url(url):
                        source_kind = "webdav"
                        logging.debug("Resolving URL as WebDAV folder: %s", url)
                        resolved = _fetch_webdav_files_recursive(url, auth=self.auth)
                        if not resolved:
                            raise ValueError("no media files found in webdav folder")
                    else:
                        logging.debug("Resolving URL as direct stream: %s", url)
                        resolved = [_sanitize_http_url(url)]
                except HTTPError as e:
                    logging.warning("URL resolve HTTP error: kind=%s url=%s code=%s", source_kind, url, e.code)
                    if e.code in (401, 403):
                        if source_kind == "webdav":
                            source_error = "webdav authentication failed"
                            _set_error(source_error)
                        else:
                            source_error = "authentication failed"
                            _set_error(source_error)
                    else:
                        source_error = f"http {e.code}"
                        _set_error(source_error)
                    resolved = [] if source_kind in {"youtube", "m3u", "webdav"} else [url]
                except PermissionError as e:
                    logging.warning("URL resolve permission error: kind=%s url=%s err=%s", source_kind, url, e)
                    source_error = str(e)
                    _set_error(source_error)
                    resolved = []
                except TimeoutError:
                    logging.warning("URL resolve timeout: kind=%s url=%s", source_kind, url)
                    if source_kind == "webdav":
                        source_error = "webdav request timed out"
                        _set_error(source_error)
                    else:
                        source_error = "timeout"
                        _set_error(source_error)
                    resolved = [] if source_kind in {"youtube", "m3u", "webdav"} else [url]
                except (URLError, ValueError):
                    logging.warning("URL resolve invalid/unreachable: kind=%s url=%s", source_kind, url)
                    if source_kind == "webdav":
                        source_error = "invalid/unreachable WebDAV URL or response"
                        _set_error(source_error)
                    elif source_kind == "m3u":
                        source_error = "invalid/unreachable playlist URL"
                        _set_error(source_error)
                    elif source_kind == "youtube":
                        source_error = "invalid/unreachable YouTube URL"
                        _set_error(source_error)
                    else:
                        source_error = "invalid or unreachable URL"
                        _set_error(source_error)
                    resolved = [] if source_kind in {"youtube", "m3u", "webdav"} else [url]
                except Exception as e:
                    logging.exception("URL resolve unexpected error: kind=%s url=%s err=%s", source_kind, url, e)
                    if source_kind == "webdav":
                        source_error = "could not resolve WebDAV folder"
                        _set_error(source_error)
                    elif source_kind == "m3u":
                        source_error = "could not resolve remote playlist"
                        _set_error(source_error)
                    elif source_kind == "youtube":
                        source_error = "could not extract YouTube entries"
                        _set_error(source_error)
                    else:
                        source_error = "could not resolve URL"
                        _set_error(source_error)
                    resolved = [] if source_kind in {"youtube", "m3u", "webdav"} else [url]

                if not resolved and source_error:
                    _record_failure(url, source_error)

                for item in resolved:
                    item_value = str(item)
                    if _is_stream_url(item_value):
                        item_value = _sanitize_http_url(item_value)
                    key = item_value.casefold()
                    if key not in seen:
                        seen.add(key)
                        all_items.append(item_value)
                        if len(all_items) % 20 == 0:
                            self.progress_count.emit(len(all_items))
        except Exception:
            logging.exception("URL resolver crashed")
            if not last_error:
                last_error = "URL resolver crashed"
        finally:
            logging.info(
                "URL resolve worker finished: resolved=%d titles=%d durations=%d failures=%d error=%s",
                len(all_items),
                len(title_map),
                len(duration_map),
                len(failures),
                last_error,
            )
            self.progress_count.emit(len(all_items))
            self.finished_urls.emit(all_items, title_map, duration_map, last_error, failures)


class DurationScanner(QThread):
    finished_item = Signal(str, str, float) # path, duration_str, seconds


    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        for path in self.paths:
            if self.isInterruptionRequested():
                break
            try:
                flags = 0
                if os.name == "nt":
                    flags = 0x08000000 # CREATE_NO_WINDOW
                
                cmd = [
                    "ffprobe", 
                    "-v", "error", 
                    "-show_entries", "format=duration", 
                    "-of", "default=noprint_wrappers=1:nokey=1", 
                    path
                ]
                completed = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                    timeout=8,
                    check=False,
                    text=True,
                )
                result = str(completed.stdout or "").strip()
                if result:
                    seconds = float(result)
                    dur_str = format_duration(seconds)
                    self.finished_item.emit(path, dur_str, seconds)

            except Exception:
                continue


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
            p_str, key = normalize_playlist_entry(candidate)
            if key not in seen:
                unique_paths.append(p_str)
                seen.add(key)
            if len(unique_paths) - last_emitted >= 200:
                last_emitted = len(unique_paths)
                self.progress_count.emit(last_emitted)
        self.progress_count.emit(len(unique_paths))
        self.finished_paths.emit(unique_paths)


class PlaylistViewMixin:
    def _clear_playlist_before_import(self):
        old_paths = list(self.playlist)
        self.stop_playback()
        self.playlist = []
        self._prune_playlist_metadata(old_paths)
        self.current_index = -1
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self._save_session_playlist_snapshot()

    def _import_playlist_entries(
        self,
        entries,
        replace_existing: bool = False,
        label: str = "",
        title_map: dict | None = None,
        duration_map: dict | None = None,
        resolve_stream_urls: bool = True,
    ):
        cleaned = [str(item).strip() for item in entries if str(item).strip()]
        if not cleaned:
            self.show_status_overlay(tr("No valid files in playlist"))
            return

        title_map = dict(title_map or {})
        duration_map = dict(duration_map or {})

        if replace_existing:
            self._clear_playlist_before_import()

        is_idle = self._player_is_idle()
        autoplay = bool(replace_existing or is_idle)

        local_paths = [item for item in cleaned if not _is_stream_url(item)]
        stream_urls = [item for item in cleaned if _is_stream_url(item)]

        if local_paths:
            local_titles = {k: v for k, v in title_map.items() if k in local_paths}
            local_durations = {k: v for k, v in duration_map.items() if k in local_paths}
            self.append_to_playlist_async(
                local_paths,
                play_new=autoplay,
                on_done=lambda _new_items: None,
                title_map=local_titles,
                duration_map=local_durations,
            )
            autoplay = False
        if stream_urls:
            stream_titles = {k: v for k, v in title_map.items() if k in stream_urls}
            stream_durations = {k: v for k, v in duration_map.items() if k in stream_urls}
            if resolve_stream_urls:
                self.import_stream_sources_async(
                    stream_urls,
                    play_new=autoplay,
                    title_map=stream_titles,
                    duration_map=stream_durations,
                )
            else:
                self._register_stream_auth_rules(stream_urls, load_stream_auth_settings())
                self.append_to_playlist_async(
                    stream_urls,
                    play_new=autoplay,
                    on_done=lambda _new_items: None,
                    title_map=stream_titles,
                    duration_map=stream_durations,
                )

        action = tr("Loaded") if replace_existing else tr("Added")
        if label:
            self.show_status_overlay(f"{action} {label}")

    def _import_dropped_m3u_sources(self, local_m3u_paths, remote_m3u_urls, replace_existing: bool):
        entries = []
        for playlist_path in local_m3u_paths:
            try:
                entries.extend(parse_local_m3u(str(playlist_path)))
            except Exception as e:
                logging.warning("Could not parse local playlist drop: path=%s err=%s", playlist_path, e)

        self._import_playlist_entries(
            entries,
            replace_existing=replace_existing,
            label=tr("{} items").format(len(entries)) if entries else "",
        )

        if remote_m3u_urls:
            self.import_stream_sources_async(
                remote_m3u_urls,
                play_new=bool(replace_existing and not entries),
            )

    def handle_dropped_paths(self, paths, remote_urls=None, drop_target: str = "auto"):
        remote_urls = [str(u).strip() for u in (remote_urls or []) if str(u).strip()]
        if not paths and not remote_urls:
            return

        effective_target = drop_target if drop_target in {"video", "playlist"} else "video"
        replace_existing = effective_target == "video"
        subtitle_exts = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
        media_files = []
        subtitle_files = []
        folders = []
        local_m3u_files = []
        for p in paths:
            if p.is_file():
                ext = p.suffix.lower()
                if ext in subtitle_exts:
                    subtitle_files.append(str(p.resolve()))
                elif _looks_like_m3u_path(str(p)):
                    local_m3u_files.append(p)
                elif is_media_file(p):
                    media_files.append(str(p.resolve()))
            elif p.is_dir():
                folders.append(p)

        remote_m3u_urls = [u for u in remote_urls if _looks_like_m3u_url(u)]
        direct_stream_urls = [u for u in remote_urls if _is_stream_url(u) and not _looks_like_m3u_url(u)]

        if local_m3u_files or remote_m3u_urls:
            self._import_dropped_m3u_sources(
                local_m3u_files,
                remote_m3u_urls,
                replace_existing=replace_existing,
            )
            return

        if subtitle_files and not media_files and not folders and not direct_stream_urls:
            if self.player.time_pos is not None:
                for sub in subtitle_files:
                    self.player.command("sub-add", sub)
                self.show_status_overlay(tr("Subtitle(s) added"))
            else:
                self.show_status_overlay(tr("Open a video before adding subtitles"))
            return

        if replace_existing and (direct_stream_urls or media_files or folders):
            self._clear_playlist_before_import()

        autoplay = bool(replace_existing or self._player_is_idle())
        if direct_stream_urls:
            self.import_stream_sources_async(direct_stream_urls, play_new=autoplay)
            autoplay = False

        if media_files or folders:
            raw_inputs = [Path(f) for f in media_files] + folders
            recursive = True
            if folders:
                recursive = self._ask_recursive_import()
            self.append_to_playlist_async(
                raw_inputs,
                play_new=autoplay,
                recursive=recursive,
                use_collect=True,
                on_done=lambda new_items: self.show_status_overlay(
                    tr("Added {count}").format(count=len(new_items))
                ),
            )

    def _ask_recursive_import(self) -> bool:
        res = self._show_message(
            QMessageBox.Question,
            tr("Include Subfolders"),
            tr("Do you want to include media from subfolders as well?"),
            QMessageBox.Yes | QMessageBox.No,
        )
        return res == QMessageBox.Yes

    def is_video_file(self, path: Path) -> bool:
        return is_video_file(path)

    def is_audio_file(self, path: Path) -> bool:
        return is_audio_file(path)

    def collect_paths(self, paths, recursive: bool = False):
        return collect_paths(paths, recursive=recursive)

    def load_startup_paths(self, raw_paths):
        paths = [Path(p) for p in raw_paths if p]
        paths = [p for p in paths if p.exists()]
        if not paths:
            if not raw_paths and bool(getattr(self, "restore_session_on_startup", False)):
                self.restore_session_playlist(silent_if_missing=True)
            return

        if len(paths) == 1 and paths[0].is_file() and self.is_video_file(paths[0]):
            self.quick_open_file(paths[0])
            return

        loaded = self.collect_paths(paths, recursive=True)
        if not loaded:
            return
        old_set = set(str(p) for p in self.playlist)
        new_set = set(str(p) for p in loaded)
        self._prune_playlist_metadata(old_set - new_set)
        self.playlist = loaded
        self.current_index = 0
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self._save_session_playlist_snapshot()
        logging.info(
            "Startup playlist loaded: items=%d current_index=%d",
            len(self.playlist),
            self.current_index,
        )
        self.play_current()

    def quick_open_file(self, file_path: Path):
        selected = file_path.resolve()
        sel_str = os.path.normpath(str(selected))
        sel_lower = sel_str.lower()

        siblings = list_folder_media(selected.parent)
        try:
            match_idx = next(
                i for i, s in enumerate(siblings) if os.path.normpath(s).lower() == sel_lower
            )
        except StopIteration:
            siblings.insert(0, sel_str)
            match_idx = 0

        old_set = set(str(p) for p in self.playlist)
        new_set = set(str(p) for p in siblings)
        self._prune_playlist_metadata(old_set - new_set)
        self.playlist = siblings
        self.current_index = match_idx
        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self._save_session_playlist_snapshot()
        self.play_current()

    def append_to_playlist(
        self,
        paths,
        play_new: bool = False,
        autoplay_if_empty: bool = True,
    ):
        if not paths:
            return []

        existing_keys = {normalize_playlist_entry(existing)[1] for existing in self.playlist}
        unique_paths = []
        seen = set(existing_keys)
        for p in paths:
            p_str, key = normalize_playlist_entry(p)
            if key not in seen:
                unique_paths.append(p_str)
                seen.add(key)

        return self._apply_prepared_playlist_paths(
            unique_paths,
            play_new=play_new,
            autoplay_if_empty=autoplay_if_empty,
        )

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

        self._active_prepare_request = self._prepare_queue.popleft()
        req = self._active_prepare_request
        existing_keys = {normalize_playlist_entry(existing)[1] for existing in self.playlist}
        self._apply_resolved_metadata(
            title_map=req.get("title_map", {}),
            duration_map=req.get("duration_map", {}),
        )
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
        if self._is_shutting_down:
            return
        self._import_progress_count = max(self._import_progress_count, max(0, int(count)))

    def _on_prepare_worker_finished(self, unique_paths):
        if self._is_shutting_down:
            self._active_prepare_worker = None
            self._active_prepare_request = None
            return
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
        if self._is_shutting_down:
            return
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
        if not self._cached_paused:
            return False
        if self._last_duration > 0 or self._last_position > 0.5:
            return False
        return True

    def _can_switch_track_now(self, manual: bool = True) -> bool:
        if not manual:
            return True
        now = time.monotonic()
        if self._is_engine_busy:
            if (now - self._last_load_attempt_at) <= self._engine_busy_timeout_sec:
                return False
            self._is_engine_busy = False
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

    def _apply_prepared_playlist_paths(
        self,
        unique_paths,
        play_new: bool = False,
        autoplay_if_empty: bool = True,
    ):
        if not unique_paths:
            return []

        start_count = len(self.playlist)
        self.playlist.extend(unique_paths)
        if self.current_index < 0 and self.playlist:
            self.current_index = 0

        self.rebuild_shuffle_order(keep_current=True)

        if start_count > 0:
            self._append_to_view(unique_paths)
        else:
            self.refresh_playlist_view()

        if play_new and self.playlist:
            self.current_index = start_count
            self.play_current()
        elif autoplay_if_empty and start_count == 0 and self._player_is_idle() and self.playlist:
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
        self._save_session_playlist_snapshot()
        return unique_paths

    def import_stream_sources_async(
        self,
        urls,
        play_new: bool = False,
        auth=None,
        title_map: dict | None = None,
        duration_map: dict | None = None,
    ):
        cleaned = [str(u).strip() for u in urls if str(u).strip()]
        logging.info("Queue stream import: raw=%d cleaned=%d", len(urls or []), len(cleaned))
        if not cleaned:
            self.show_status_overlay(tr("No URL provided"))
            return
        if auth is None:
            auth = load_stream_auth_settings()
        self._url_queue.append(
            {
                "urls": cleaned,
                "play_new": play_new,
                "auth": auth,
                "title_map": dict(title_map or {}),
                "duration_map": dict(duration_map or {}),
            }
        )
        self.show_status_overlay(tr("Resolving stream URLs..."))
        self._start_next_url_worker()

    def _start_next_url_worker(self):
        if self._active_url_worker is not None:
            try:
                if not self._active_url_worker.isRunning():
                    self._active_url_worker = None
                    self._active_url_request = None
                else:
                    return
            except Exception as e:
                logging.debug("URL worker state check failed; resetting worker state: %s", e)
                self._active_url_worker = None
                self._active_url_request = None
        if not self._url_queue:
            return
        self._active_url_request = self._url_queue.popleft()
        req = self._active_url_request
        self._url_progress_count = 0
        self._start_url_resolve_status()
        worker = self._create_url_resolve_worker(req["urls"], auth=req.get("auth"))
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
        if self._is_shutting_down:
            return
        if self._url_resolve_active:
            if self._url_progress_count > 0:
                self.show_status_overlay(
                    tr("Resolving stream URLs... {}").format(self._url_progress_count)
                )
            else:
                self.show_status_overlay(tr("Resolving stream URLs..."))

    def _on_url_worker_progress(self, count):
        if self._is_shutting_down:
            return
        self._url_progress_count = max(0, int(count))

    def _stop_url_resolve_status(self):
        self._url_resolve_active = False
        if self._url_status_timer.isActive():
            self._url_status_timer.stop()

    def _register_stream_auth_rules(self, urls, auth):
        if not auth or not auth.get("enabled"):
            return
        username = str(auth.get("username") or "")
        password = str(auth.get("password") or "")
        if not username:
            return
        token = f"{username}:{password}".encode("utf-8")
        auth_value = "Basic " + base64.b64encode(token).decode("ascii")
        for item in urls:
            parsed = urlparse(str(item))
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                host = parsed.netloc.split("@")[-1].lower()
                self._stream_auth_by_host[host] = auth_value
                while len(self._stream_auth_by_host) > self._stream_auth_cache_limit:
                    self._stream_auth_by_host.pop(next(iter(self._stream_auth_by_host)), None)

    def _on_url_worker_finished(self, resolved_urls, title_map, duration_map, error_msg, failures):
        if self._is_shutting_down:
            self._active_url_worker = None
            self._active_url_request = None
            return
        req = self._active_url_request or {}
        preset_title_map = dict(req.get("title_map", {}) if isinstance(req, dict) else {})
        preset_duration_map = dict(req.get("duration_map", {}) if isinstance(req, dict) else {})
        title_map = dict(title_map or {})
        duration_map = dict(duration_map or {})
        resolved_set = {str(u).casefold() for u in (resolved_urls or [])}
        for key, value in preset_title_map.items():
            s_key = str(key)
            if s_key.casefold() in resolved_set and s_key not in title_map and str(value).strip():
                title_map[s_key] = str(value).strip()
        for key, value in preset_duration_map.items():
            s_key = str(key)
            if s_key.casefold() not in resolved_set or s_key in duration_map:
                continue
            try:
                sec = float(value)
                if sec >= 0:
                    duration_map[s_key] = sec
            except (TypeError, ValueError):
                continue
        failure_items = list(failures or [])
        failure_count = len(failure_items)
        logging.info(
            "URL worker callback: requested=%d resolved=%d failures=%d error=%s",
            len(req.get("urls", []) if isinstance(req, dict) else []),
            len(resolved_urls or []),
            failure_count,
            error_msg or "",
        )
        for item in failure_items:
            src = str((item or {}).get("source") or "")
            reason = str((item or {}).get("reason") or "")
            if src and reason:
                logging.warning("Stream import item failed: source=%s reason=%s", src, reason)
        self._active_url_worker = None
        self._active_url_request = None
        self._stop_url_resolve_status()
        if not resolved_urls:
            msg = str(error_msg or "").strip()
            if failure_count > 0:
                first_reason = ""
                if failure_count == 1:
                    first_reason = str((failure_items[0] or {}).get("reason") or "").strip()
                if first_reason:
                    self.show_status_overlay(tr("Stream import failed: {}").format(first_reason))
                else:
                    self.show_status_overlay(tr("Imported 0, failed {}").format(failure_count))
            else:
                self.show_status_overlay(
                    tr("Stream import failed: {}").format(msg)
                    if msg
                    else tr("No stream URLs found")
                )
            self._start_next_url_worker()
            return

        play_new = bool(req.get("play_new", False))
        self._apply_resolved_metadata(title_map=title_map, duration_map=duration_map)
        self._register_stream_auth_rules(resolved_urls, req.get("auth"))
        self.append_to_playlist_async(
            resolved_urls,
            play_new=play_new,
            title_map=title_map,
            duration_map=duration_map,
            on_done=lambda new_items, failed=failure_count, err=error_msg: self.show_status_overlay(
                tr("Imported {}, failed {}").format(len(new_items), failed)
                if failed > 0
                else tr("Imported {} stream items").format(len(new_items))
            )
            if new_items
            else self.show_status_overlay(
                tr("Imported 0, failed {}").format(failed)
                if failed > 0
                else (
                    tr("No new items imported")
                    if not err
                    else tr("Stream import failed: {}").format(err)
                )
            ),
        )
        self._start_next_url_worker()

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
        dialog = QFileDialog(self, tr("Select files to open"), "")
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilter(filter_str)
        files = self._run_file_dialog(dialog)
        if files:
            self.append_to_playlist_async(
                files,
                play_new=False,
                on_done=lambda new_items: self.show_status_overlay(
                    tr("Added {count}").format(count=len(new_items))
                ),
            )

    def add_folder_dialog(self):
        dialog = QFileDialog(self, tr("Select folder to open"), "")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        selected = self._run_file_dialog(dialog)
        folder = selected[0] if selected else ""
        if folder:
            recursive = self._ask_recursive_import()
            self.append_to_playlist_async(
                [folder],
                play_new=False,
                recursive=recursive,
                use_collect=True,
                on_done=lambda new_items: self.show_status_overlay(
                    tr("Added {count}").format(count=len(new_items))
                ),
            )

    def _duration_scan_batch_size(self, allow_while_playing: bool = False) -> int:
        is_playing = (not self._cached_paused and self.current_index >= 0)
        if is_playing and not allow_while_playing:
            return 0
        if is_playing:
            if len(self.playlist) > 1000:
                return 1
            if len(self.playlist) > 800:
                return 2
            return 3
        if len(self.playlist) > 1000:
            return 25
        return 80

    def scan_durations(self, paths=None, allow_while_playing: bool = False, force: bool = False):
        if not force and not self._full_duration_scan_active:
            return
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
        if self.scanners:
            return
        batch_size = self._duration_scan_batch_size(allow_while_playing=allow_while_playing)
        if batch_size <= 0:
            return
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
        if self._is_shutting_down:
            return
        if scanner in self.scanners:
            self.scanners.remove(scanner)
        try:
            scanner.deleteLater()
        except Exception:
            pass
        if self._full_duration_scan_active:
            if self._full_duration_scan_cancel_requested:
                if not self.scanners:
                    self._finish_full_duration_scan(cancelled=True)
                return
            if self._pending_duration_paths:
                self.scan_durations(None, allow_while_playing=True, force=True)
                return
            if not self.scanners:
                self._finish_full_duration_scan(cancelled=False)

    def _on_duration_found(self, path, dur_str, seconds):
        if self._is_shutting_down:
            return
        self.playlist_durations[path] = dur_str
        self.playlist_raw_durations[path] = seconds
        if hasattr(self, "playlist_model"):
            self.playlist_model.update_duration(path, dur_str)
        if self._full_duration_scan_active:
            self._full_duration_scan_done = min(
                self._full_duration_scan_total,
                self._full_duration_scan_done + 1,
            )
            self.show_status_overlay(
                tr("Scanning durations... {}/{}").format(
                    self._full_duration_scan_done,
                    self._full_duration_scan_total,
                )
            )

    def _finish_full_duration_scan(self, cancelled: bool):
        self._full_duration_scan_active = False
        self._full_duration_scan_cancel_requested = False
        self._pending_duration_paths.clear()
        if cancelled:
            self.show_status_overlay(
                tr("Duration scan cancelled ({}/{})").format(
                    self._full_duration_scan_done,
                    self._full_duration_scan_total,
                )
            )
        else:
            self.show_status_overlay(
                tr("Duration scan complete ({}/{})").format(
                    self._full_duration_scan_done,
                    self._full_duration_scan_total,
                )
            )
        self._full_duration_scan_total = 0
        self._full_duration_scan_done = 0
        self.update_transport_icons()

    def toggle_full_duration_scan(self):
        if self._full_duration_scan_active:
            self._full_duration_scan_cancel_requested = True
            self._pending_duration_paths.clear()
            for scanner in list(self.scanners):
                try:
                    scanner.requestInterruption()
                except Exception:
                    pass
            self.show_status_overlay(tr("Cancelling duration scan..."))
            if not self.scanners:
                self._finish_full_duration_scan(cancelled=True)
            return

        if not self.playlist:
            self.show_status_overlay(tr("Playlist is empty"))
            return

        targets = []
        for item in self.playlist:
            p = str(item)
            if _is_stream_url(p):
                continue
            dur = self.playlist_raw_durations.get(p)
            if isinstance(dur, (int, float)) and dur > 0:
                continue
            targets.append(p)

        if not targets:
            self.show_status_overlay(tr("All local item durations are already known"))
            return

        confirm = self._show_message(
            QMessageBox.Question,
            tr("Scan All Durations"),
            tr("Scan {} local playlist items for duration now?\nPlayback will stay paused until scan finishes or is cancelled.").format(len(targets)),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._full_duration_scan_active = True
        self._full_duration_scan_cancel_requested = False
        self._full_duration_scan_total = len(targets)
        self._full_duration_scan_done = 0
        self._pending_duration_paths = list(targets)
        self._set_mpv_property_safe("pause", True, allow_during_busy=True)
        self._cached_paused = True
        self._user_paused = True
        self.update_transport_icons()
        self.show_status_overlay(tr("Scanning durations... 0/{}").format(self._full_duration_scan_total))
        self.scan_durations(None, allow_while_playing=True, force=True)

    def refresh_playlist_view(self):
        if not hasattr(self, "playlist_widget"):
            return

        self._playlist_refresh_lock = True
        self.playlist_model.set_paths([], self.playlist_durations, self.playlist_titles)
        self._append_to_view(self.playlist, apply_filter=False)
        self._playlist_refresh_lock = False
        self.apply_playlist_filter()
        self.highlight_current_item()

    def _append_to_view(self, paths, apply_filter: bool = True):
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
        if self._full_duration_scan_active:
            self.show_status_overlay(tr("Duration scan is running (F4 to cancel)"))
            return
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

    def remove_playlist_index(self, index: int):
        self.remove_playlist_indices([index])

    def remove_selected_from_playlist(self):
        indices = self.get_selected_playlist_indices()
        self.remove_playlist_indices(indices)

    def save_current_resume_info(self):
        if not self.playlist or self.current_index < 0:
            return
        # Use cached timeline values to avoid unstable mpv property reads during rapid switching.
        path = self.playlist[self.current_index]
        pos = float(self._last_position or 0.0)
        dur = float(self._last_duration or 0.0)
        if pos <= 0 or dur <= 0:
            return
        if pos > (dur - 15):
            save_resume_position(path, 0)
        else:
            save_resume_position(path, pos)

    def remove_playlist_indices(self, indices: list[int]):
        if not indices:
            return

        current_removed = self.current_index in indices
        current_path = (
            self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        )

        removed_paths = []
        # Remove in reverse order
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self.playlist):
                removed_path = self.playlist.pop(idx)
                removed_paths.append(removed_path)
        self._prune_playlist_metadata(removed_paths)

        if not self.playlist:
            self.current_index = -1
            self.player.stop()
            self.setWindowTitle("Cadre Player")
            if hasattr(self, "title_bar"):
                self.title_bar.info_label.setText("")
            self.seek_slider.set_current_time(0.0)
            self.seek_slider.set_chapters([])
            self.sync_size()
        elif current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        else:
            if self.current_index >= len(self.playlist):
                self.current_index = len(self.playlist) - 1
            if current_removed and self.current_index >= 0:
                self.play_current()

        self.rebuild_shuffle_order(keep_current=True)
        self.refresh_playlist_view()
        self._save_session_playlist_snapshot()

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

        reply = self._show_message(
            QMessageBox.Question,
            tr("Recycle Bin"),
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
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
                self._show_message(
                    QMessageBox.Warning,
                    tr("Error"),
                    tr("Could not delete file."),
                )

    def delete_selected_file_to_trash(self):
        self.delete_to_trash()

    def _prune_playlist_metadata(self, paths):
        for item in paths or []:
            key = str(item)
            self.playlist_titles.pop(key, None)
            self.playlist_durations.pop(key, None)
            self.playlist_raw_durations.pop(key, None)

    def _apply_resolved_metadata(self, title_map=None, duration_map=None):
        for path, title in (title_map or {}).items():
            value = str(title or "").strip()
            if _is_youtube_url(str(path)) and _is_placeholder_title(value):
                continue
            if value:
                self.playlist_titles[path] = value
        for path, seconds in (duration_map or {}).items():
            try:
                sec = float(seconds)
                self.playlist_raw_durations[path] = sec
                self.playlist_durations[path] = format_duration(sec)
            except (TypeError, ValueError):
                continue

    def highlight_current_item(self):
        if not hasattr(self, "playlist_widget"):
            return
        try:
            self.playlist_widget.setProperty("current_playlist_index", self.current_index)
            self.playlist_widget.viewport().update()
            if not self.playlist_widget.isVisible():
                return
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
            self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
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
        self._save_session_playlist_snapshot()

    def show_sort_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)

        az_act = QAction(tr("Name (A-Z)"), menu)
        az_act.triggered.connect(lambda: self.sort_playlist("name", False))

        za_act = QAction(tr("Name (Z-A)"), menu)
        za_act.triggered.connect(lambda: self.sort_playlist("name", True))

        dur_asc_act = QAction(tr("Duration (Shortest first)"), menu)
        dur_asc_act.triggered.connect(lambda: self.sort_playlist("duration", False))

        dur_desc_act = QAction(tr("Duration (Longest first)"), menu)
        dur_desc_act.triggered.connect(lambda: self.sort_playlist("duration", True))

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
        scan_label = (
            tr("Cancel Duration Scan") + "(F4)"
            if self._full_duration_scan_active
            else tr("Scan All Durations") + "(F4)"
        )
        scan_act = QAction(scan_label, menu)
        scan_act.triggered.connect(self.toggle_full_duration_scan)
        menu.addAction(scan_act)
        menu.addSeparator()
        menu.addAction(folder_act)

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
            self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        )

        if criteria == "name":
            if self.sort_include_folders:
                self.playlist.sort(key=lambda x: x.lower(), reverse=reverse)
            else:
                self.playlist.sort(key=lambda x: Path(x).name.lower(), reverse=reverse)
        elif criteria == "duration":
            known = []
            unknown = []
            for item in self.playlist:
                dur = self.playlist_raw_durations.get(item)
                if isinstance(dur, (int, float)) and dur > 0:
                    known.append(item)
                else:
                    unknown.append(item)
            known.sort(
                key=lambda x: float(self.playlist_raw_durations.get(x, 0.0)),
                reverse=reverse,
            )
            self.playlist = known + unknown

        if current_path and current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)

        self.rebuild_shuffle_order(keep_current=True)
        key_name = tr("Path") if (criteria == "name" and self.sort_include_folders) else tr(criteria.capitalize())
        dir_name = tr("DESC") if reverse else tr("ASC")
        self.show_status_overlay(tr("Sorted: {} {}").format(key_name, dir_name))
        self.refresh_playlist_view()
        self.highlight_current_item()

    def _session_playlist_path(self) -> str:
        return str(get_user_data_path("session_playlist.m3u"))

    def _write_m3u_playlist(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            current_index = int(self.current_index) if 0 <= int(self.current_index) < len(self.playlist) else -1
            current_path = ""
            if current_index >= 0:
                current_path = str(self.playlist[current_index])
            f.write(f"#EXTCADRE:CURRENT_INDEX={current_index}\n")
            f.write(f"#EXTCADRE:CURRENT_PATH={quote(current_path, safe='')}\n")
            for item_path in self.playlist:
                name = self.playlist_titles.get(item_path, "").strip()
                if _is_youtube_url(item_path) and _is_placeholder_title(name):
                    name = ""
                if not name:
                    if _is_stream_url(item_path):
                        name = _fallback_stream_title(item_path)
                    else:
                        name = Path(item_path).name
                raw_dur = self.playlist_raw_durations.get(item_path, -1)
                dur_int = int(raw_dur) if raw_dur > 0 else -1
                f.write(f"#EXTINF:{dur_int},{name}\n")
                f.write(f"{item_path}\n")

    def _read_session_snapshot_meta(self, path: str) -> tuple[int, str]:
        current_index = -1
        current_path = ""
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                for raw_line in f:
                    line = str(raw_line or "").strip()
                    if not line:
                        continue
                    if not line.startswith("#"):
                        break
                    if line.startswith("#EXTCADRE:CURRENT_INDEX="):
                        value = line.split("=", 1)[1].strip()
                        try:
                            current_index = int(value)
                        except (TypeError, ValueError):
                            current_index = -1
                    elif line.startswith("#EXTCADRE:CURRENT_PATH="):
                        encoded = line.split("=", 1)[1].strip()
                        current_path = unquote(encoded) if encoded else ""
        except Exception as e:
            logging.debug("Session snapshot metadata read failed: path=%s err=%s", path, e)
        return current_index, current_path

    def _save_session_playlist_snapshot(self):
        path = self._session_playlist_path()
        try:
            if not self.playlist:
                if os.path.exists(path):
                    os.remove(path)
                return
            self._write_m3u_playlist(path)
        except Exception as e:
            logging.warning("Could not save session playlist: path=%s err=%s", path, e)

    def restore_session_playlist(self, silent_if_missing: bool = False):
        path = self._session_playlist_path()
        if not os.path.exists(path):
            if not silent_if_missing:
                self.show_status_overlay(tr("No saved session playlist"))
            return
        try:
            target_index, target_path = self._read_session_snapshot_meta(path)
            entries, title_map, duration_map = parse_local_m3u_with_meta(path)
            if entries:
                self._clear_playlist_before_import()
                self._apply_resolved_metadata(title_map=title_map, duration_map=duration_map)
                # Avoid initial auto-play race: restore target index first, then play once.
                self.append_to_playlist(entries, play_new=False, autoplay_if_empty=False)
                if target_path and target_path in self.playlist:
                    self.current_index = self.playlist.index(target_path)
                elif 0 <= target_index < len(self.playlist):
                    self.current_index = int(target_index)
                elif self.playlist:
                    self.current_index = 0
                self.rebuild_shuffle_order(keep_current=True)
                self.highlight_current_item()
                if self.playlist and self.current_index >= 0:
                    self.play_current()
                self.show_status_overlay(tr("Restored {} session items").format(len(entries)))
            else:
                if not silent_if_missing:
                    self.show_status_overlay(tr("Saved session playlist is empty"))
        except Exception as e:
            logging.warning("Could not restore session playlist: path=%s err=%s", path, e)
            if not silent_if_missing:
                self.show_status_overlay(tr("Could not restore session playlist"))

    def save_playlist_m3u(self):
        if not self.playlist:
            return

        dialog = QFileDialog(self, tr("Save Playlist"), "")
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilter(tr("M3U Playlist (*.m3u)"))
        selected = self._run_file_dialog(dialog)
        path = selected[0] if selected else ""
        if not path:
            return

        if not path.endswith(".m3u"):
            path += ".m3u"

        try:
            self._write_m3u_playlist(path)
            self.show_status_overlay(tr("Playlist Saved"))
        except Exception as e:
            self._show_message(
                QMessageBox.Critical,
                tr("Error"),
                tr("Could not save playlist: {}").format(e),
            )

    def load_playlist_m3u(self):
        dialog = QFileDialog(self, tr("Open Playlist"), "")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter(tr("M3U Playlist (*.m3u);;All files (*.*)"))
        selected = self._run_file_dialog(dialog)
        path = selected[0] if selected else ""
        if not path:
            return

        try:
            entries, title_map, duration_map = parse_local_m3u_with_meta(path)
            if entries:
                self._import_playlist_entries(
                    entries,
                    replace_existing=True,
                    title_map=title_map,
                    duration_map=duration_map,
                )
                self.show_status_overlay(tr("Loaded {} items").format(len(entries)))
            else:
                self.show_status_overlay(tr("No valid files in playlist"))
        except Exception as e:
            self._show_message(
                QMessageBox.Critical,
                tr("Error"),
                tr("Could not load playlist: {}").format(e),
            )

    def toggle_playlist_panel(self):
        if hasattr(self, "playlist_overlay") and self.playlist_overlay.isVisible():
            self.playlist_overlay.hide()
            return
        self._sync_playlist_overlay_geometry()
        self.playlist_overlay.show()
        self.playlist_overlay.raise_()
        self.playlist_widget.updateGeometries()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1, self.playlist_widget.update)
