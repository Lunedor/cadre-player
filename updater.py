from __future__ import annotations

import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path


WAIT_TIMEOUT_SECONDS = 45
RETRY_COUNT = 8
RETRY_DELAY_SECONDS = 0.7


def _appdata_dir(env_name: str) -> Path | None:
    raw = os.environ.get(env_name)
    if not raw:
        return None
    return Path(raw) / "CadrePlayer"


def user_data_dirs() -> list[Path]:
    out = []
    for name in ("APPDATA", "LOCALAPPDATA"):
        path = _appdata_dir(name)
        if path is not None:
            out.append(path.resolve())
    return out


def setup_logging() -> None:
    base = _appdata_dir("APPDATA") or (Path.home() / "AppData" / "Roaming" / "CadrePlayer")
    logs_dir = base / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs_dir / "updater.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def message_box(title: str, text: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x10)
    else:
        print(f"{title}: {text}", file=sys.stderr)


def wait_for_pid(pid: int, timeout: float = WAIT_TIMEOUT_SECONDS) -> None:
    if pid <= 0:
        return
    if os.name != "nt":
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.25)
        raise RuntimeError("CadrePlayer did not close in time.")

    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        if result == WAIT_OBJECT_0:
            time.sleep(0.5)
            return
        if result == WAIT_TIMEOUT:
            raise RuntimeError("CadrePlayer did not close in time.")
        raise RuntimeError("Could not wait for CadrePlayer to close.")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def is_relative_safe_zip_name(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def extract_zip_safely(zip_path: Path, staging_dir: Path) -> None:
    root = staging_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if not is_relative_safe_zip_name(info.filename):
                raise RuntimeError("Update ZIP contains unsafe file paths.")
            target = (root / info.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError("Update ZIP contains unsafe file paths.")
            archive.extract(info, root)


def validate_install_dir(install_dir: Path) -> None:
    if not install_dir.is_dir():
        raise RuntimeError("Portable install folder was not found.")
    if not (install_dir / "CadrePlayerUpdater.exe").is_file():
        raise RuntimeError("Installed updater executable was not found.")


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


def validate_staging(payload_root: Path) -> None:
    if not (payload_root / "CadrePlayer.exe").is_file():
        raise RuntimeError("Staged update is missing CadrePlayer.exe.")
    if find_internal_dir(payload_root) is None:
        raise RuntimeError("Staged update is missing internal runtime files.")


def _is_under(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    root = root.resolve()
    return resolved == root or root in resolved.parents


def assert_allowed_target(path: Path, install_dir: Path) -> None:
    resolved = path.resolve()
    allowed = {
        (install_dir / "CadrePlayer.exe").resolve(),
        (install_dir / "internal").resolve(),
        (install_dir / "_internal").resolve(),
    }
    if resolved not in allowed:
        raise RuntimeError(f"Refusing to modify unexpected path: {resolved}")
    for user_dir in user_data_dirs():
        if _is_under(resolved, user_dir):
            raise RuntimeError("Refusing to modify CadrePlayer user data.")


def get_target_names(payload_root: Path, install_dir: Path) -> list[str]:
    names = ["CadrePlayer.exe"]
    for root in (payload_root, install_dir):
        for candidate in ("_internal", "internal"):
            if (root / candidate).is_dir() and candidate not in names:
                names.append(candidate)
    if not any(n in ("_internal", "internal") for n in names):
        names.append("_internal")
    return names


def retry(action, description: str) -> None:
    last = None
    for attempt in range(RETRY_COUNT):
        try:
            action()
            return
        except OSError as exc:
            last = exc
            logging.warning("%s failed on attempt %s: %s", description, attempt + 1, exc)
            time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"{description} failed: {last}")


def safe_move_path(src: Path, dst: Path) -> None:
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    if not src.exists():
        return

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Clean destination if it already exists to prevent shutil.move from nesting src inside dst
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
        else:
            try:
                dst.unlink()
            except OSError:
                pass

    try:
        os.replace(src, dst)
        return
    except OSError:
        pass

    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
        else:
            try:
                dst.unlink()
            except OSError:
                pass

    shutil.move(str(src), str(dst))


def move_existing_to_backup(install_dir: Path, backup_dir: Path, target_names: list[str]) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in target_names:
        src = install_dir / name
        dst = backup_dir / name
        assert_allowed_target(src, install_dir)
        if not src.exists():
            continue
        retry(lambda s=src, d=dst: safe_move_path(s, d), f"Backing up {name}")


def install_from_staging(payload_root: Path, install_dir: Path, target_names: list[str]) -> None:
    for name in target_names:
        src = payload_root / name
        dst = install_dir / name
        if not src.exists():
            continue
        assert_allowed_target(dst, install_dir)
        retry(lambda s=src, d=dst: safe_move_path(s, d), f"Installing {name}")


def restore_backup(backup_dir: Path, install_dir: Path, target_names: list[str]) -> None:
    for name in target_names:
        dst = install_dir / name
        src = backup_dir / name
        assert_allowed_target(dst, install_dir)
        if src.exists():
            retry(lambda s=src, d=dst: safe_move_path(s, d), f"Restoring {name}")


def run_update(args) -> None:
    install_dir = Path(args.install_dir).resolve()
    zip_path = Path(args.zip).resolve()
    restart_exe = Path(args.restart_exe).resolve()
    version = str(args.version or "unknown").strip() or "unknown"

    validate_install_dir(install_dir)
    if not zip_path.is_file():
        raise RuntimeError("Verified update ZIP was not found.")
    if restart_exe != (install_dir / "CadrePlayer.exe").resolve():
        raise RuntimeError("Restart executable is outside the portable install folder.")

    wait_for_pid(int(args.pid))

    work_root = Path(tempfile.gettempdir()) / "CadrePlayer" / "updates"
    work_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f"stage-{version}-", dir=str(work_root)))
    backup_dir = work_root / f"backup-{version}"

    try:
        extract_zip_safely(zip_path, staging_dir)
        payload_root = find_payload_root(staging_dir)
        validate_staging(payload_root)
        target_names = get_target_names(payload_root, install_dir)
        move_existing_to_backup(install_dir, backup_dir, target_names)
        try:
            install_from_staging(payload_root, install_dir, target_names)
        except Exception:
            logging.exception("Install failed; attempting rollback")
            restore_backup(backup_dir, install_dir, target_names)
            raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        shutil.rmtree(backup_dir, ignore_errors=True)
    except OSError:
        pass

    subprocess.Popen([str(restart_exe)], cwd=str(install_dir), close_fds=True)


