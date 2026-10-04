"""Close Chromium launched by the old, unsupervised PicoChess kiosk script."""

import os
from pathlib import Path
import signal
import shlex
import sys
from urllib.parse import urlsplit


def configured_kiosk_port(config_path: Path = Path("/opt/picochess/picochess.ini")) -> int | None:
    """Read the legacy launcher's web-server setting; skip cleanup if unknown."""
    try:
        value = ""
        for line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, setting = line.partition("=")
            if separator and key.strip() == "web-server":
                value = setting.split("#", 1)[0].strip()
        port = int(value)
        return port if 1 <= port <= 65535 else None
    except (OSError, ValueError):
        return None


def is_legacy_kiosk_command(args: list[str], web_port: int, *, allow_windowed: bool = False) -> bool:
    if not args or Path(args[0]).name not in ("chromium", "chromium-browser"):
        return False
    if ("--kiosk" not in args and not allow_windowed) or any(arg.startswith("--user-data-dir") for arg in args):
        return False
    if "--password-store=basic" not in args or not 1 <= web_port <= 65535:
        return False
    urls = [arg for arg in args if arg.startswith(("http://", "https://"))]
    if len(urls) != 1:
        return False
    try:
        url = urlsplit(urls[0])
        return (
            url.scheme == "http"
            and url.hostname in ("127.0.0.1", "localhost")
            and (url.port if url.port is not None else 80) == web_port
            and url.path in ("", "/")
            and not url.query
            and not url.fragment
            and url.username is None
            and url.password is None
        )
    except ValueError:
        return False


def has_legacy_windowed_launcher(home: Path, web_port: int) -> bool:
    """Recognize the old Wayland launch line, which deliberately omitted --kiosk."""
    try:
        script = (home / "kiosk.sh").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    # Supervised launchers own their browser; never take over their cleanup.
    if "--user-data-dir" in script or "monitor_kiosk_browser" in script:
        return False
    for line in script.replace("\\\n", " ").splitlines():
        try:
            args = shlex.split(line, comments=True)
        except ValueError:
            continue
        if (
            len(args) == 4
            and args[1] == "--password-store=basic"
            and args[-1] == "&"
            and is_legacy_kiosk_command(args[:-1], web_port, allow_windowed=True)
        ):
            return True
    return False


def stop_legacy_kiosk(proc_root: Path = Path("/proc"), *, web_port: int | None = None) -> None:
    """Terminate only local PicoChess kiosks from the pre-supervisor launcher."""
    if not sys.platform.startswith("linux"):
        return
    if web_port is None:
        web_port = configured_kiosk_port()
    if web_port is None or not 1 <= web_port <= 65535:
        return
    target_uid = os.getuid()
    import pwd

    if target_uid == 0:
        sudo_user = os.environ.get("SUDO_USER")
        if not sudo_user:
            return
        try:
            target_uid = pwd.getpwnam(sudo_user).pw_uid
        except KeyError:
            return
    try:
        home = Path(pwd.getpwuid(target_uid).pw_dir)
        allow_windowed = has_legacy_windowed_launcher(home, web_port)
    except KeyError:
        allow_windowed = False
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
            if is_legacy_kiosk_command(args, web_port, allow_windowed=allow_windowed):
                os.kill(int(entry.name), signal.SIGTERM)
        except (OSError, ValueError):
            continue  # The process may have exited while /proc was scanned.


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-port", type=int)
    stop_legacy_kiosk(web_port=parser.parse_args().web_port)
