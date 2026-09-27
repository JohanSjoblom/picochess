"""Close Chromium launched by the old, unsupervised PicoChess kiosk script."""

import os
from pathlib import Path
import signal
import sys
from urllib.parse import urlsplit


def is_legacy_kiosk_command(args: list[str]) -> bool:
    if not args or Path(args[0]).name not in ("chromium", "chromium-browser"):
        return False
    if "--kiosk" not in args or any(arg.startswith("--user-data-dir") for arg in args):
        return False
    return any(
        urlsplit(arg).scheme == "http"
        and urlsplit(arg).hostname in ("127.0.0.1", "localhost")
        for arg in args
    )


def stop_legacy_kiosk(proc_root: Path = Path("/proc")) -> None:
    """Terminate only local PicoChess kiosks from the pre-supervisor launcher."""
    if not sys.platform.startswith("linux"):
        return
    target_uid = os.getuid()
    if target_uid == 0:
        sudo_user = os.environ.get("SUDO_USER")
        if not sudo_user:
            return
        import pwd

        try:
            target_uid = pwd.getpwnam(sudo_user).pw_uid
        except KeyError:
            return
    try:
        processes = list(proc_root.iterdir())
    except OSError:
        return  # Kiosk cleanup must not prevent the remaining shutdown steps.
    for entry in processes:
        if not entry.name.isdecimal():
            continue
        try:
            if entry.stat().st_uid != target_uid:
                continue
            args = (entry / "cmdline").read_bytes().decode(errors="replace").strip("\0").split("\0")
            if is_legacy_kiosk_command(args):
                os.kill(int(entry.name), signal.SIGTERM)
        except (OSError, ValueError):
            continue  # The process may have exited while /proc was scanned.


if __name__ == "__main__":
    stop_legacy_kiosk()
