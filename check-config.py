#!/usr/bin/env python3
import sys
from pathlib import Path

try:
    from configobj import ConfigObj
except Exception:
    ConfigObj = None


def normalize_value(value: str) -> str:
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    if v.startswith("(") and v.endswith(")"):
        v = v[1:-1]
    return v.strip()


def get_value(cfg, key):
    if cfg is None:
        return None
    if key not in cfg:
        return None
    value = cfg.get(key)
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    return normalize_value(str(value))


def main(argv):
    config_path = Path(argv[1]) if len(argv) > 1 else Path("/opt/picochess/picochess.ini")
    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        return 2
    if ConfigObj is None:
        print("ERROR: python module 'configobj' not available.")
        return 2

    cfg = ConfigObj(str(config_path), encoding="utf-8")
    errors = []

    beep_config = get_value(cfg, "beep-config")
    if beep_config:
        allowed = {"none", "some", "all", "sample"}
        aliases = {
            "never": "none",
            "sometimes": "some",
            "always": "all",
        }
        v = beep_config.lower()
        v = aliases.get(v, v)
        if v not in allowed:
            errors.append(
                f"beep-config='{beep_config}' is invalid. Allowed: none, some, all, sample."
            )

    audio_backend = get_value(cfg, "audio-backend")
    if audio_backend:
        if audio_backend.lower() not in {"sox", "native"}:
            errors.append(
                f"audio-backend='{audio_backend}' is invalid. Allowed: sox, native."
            )

    def check_int_range(key, min_value, max_value):
        val = get_value(cfg, key)
        if val is None or val == "":
            return
        try:
            num = int(val, 0)
        except ValueError:
            errors.append(f"{key}='{val}' is not a valid integer.")
            return
        if num < min_value or num > max_value:
            errors.append(f"{key}={num} out of range ({min_value}-{max_value}).")

    check_int_range("beep-some-level", 0, 15)
    check_int_range("speed-voice", 0, 9)
    check_int_range("volume-voice", 0, 20)

    board_type = get_value(cfg, "board-type")
    if board_type:
        allowed = {"dgt", "certabo", "chesslink", "chessnut", "ichessone", "noeboard"}
        if board_type.lower() not in allowed:
            errors.append(
                f"board-type='{board_type}' is invalid. Allowed: {', '.join(sorted(allowed))}."
            )

    theme = get_value(cfg, "theme")
    if theme is not None:
        if theme == "":
            pass
        else:
            allowed = {"light", "dark", "time", "auto"}
            if theme.lower() not in allowed:
                errors.append(
                    f"theme='{theme}' is invalid. Allowed: light, dark, time, auto, or blank."
                )

    if errors:
        print("Config check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Config check OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
