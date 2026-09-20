"""System audio volume control for PipeWire and legacy ALSA systems."""

import logging
import shutil
import subprocess
import threading
from typing import Callable, Optional


logger = logging.getLogger(__name__)

ALSA_VOLUME_CHANNELS = ("Headphone", "Master", "HDMI", "PCM")
VOLUME_COMMAND_TIMEOUT = 3.0

_volume_request_lock = threading.Lock()
_volume_apply_lock = threading.Lock()
_volume_request_sequence = 0
_latest_volume_request = None


def set_system_volume(
    volume_factor: int,
    audio_backend: str = "sox",
    volume_factor_getter: Optional[Callable[[], int]] = None,
) -> bool:
    """Apply the newest requested volume, serializing concurrent callers."""
    bounded_factor = max(0, min(20, int(volume_factor)))
    backend = (audio_backend or "sox").lower()

    global _volume_request_sequence, _latest_volume_request
    with _volume_request_lock:
        _volume_request_sequence += 1
        request = (_volume_request_sequence, bounded_factor, backend, volume_factor_getter)
        _latest_volume_request = request

    # Every writer uses this lock. If a newer request arrives while a command
    # is running, reconcile it before releasing the lock so an older request
    # can never be the last value applied.
    with _volume_apply_lock:
        while True:
            with _volume_request_lock:
                target = _latest_volume_request
            _, requested_factor, target_backend, target_getter = target
            target_factor = requested_factor
            if target_getter is not None:
                try:
                    target_factor = max(0, min(20, int(target_getter())))
                except (TypeError, ValueError):
                    logger.warning("invalid committed voice volume; using requested value %s", requested_factor)
            applied = _apply_system_volume(target_factor * 5, target_backend)
            with _volume_request_lock:
                if target == _latest_volume_request:
                    return applied


def _apply_system_volume(percent: int, audio_backend: str) -> bool:
    """Apply one serialized request and report whether its output route is ready."""
    wpctl_available = bool(shutil.which("wpctl"))

    if audio_backend == "native":
        if wpctl_available:
            pipewire_applied = _set_pipewire_volume(percent)
            if pipewire_applied:
                return True
            # This may control a direct ALSA device, but it does not prove the
            # native PipeWire route is ready. Return False so playback retries.
            _set_alsa_volume(percent)
            return False
        return _set_alsa_volume(percent)

    # SoX may use ALSA directly or through PipeWire, so cover both routes. If
    # wpctl exists, require that route to be ready before declaring success;
    # otherwise an unrelated hardware mixer could suppress the needed retry.
    alsa_applied = _set_alsa_volume(percent)
    if wpctl_available:
        return _set_pipewire_volume(percent)
    return alsa_applied


def _set_pipewire_volume(percent: int) -> bool:
    return _run_volume_command(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"],
        "PipeWire default sink",
    )


def _set_alsa_volume(percent: int) -> bool:
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