def relocate_if_needed(args, argv: list[str]) -> bool:
    if "--self-relocated" in argv:
        return False

    current_exe = Path(sys.executable).resolve()
    install_dir = Path(args.install_dir).resolve()

    if not _is_under(current_exe, install_dir):
        return False

    logging.info("Relocating updater from %s to %%TEMP%% to prevent DLL file locks", current_exe)
    runner_dir = Path(tempfile.gettempdir()) / "CadrePlayer" / "updater_runner"
    try:
        shutil.rmtree(runner_dir, ignore_errors=True)
    except Exception:
        pass
    runner_dir.mkdir(parents=True, exist_ok=True)

    for item in install_dir.iterdir():
        if item.name.startswith("CadrePlayerUpdater") or item.name in ("_internal", "internal"):
            dst = runner_dir / item.name
            try:
                if item.is_dir():
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)
            except Exception as e:
                logging.warning("Failed copying %s to runner_dir: %s", item, e)

    temp_updater_exe = runner_dir / current_exe.name
    if not temp_updater_exe.is_file():
        temp_updater_exe = runner_dir / "CadrePlayerUpdater.exe"

    if not temp_updater_exe.is_file():
        logging.warning("Could not find relocated updater executable at %s", temp_updater_exe)
        return False

    cmd = [str(temp_updater_exe)] + argv + ["--self-relocated"]
    subprocess.Popen(cmd, cwd=str(install_dir), close_fds=True)
    return True


def parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description="CadrePlayer updater")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--restart-exe", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--self-relocated", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    try:
        raw_argv = sys.argv[1:] if argv is None else argv
        args = parse_args(raw_argv)
        if relocate_if_needed(args, raw_argv):
            logging.info("Relocated updater spawned from %%TEMP%%; initial process exiting cleanly.")
            return 0
        logging.info("Updater started for version=%s install_dir=%s", args.version, args.install_dir)
        run_update(args)
        logging.info("Updater completed")
        return 0
    except Exception as exc:
        logging.exception("Updater failed")
        message_box(
            "CadrePlayer Update Failed",
            str(exc)
            + "\n\nCadrePlayer could not install the update. "
            "If it is in Program Files or another protected folder, move it to Downloads/Documents or run it as administrator.",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
