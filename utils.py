import os
import sys
import subprocess
import json
import struct
import time
import hashlib
import shutil
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse, unquote
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QThread, Signal

VIDEO_EXTENSIONS = (
    ".3g2",
    ".3gp",
    ".amv",
    ".asf",
    ".avi",
    ".drc",
    ".dv",
    ".f4v",
    ".flv",
    ".gifv",
    ".m2t",
    ".m2ts",
    ".m2v",
    ".m4v",
    ".mjpeg",
    ".mjpg",
    ".mkv",
    ".mov",
    ".mp2v",
    ".mp4",
    ".mpe",
    ".mpeg",
    ".mpg",
    ".mpv",
    ".mts",
    ".mxf",
    ".nut",
    ".ogm",
    ".ogv",
    ".qt",
    ".rm",
    ".rmvb",
    ".roq",
    ".swf",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
    ".y4m",
)
AUDIO_EXTENSIONS = (
    ".aac",
    ".ac3",
    ".aif",
    ".aifc",
    ".aiff",
    ".alac",
    ".amr",
    ".ape",
    ".au",
    ".caf",
    ".dts",
    ".eac3",
    ".flac",
    ".m4a",
    ".m4b",
    ".mka",
    ".mp2",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".ra",
    ".spx",
    ".tta",
    ".wav",
    ".weba",
    ".wma",
    ".wv",
)
ARCHIVE_EXTENSIONS = (
    ".zip",
    ".rar",
)
VIDEO_EXTENSION_SET = set(VIDEO_EXTENSIONS)
AUDIO_EXTENSION_SET = set(AUDIO_EXTENSIONS)
ARCHIVE_EXTENSION_SET = set(ARCHIVE_EXTENSIONS)
ARCHIVE_SOURCE_SCHEME = "cadre-archive"


def is_media_file(path: Path, include_audio: bool = True) -> bool:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSION_SET:
        return True
    if ext in AUDIO_EXTENSION_SET:
        return bool(include_audio)
    return False


def is_archive_file(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSION_SET


def is_playable_file(path: Path, include_audio: bool = True) -> bool:
    return is_media_file(path, include_audio=include_audio) or is_archive_file(path)


def make_archive_member_source(archive_path: Path | str, member_name: str) -> str:
    archive = str(Path(archive_path).resolve())
    return f"{ARCHIVE_SOURCE_SCHEME}:?src={quote(archive, safe='')}&entry={quote(str(member_name or ''), safe='')}"


def is_archive_member_source(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == ARCHIVE_SOURCE_SCHEME


def parse_archive_member_source(value: str) -> tuple[str, str]:
    if not is_archive_member_source(value):
        return "", ""
    parsed = urlparse(str(value or "").strip())
    query = parse_qs(parsed.query)
    archive_path = unquote(query.get("src", [""])[0].strip())
    member_name = unquote(query.get("entry", [""])[0].strip())
    return archive_path, member_name


def list_archive_member_sources(path: Path, include_audio: bool = True) -> list[str]:
    resolved = path.resolve()
    if not is_archive_file(resolved):
        return []
    ext = resolved.suffix.lower()

    if ext == ".zip":
        sources = []
        with zipfile.ZipFile(resolved) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member_path = Path(info.filename)
                if is_media_file(member_path, include_audio=include_audio):
                    sources.append(make_archive_member_source(resolved, info.filename))
        return sources

    if ext == ".rar":
        tool = find_archive_backend_tool()
        if not tool:
            return []
        run_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "timeout": 20,
            "check": False,
        }
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if flags:
                run_kwargs["creationflags"] = flags
        proc = subprocess.run([tool, "-tf", str(resolved)], **run_kwargs)
        if proc.returncode != 0:
            return []
        sources = []
        seen = set()
        for raw_line in (proc.stdout or "").splitlines():
            member_name = str(raw_line or "").strip()
            if not member_name or member_name.endswith(("/", "\\")):
                continue
            if member_name in seen:
                continue
            seen.add(member_name)
            if is_media_file(Path(member_name), include_audio=include_audio):
                sources.append(make_archive_member_source(resolved, member_name))
        return sources

    return []


def find_archive_backend_tool() -> str:
    candidates = []
    base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).parent
    for name in ("bsdtar.exe", "tar.exe", "bsdtar", "tar"):
        candidates.extend([
            str(base_dir / "vendor" / name),
            str(base_dir / name),
        ])
    for name in ("bsdtar", "tar"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)

    seen = set()
    for candidate in candidates:
        token = str(candidate or "").strip()
        if not token:
            continue
        norm = os.path.normcase(os.path.normpath(token))
        if norm in seen:
            continue
        seen.add(norm)
        if Path(token).exists():
            return token
    return ""


