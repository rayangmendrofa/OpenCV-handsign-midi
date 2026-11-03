# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on the Python standard library. Full credits: CREDITS.md

"""Remembers your choices between sessions in settings.json (instruments, key mapping, display...).

Unknown or invalid values in the file are ignored, so a hand-edited or older file never stops
the app from starting.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"


def _note(midi):
    return {"kind": "note", "midi": midi}


# Custom mode starts as a two-octave keyboard: left hand C3-C4, right hand C4-C5 (C major)
_C_MAJOR = [0, 2, 4, 5, 7, 9, 11, 12]
DEFAULT_CUSTOM_PADS = {
    "L": [_note(48 + s) for s in _C_MAJOR],
    "R": [_note(60 + s) for s in _C_MAJOR],
}

DEFAULTS = {
    "mode": "Notes",
    "scale": "Major",
    "root": 60,
    "sign_set": "Basic",
    "style": "Signs",
    "expression": "Off",
    "instruments": {"L": "Piano", "R": "Piano"},
    "custom_pads": DEFAULT_CUSTOM_PADS,
    "stage_color": 0,
    "stage_view": 0,
    "trails": True,
    "camera_skeleton": True,
    "background": "Colour",                  # camera backdrop: Colour, Blur or Off
    "game_offset_ms": 0,
    "calibration": {},                       # per hand: thresholds from the calibration wizard
    "hand_volume": {"L": 1.0, "R": 1.0},     # mixer
    "hand_reverb": {"L": 0.15, "R": 0.15},
    "dynamics": True,                        # strike speed sets loudness
    "loop_bpm": 100.0,
    "metronome": False,
    "count_in": True,
    "quantise": "Off",
}


def _valid_calibration(cal):
    """{hand: {"ext_max": [4 numbers], "curl_min": [4 numbers], "thumb_out_min": n, "thumb_in_max": n}}"""
    if not isinstance(cal, dict):
        return {}
    out = {}
    for hand, c in cal.items():
        try:
            if hand in ("L", "R") and all(len(c[k]) == 4 for k in ("ext_max", "curl_min")):
                out[hand] = {"ext_max": [float(v) for v in c["ext_max"]],
                             "curl_min": [float(v) for v in c["curl_min"]],
                             "thumb_out_min": float(c["thumb_out_min"]), "thumb_in_max": float(c["thumb_in_max"])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _valid_pad(pad):
    if pad is None:
        return True
    if not isinstance(pad, dict):
        return False
    kind = pad.get("kind")
    if kind == "note":
        return isinstance(pad.get("midi"), int) and 0 <= pad["midi"] <= 127
    if kind in ("chord", "drum"):
        return isinstance(pad.get("name"), str)
    return False


def load():
    data = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(saved, dict):
        return data
    for key, default in DEFAULTS.items():
        value = saved.get(key)
        if value is None:
            continue
        if key == "custom_pads":
            for hand in ("L", "R"):
                pads = value.get(hand) if isinstance(value, dict) else None
                if isinstance(pads, list):
                    pads = (pads + [None] * 8)[:8]
                    data[key][hand] = [p if _valid_pad(p) else None for p in pads]
        elif key == "instruments":
            if isinstance(value, dict):
                data[key].update({h: v for h, v in value.items() if h in ("L", "R") and isinstance(v, str)})
        elif key == "calibration":
            data[key] = _valid_calibration(value)
        elif key in ("hand_volume", "hand_reverb"):
            if isinstance(value, dict):
                data[key].update({h: min(1.0, max(0.0, float(v))) for h, v in value.items()
                                  if h in ("L", "R") and isinstance(v, (int, float)) and not isinstance(v, bool)})
        elif isinstance(default, bool):
            if isinstance(value, bool):
                data[key] = value
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                data[key] = type(default)(value)
        elif isinstance(value, type(default)):
            data[key] = value
    return data


# ---------------------------------------------------------------- key-mapping presets
# Each preset is a small JSON file in mappings/, so presets can be shared, backed up or imported.
MAPPINGS_DIR = Path(__file__).parent / "mappings"


def _preset_path(name):
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "preset"
    return MAPPINGS_DIR / f"{safe}.json"


def list_presets():
    return sorted(p.stem for p in MAPPINGS_DIR.glob("*.json")) if MAPPINGS_DIR.exists() else []


def read_preset(path):
    """{"L": [8 pads], "R": [8 pads]} from a preset file, or ValueError."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        pads = data["pads"]
        out = {h: ([p if _valid_pad(p) else None for p in pads[h]] + [None] * 8)[:8] for h in ("L", "R")}
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(f"{Path(path).name} isn't a Gesture Music key mapping")
    return out


def write_preset(name, pads, path=None):
    MAPPINGS_DIR.mkdir(exist_ok=True)
    path = Path(path) if path else _preset_path(name)
    path.write_text(json.dumps({"format": "gesture-music-mapping", "version": 1, "name": name,
                                "pads": {h: list(pads[h]) for h in ("L", "R")}}, indent=2), encoding="utf-8")
    return path


def load_preset(name):
    return read_preset(_preset_path(name))


def delete_preset(name):
    _preset_path(name).unlink(missing_ok=True)


def save(data):
    try:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_PATH)  # write-then-rename, so a crash never leaves half a file
    except OSError as e:
        print(f"Couldn't save settings: {e}")
