from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .version import APP_NAME, GITHUB_LATEST_RELEASE_API
except ImportError:
    from version import APP_NAME, GITHUB_LATEST_RELEASE_API


USER_AGENT = f"{APP_NAME}-Updater"
PORTABLE_ZIP_TEMPLATE = "CadrePlayer-v{version}-windows-x64-portable.zip"
CHECKSUM_SUFFIX = ".sha256"
AUTO_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 20
DOWNLOAD_TIMEOUT_SECONDS = 45
CHUNK_SIZE = 1024 * 1024
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    browser_download_url: str
    size: int | None = None


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    body: str
    zip_asset: ReleaseAsset
    checksum_asset: ReleaseAsset | None


def parse_numeric_version(value: str) -> tuple[int, ...]:
    token = str(value or "").strip()
    match = _VERSION_RE.fullmatch(token)
    if not match:
        raise ValueError(f"Unsupported version format: {value!r}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    if not parts:
        raise ValueError(f"Unsupported version format: {value!r}")
    return parts


def normalize_version(value: str) -> str:
    parts = parse_numeric_version(value)
    return ".".join(str(part) for part in parts)


def compare_versions(left: str, right: str) -> int:
    a = list(parse_numeric_version(left))
    b = list(parse_numeric_version(right))
    width = max(len(a), len(b))
    a.extend([0] * (width - len(a)))
    b.extend([0] * (width - len(b)))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_newer_version(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


def expected_portable_zip_name(version: str) -> str:
    return PORTABLE_ZIP_TEMPLATE.format(version=normalize_version(version))


def should_run_auto_check(last_success_epoch: float, now_epoch: float | None = None) -> bool:
    if last_success_epoch <= 0:
        return True
    now = time.time() if now_epoch is None else float(now_epoch)
    return (now - float(last_success_epoch)) >= AUTO_CHECK_INTERVAL_SECONDS


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }


def _asset_from_payload(payload: dict) -> ReleaseAsset:
    return ReleaseAsset(
        name=str(payload.get("name") or ""),
        browser_download_url=str(payload.get("browser_download_url") or ""),
        size=int(payload["size"]) if payload.get("size") is not None else None,
    )


def select_portable_release(payload: dict) -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise UpdateError("GitHub release response was not an object.")
    if payload.get("draft"):
        raise UpdateError("Latest release is a draft.")
    if payload.get("prerelease"):
        raise UpdateError("Latest release is a prerelease.")

    tag_name = str(payload.get("tag_name") or "").strip()
    try:
        version = normalize_version(tag_name)
    except ValueError as exc:
        raise UpdateError(str(exc)) from exc

    expected_zip = expected_portable_zip_name(version)
    possible_checksum_names = {
        expected_zip + CHECKSUM_SUFFIX,
        expected_zip + ".sha256sum",
        expected_zip + ".sha256.txt",
        expected_zip.replace(".zip", ".sha256"),
        expected_zip.replace(".zip", ".sha256.txt"),
    }
    zip_asset = None
    checksum_asset = None
    for raw_asset in payload.get("assets") or []:
        if not isinstance(raw_asset, dict):
            continue
        asset = _asset_from_payload(raw_asset)
        if asset.name == expected_zip:
            zip_asset = asset
        elif asset.name in possible_checksum_names or asset.name.lower().endswith(".sha256"):
            checksum_asset = asset

    if zip_asset is None or not zip_asset.browser_download_url:
        raise UpdateError(f"Release is missing expected asset: {expected_zip}")
    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        body=str(payload.get("body") or ""),
        zip_asset=zip_asset,
        checksum_asset=checksum_asset,
    )