def extract_archive_member_to_path(archive_path: str | Path, member_name: str, target_path: str | Path) -> None:
    archive = Path(archive_path).resolve()
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ext = archive.suffix.lower()

    if ext == ".zip":
        with zipfile.ZipFile(archive) as payload:
            with payload.open(member_name) as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
        return

    if ext == ".rar":
        tool = find_archive_backend_tool()
        if not tool:
            raise RuntimeError("No RAR extraction backend is available.")
        run_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": 60,
            "check": False,
        }
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if flags:
                run_kwargs["creationflags"] = flags
        proc = subprocess.run([tool, "-xOf", str(archive), member_name], **run_kwargs)
        if proc.returncode != 0:
            detail = (proc.stderr or b"").decode(errors="replace").strip()
            raise RuntimeError(detail or "RAR extraction failed.")
        target.write_bytes(proc.stdout or b"")
        return

    raise RuntimeError("Unsupported archive type.")


def is_audio_file(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in AUDIO_EXTENSION_SET
SPEED_STEPS = (0.5, 0.75, 1.0, 1.5, 2.0)
REPEAT_OFF = 0
REPEAT_ONE = 1
REPEAT_ALL = 2

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
    
    return base_path / relative_path

def get_user_data_path(filename: str) -> str:
    """Get path for writable user data (settings, resume info)."""
    if getattr(sys, 'frozen', False):
        # In installed mode, use %APPDATA%/CadrePlayer
        app_data = Path(os.getenv('APPDATA')) / "CadrePlayer"
        app_data.mkdir(parents=True, exist_ok=True)
        return str(app_data / filename)
    else:
        # In dev mode, keep it local for easy access
        return str(Path(__file__).parent / filename)


def get_user_data_dir() -> Path:
    """Get writable base directory for app-managed user files."""
    if getattr(sys, "frozen", False):
        app_data = Path(os.getenv("APPDATA")) / "CadrePlayer"
        app_data.mkdir(parents=True, exist_ok=True)
        return app_data
    return Path(__file__).parent


def is_stream_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return bool(parsed.scheme and parsed.netloc)


def media_basename_from_source(source: str) -> str:
    source = str(source or "").strip()
    if not source:
        return "subtitle"
    if is_archive_member_source(source):
        _, member_name = parse_archive_member_source(source)
        return Path(member_name).stem or "subtitle"
    parsed = urlparse(source)
    if parsed.scheme and parsed.netloc:
        name = unquote(Path(parsed.path).name)
        stem = Path(name).stem if name else ""
        return stem or "subtitle"
    return Path(source).stem or "subtitle"


def media_query_from_source(source: str) -> str:
    base = media_basename_from_source(source)
    return base.replace(".", " ").replace("_", " ").strip() or "subtitle"


def compute_opensubtitles_moviehash(file_path: str) -> tuple[str, int]:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise RuntimeError("File not found for hash search.")
    size = path.stat().st_size
    if size < 131072:
        raise RuntimeError("File is too small for OpenSubtitles hash search.")

    chunk_size = 65536
    total = size & 0xFFFFFFFFFFFFFFFF
    with path.open("rb") as handle:
        head = handle.read(chunk_size)
        handle.seek(max(0, size - chunk_size))
        tail = handle.read(chunk_size)

    for block in (head, tail):
        remainder = len(block) % 8
        if remainder:
            block = block + (b"\x00" * (8 - remainder))
        for (part,) in struct.iter_unpack("<Q", block):
            total = (total + part) & 0xFFFFFFFFFFFFFFFF

    return f"{total:016x}", int(size)


class OpenSubtitlesWorkerSignals(QObject):
    status_changed = Signal(str)
    search_finished = Signal(list)
    download_finished = Signal(bytes, str)
    error_occurred = Signal(str)


class OpenSubtitlesAPIError(RuntimeError):
    def __init__(self, code: int, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.code = int(code)
        self.retry_after = float(retry_after or 0.0)


class OpenSubtitlesWorker(QThread):
    API_BASE = "https://api.opensubtitles.com/api/v1"
    APP_API_KEY = "EJyqQ27H2B93PoYjMVjd2x812oq8Xmtx"
    _TOKEN_CACHE: dict[str, tuple[str, str, float]] = {}
    _LOGIN_BLOCK_CACHE: dict[str, tuple[float, bool, str]] = {}

    @classmethod
    def _token_cache_path(cls) -> Path:
        return get_user_data_dir() / "opensubtitles_tokens.json"

    @classmethod
    def _token_cache_digest(cls, username: str, password: str) -> str:
        raw = f"{username}\n{password}".encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _load_disk_token_cache(cls) -> dict:
        path = cls._token_cache_path()
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    @classmethod
    def _save_disk_token_cache(cls, payload: dict) -> None:
        path = cls._token_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except Exception:
            pass

    def __init__(
        self,
        mode: str,
        credentials: dict,
        media_source: str = "",
        query: str = "",
        language: str = "en",
        file_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = str(mode or "").strip().lower()
        self.credentials = credentials or {}
        self.media_source = str(media_source or "")
        self.query = str(query or "").strip()
        self.language = str(language or "en").strip().lower() or "en"
        self.file_id = file_id
        self.signals = OpenSubtitlesWorkerSignals()

    def run(self):
        try:
            if self.mode == "search":
                results = self._run_search("", "")
                self.signals.search_finished.emit(results)
                return
            if self.mode == "download":
                token, base_host = self._login()
                content, filename = self._run_download(token, base_host)
                self.signals.download_finished.emit(content, filename)
                return
            raise RuntimeError("Unsupported OpenSubtitles action.")
        except Exception as exc:
            self.signals.error_occurred.emit(str(exc))

    def _base_headers(self) -> dict:
        ua = "Cadre Player v1.0"
        return {
            "Api-Key": self.APP_API_KEY,
            "Accept": "*/*",
            "User-Agent": ua,
            "X-User-Agent": ua,
        }

    def _api_base(self, base_host: str | None = None) -> str:
        host = str(base_host or "").strip().lower()
        if host.startswith("http://") or host.startswith("https://"):
            return host.rstrip("/") + "/api/v1"
        if host:
            return f"https://{host}/api/v1"
        return self.API_BASE

    def _http_json(
        self,
        method: str,
        endpoint: str,
        headers: dict | None = None,
        params: dict | None = None,
        payload: dict | None = None,
        base_host: str | None = None,
    ) -> dict:
        url = f"{self._api_base(base_host)}{endpoint}"
        if params:
            url = f"{url}?{urlencode(params)}"

        request_headers = dict(headers or {})
        data = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        request = Request(url, data=data, method=method.upper(), headers=request_headers)
        try:
            with urlopen(request, timeout=25) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            message = f"OpenSubtitles API error ({exc.code})."
            retry_after = 0.0
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                payload = json.loads(raw) if raw else {}
                detail = payload.get("message") or payload.get("status")
                if detail:
                    message = f"{message} {detail}"
            except Exception:
                pass
            try:
                reset_raw = str(exc.headers.get("ratelimit-reset", "")).strip()
                if reset_raw:
                    retry_after = max(1.0, float(reset_raw) + 0.2)
            except Exception:
                retry_after = 0.0
            raise OpenSubtitlesAPIError(exc.code, message, retry_after=retry_after) from exc
        except URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    def _http_bytes(self, url: str) -> bytes:
        req = Request(url, method="GET", headers={"User-Agent": "CadrePlayer/1.0"})
        try:
            with urlopen(req, timeout=45) as response:
                return response.read()
        except Exception as exc:
            raise RuntimeError("Failed to fetch subtitle file.") from exc

    def _login(self) -> tuple[str, str]:
        username_raw = str(self.credentials.get("os_username", ""))
        password_raw = str(self.credentials.get("os_password", ""))
        username = username_raw.strip()
        password = password_raw
        if not username and not password:
            return "", ""
        if not username or not password:
            raise RuntimeError("Provide both OpenSubtitles username and password, or leave both empty.")

        cache_key = f"{username}\n{password}"
        digest_key = self._token_cache_digest(username, password)
        cached = self._TOKEN_CACHE.get(cache_key)
        now = time.time()
        if cached:
            cached_token, cached_base, issued_at = cached
            # OpenSubtitles JWT is valid for 24h.
            if (now - float(issued_at)) < (23.5 * 3600):
                return cached_token, cached_base

        disk_cache = self._load_disk_token_cache()
        disk_entry = disk_cache.get(digest_key)
        if isinstance(disk_entry, dict):
            disk_token = str(disk_entry.get("token", "")).strip()
            disk_base = str(disk_entry.get("base_url", "")).strip()
            try:
                disk_issued = float(disk_entry.get("issued_at", 0.0) or 0.0)
            except (TypeError, ValueError):
                disk_issued = 0.0
            if disk_token and (now - disk_issued) < (23.5 * 3600):
                self._TOKEN_CACHE[cache_key] = (disk_token, disk_base, disk_issued)
                return disk_token, disk_base

        blocked = self._LOGIN_BLOCK_CACHE.get(cache_key)
        if blocked:
            blocked_until, invalid_credentials, last_message = blocked
            if invalid_credentials:
                raise RuntimeError(last_message or "OpenSubtitles rejected provided credentials (401).")
            if now < float(blocked_until):
                wait_left = max(1, int(round(float(blocked_until) - now)))
                raise RuntimeError(f"OpenSubtitles rate limit active. Try again in {wait_left}s.")

        self.signals.status_changed.emit("Authenticating...")
        try:
            data = self._http_json(
                "POST",
                "/login",
                headers=self._base_headers(),
                payload={"username": username, "password": password},
            )
        except OpenSubtitlesAPIError as exc:
            if exc.code == 401:
                message = str(exc) or "OpenSubtitles API error (401)."
                self._LOGIN_BLOCK_CACHE[cache_key] = (time.time() + 45.0, True, message)
                if digest_key in disk_cache:
                    disk_cache.pop(digest_key, None)
                    self._save_disk_token_cache(disk_cache)
                raise RuntimeError(message) from exc
            if exc.code == 429:
                retry_after = exc.retry_after if exc.retry_after > 0 else 1.2
                blocked_until = time.time() + retry_after
                message = str(exc) or "OpenSubtitles API error (429)."
                self._LOGIN_BLOCK_CACHE[cache_key] = (blocked_until, False, message)
                wait_left = max(1, int(round(retry_after)))
                raise RuntimeError(f"{message} Retry in {wait_left}s.") from exc
            raise RuntimeError(str(exc)) from exc

        token = str(data.get("token", "")).strip()
        if not token:
            raise RuntimeError("Authentication failed: token not returned.")
        base_url = str(data.get("base_url", "")).strip()
        self._TOKEN_CACHE[cache_key] = (token, base_url, now)
        disk_cache[digest_key] = {
            "token": token,
            "base_url": base_url,
            "issued_at": now,
        }
        # Keep token cache small.
        if len(disk_cache) > 12:
            sorted_items = sorted(
                disk_cache.items(),
                key=lambda kv: float((kv[1] or {}).get("issued_at", 0.0)),
                reverse=True,
            )
            disk_cache = dict(sorted_items[:12])
        self._save_disk_token_cache(disk_cache)
        self._LOGIN_BLOCK_CACHE.pop(cache_key, None)
        return token, base_url

    def _authorized_headers(self, token: str) -> dict:
        headers = self._base_headers()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _parse_search_results(self, payload: dict) -> list[dict]:
        data = payload.get("data") or []
        results = []
        for item in data:
            attrs = item.get("attributes") or {}
            files = attrs.get("files") or []
            file_id = None
            if files and isinstance(files, list):
                file_id = files[0].get("file_id")
            if not file_id:
                continue
            name = str(attrs.get("release") or attrs.get("feature_details", {}).get("title") or f"Subtitle {file_id}")
            language = str(attrs.get("language") or attrs.get("iso639") or "").strip().lower() or "unknown"
            rating = attrs.get("ratings")
            try:
                rating_text = f"{float(rating):.1f}"
            except (TypeError, ValueError):
                rating_text = "N/A"
            results.append(
                {
                    "file_id": int(file_id),
                    "name": name,
                    "language": language,
                    "rating": rating_text,
                }
            )
        return results

    def _run_search(self, token: str, base_host: str = "") -> list[dict]:
        headers = self._authorized_headers(token)
        query = self.query or media_query_from_source(self.media_source)
        lang = self.language or "en"

        hash_results = []
        if self.media_source and not is_stream_url(self.media_source):
            try:
                self.signals.status_changed.emit("Hashing file...")
                moviehash, moviebytesize = compute_opensubtitles_moviehash(self.media_source)
                self.signals.status_changed.emit("Searching...")
                hash_results = self._parse_search_results(
                    self._http_json(
                        "GET",
                        "/subtitles",
                        headers=headers,
                        base_host=base_host,
                        params={
                            "moviehash": moviehash,
                            "moviebytesize": moviebytesize,
                            "languages": lang,
                        },
                    )
                )
            except Exception:
                hash_results = []

        if hash_results:
            return hash_results

        self.signals.status_changed.emit("Searching...")
        return self._parse_search_results(
            self._http_json(
                "GET",
                "/subtitles",
                headers=headers,
                base_host=base_host,
                params={
                    "query": query,
                    "languages": lang,
                },
            )
        )

    def _run_download(self, token: str, base_host: str = "") -> tuple[bytes, str]:
        if self.file_id is None:
            raise RuntimeError("No subtitle selected.")
        self.signals.status_changed.emit("Downloading...")
        headers = self._authorized_headers(token)
        payload = {"file_id": int(self.file_id)}
        data = self._http_json("POST", "/download", headers=headers, payload=payload, base_host=base_host)
        link = str(data.get("link", "")).strip()
        filename = str(data.get("file_name", "")).strip() or f"{self.file_id}.srt"
        if not link:
            raise RuntimeError("Download link was not returned by OpenSubtitles.")
        content = self._http_bytes(link)
        if not content:
            raise RuntimeError("Downloaded subtitle file is empty.")
        return content, filename


def fetch_opensubtitles_languages(timeout: int = 20) -> list[tuple[str, str]]:
    ua = "Cadre Player v1.0"
    headers = {
        "Api-Key": OpenSubtitlesWorker.APP_API_KEY,
        "Accept": "*/*",
        "User-Agent": ua,
        "X-User-Agent": ua,
    }
    req = Request(f"{OpenSubtitlesWorker.API_BASE}/infos/languages", headers=headers, method="GET")
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    payload = json.loads(raw) if raw else {}
    data = payload.get("data") or []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        code = str(row.get("language_code") or "").strip().lower()
        name = str(row.get("language_name") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append((code, name or code))
    out.sort(key=lambda item: (item[1].casefold(), item[0]))
    return out


class OpenSubtitlesLanguagesSignals(QObject):
    finished = Signal(list)
    error = Signal(str)


class OpenSubtitlesLanguagesWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = OpenSubtitlesLanguagesSignals()

    def run(self):
        try:
            langs = fetch_opensubtitles_languages()
            self.signals.finished.emit(langs)
        except Exception as exc:
            self.signals.error.emit(str(exc))


def format_duration(seconds: float) -> str:
    if seconds is None:
        return "--:--"
    
    import math
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"

    # Round to nearest second to reduce one-second jitter between probe/runtime sources.
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def is_video_file(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in VIDEO_EXTENSION_SET

def list_folder_media(folder: Path, recursive: bool = False, include_audio: bool = True) -> list[str]:
    if not folder.exists() or not folder.is_dir():
        return []
    
    if recursive:
        all_media = []
        for root, dirs, filenames in os.walk(folder):
            dirs.sort(key=lambda d: d.lower())
            filenames.sort(key=lambda f: f.lower())
            for filename in filenames:
                full_path = Path(root) / filename
                if is_playable_file(full_path, include_audio=include_audio):
                    all_media.append(str(full_path.resolve()))
        return all_media
    else:
        return [
            str(item.resolve())
            for item in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if item.is_file() and is_playable_file(item, include_audio=include_audio)
        ]

def collect_paths(
    paths: list[Path],
    recursive: bool = False,
    include_audio: bool = True,
    progress_cb=None,
    progress_step: int = 100,
) -> list[str]:
    files = []
    pending_emit = 0

    def maybe_emit(force: bool = False):
        nonlocal pending_emit
        if progress_cb is None:
            return
        if force or pending_emit >= max(1, int(progress_step)):
            progress_cb(len(files))
            pending_emit = 0

    for path in paths:
        resolved = path.resolve()
        if resolved.is_file() and is_playable_file(resolved, include_audio=include_audio):
            files.append(str(resolved))
            pending_emit += 1
            maybe_emit()
        elif resolved.is_dir():
            if recursive:
                for root, dirs, filenames in os.walk(resolved):
                    dirs.sort(key=lambda d: d.lower())
                    filenames.sort(key=lambda f: f.lower())
                    for filename in filenames:
                        full_path = Path(root) / filename
                        if is_playable_file(full_path, include_audio=include_audio):
                            files.append(str(full_path.resolve()))
                            pending_emit += 1
                            maybe_emit()
            else:
                for item in sorted(resolved.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file() and is_playable_file(item, include_audio=include_audio):
                        files.append(str(item.resolve()))
                        pending_emit += 1
                        maybe_emit()
    maybe_emit(force=True)
    return files

def reveal_path(path: str):
    path_obj = Path(path)
    if not path_obj.exists():
        return
    
    if os.name == "nt":
        # Windows-specific: select the file in explorer
        subprocess.run(["explorer", "/select,", str(path_obj.resolve())])
    else:
        # Standard open folder for other OS
        folder = str(path_obj.parent.resolve())
        os.startfile(folder) if hasattr(os, "startfile") else subprocess.run(["open", folder])

def delete_to_trash(path: str) -> bool:
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except Exception:
        logging.exception("Failed to move file to recycle bin: %s", path)
        return False
