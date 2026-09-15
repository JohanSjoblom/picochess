"""System audio volume control for PipeWire and legacy ALSA systems."""

import logging
import shutil
import subprocess


logger = logging.getLogger(__name__)

ALSA_VOLUME_CHANNELS = ("Headphone", "Master", "HDMI", "PCM")
VOLUME_COMMAND_TIMEOUT = 3.0


def set_system_volume(volume_factor: int) -> bool:
    """Apply PicoChess's 0..20 voice-volume factor to the active output."""
    bounded_factor = max(0, min(20, int(volume_factor)))
    percent = bounded_factor * 5

    if shutil.which("wpctl"):
        result = _run_volume_command(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"],
            "PipeWire default sink",
        )
        if result:
            return True

    applied = False
    for channel in ALSA_VOLUME_CHANNELS:
        applied = (
            _run_volume_command(
                ["amixer", "-M", "sset", channel, f"{percent}%"],
                f"ALSA {channel}",
            )
            or applied
        )
    return applied


def _run_volume_command(command: list[str], target: str) -> bool:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=VOLUME_COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("volume control unavailable for %s: %s", target, exc)
        return False

    if result.returncode == 0:
        logger.debug("volume applied to %s", target)
        return True

    error = (result.stderr or result.stdout or "unknown error").strip()
    logger.debug("volume control failed for %s: %s", target, error)
    return False