def fetch_latest_release() -> ReleaseInfo:
    request = Request(GITHUB_LATEST_RELEASE_API, headers=_headers(), method="GET")
    try:
        with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise UpdateError(f"GitHub API request failed ({exc.code}).") from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise UpdateError(f"Network error while checking for updates: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError("GitHub release response was not valid JSON.") from exc
    return select_portable_release(payload)


def update_temp_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "CadrePlayer" / "updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def download_file(
    url: str,
    destination: Path,
    *,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
    progress_callback=None,
    cancel_callback=None,
) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = Request(str(url), headers={"User-Agent": USER_AGENT}, method="GET")
    downloaded = 0
    total = 0
    try:
        with urlopen(request, timeout=timeout) as response:
            try:
                total = int(response.headers.get("Content-Length") or 0)
            except ValueError:
                total = 0
            with tmp.open("wb") as handle:
                while True:
                    if cancel_callback and cancel_callback():
                        raise UpdateError("Download cancelled.")
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)
        tmp.replace(destination)
    except HTTPError as exc:
        raise UpdateError(f"Download failed ({exc.code}).") from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise UpdateError(f"Network error while downloading update: {exc}") from exc
    except OSError as exc:
        raise UpdateError(f"Could not write downloaded update: {exc}") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def parse_sha256_text(text: str, expected_filename: str | None = None) -> str:
    first_line = ""
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        raise UpdateError("Checksum file is empty.")

    parts = first_line.split()
    digest = parts[0].strip().lower() if parts else ""
    if not _SHA256_RE.fullmatch(digest):
        raise UpdateError("Checksum file does not contain a valid SHA-256 hash.")
    if expected_filename and len(parts) > 1:
        provided = parts[-1].strip().lstrip("*")
        if provided and provided != expected_filename:
            raise UpdateError("Checksum file is for a different update package.")
    return digest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected_digest: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != str(expected_digest or "").strip().lower():
        raise UpdateError("Downloaded update failed SHA-256 verification.")


def download_checksum(asset: ReleaseAsset, expected_filename: str) -> str:
    request = Request(asset.browser_download_url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            raw = response.read(8192).decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise UpdateError(f"Checksum download failed ({exc.code}).") from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        raise UpdateError(f"Network error while downloading checksum: {exc}") from exc
    return parse_sha256_text(raw, expected_filename)


def verify_zip_integrity(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad = archive.testzip()
            if bad:
                raise UpdateError(f"Update ZIP is corrupt at: {bad}")
    except zipfile.BadZipFile as exc:
        raise UpdateError("Downloaded update is not a valid ZIP file.") from exc


def validate_zip_members(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise UpdateError("Downloaded update is not a valid ZIP file.") from exc
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise UpdateError("Update ZIP contains unsafe file paths.")


def find_internal_dir(root_dir: Path) -> Path | None:
    root = Path(root_dir)
    for name in ("_internal", "internal"):
        target = root / name
        if target.is_dir():
            return target
    return None


def find_payload_root(staging_dir: Path) -> Path:
    staging = Path(staging_dir).resolve()
    if (staging / "CadrePlayer.exe").is_file():
        return staging
    try:
        children = [c for c in staging.iterdir() if c.is_dir()]
        if len(children) == 1:
            sub = children[0]
            if (sub / "CadrePlayer.exe").is_file():
                return sub
    except OSError:
        pass
    return staging


def validate_staged_package(staging_dir: Path) -> Path:
    payload_root = find_payload_root(staging_dir)
    if not (payload_root / "CadrePlayer.exe").is_file():
        raise UpdateError("Update package is missing CadrePlayer.exe.")
    if find_internal_dir(payload_root) is None:
        raise UpdateError("Update package is missing internal runtime files.")
    return payload_root


def extract_zip_safely(zip_path: Path, staging_dir: Path) -> Path:
    staging = Path(staging_dir).resolve()
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            member_path = Path(name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise UpdateError("Update ZIP contains unsafe file paths.")
            target = (staging / member_path).resolve()
            if staging != target and staging not in target.parents:
                raise UpdateError("Update ZIP contains unsafe file paths.")
            archive.extract(info, staging)
    return validate_staged_package(staging)


def remove_path(path: Path) -> None:
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
