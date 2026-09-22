"""Platform-specific naming for local PicoChess engine resources."""

from pathlib import Path
import platform


def engine_platform_name(system_name: str | None = None, machine: str | None = None) -> str:
    """Return the folder name used for engines on the current platform.

    Intel macOS and Linux both report ``x86_64``. Keep the established Linux
    folder name and give Intel macOS its own catalog so binaries cannot be
    mixed accidentally.
    """

    resolved_system = platform.system() if system_name is None else system_name
    resolved_machine = platform.machine() if machine is None else machine
    if resolved_system == "Darwin" and resolved_machine.lower() == "x86_64":
        return "mac_x86_64"
    return resolved_machine


def local_engine_directory() -> Path:
    """Return this checkout's platform-specific engine directory."""

    return Path(__file__).resolve().parent.parent / "engines" / engine_platform_name()
