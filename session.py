# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on Google MediaPipe hand landmarks (stored, not images); the Python standard library. Full credits: CREDITS.md

"""Record and replay hand sessions: the tracked landmarks of both hands over time.

Only landmarks are stored (no camera images), as gzip-compressed JSON lines, roughly 1-2 MB per
minute. A replay feeds the same data through the app as the live camera would, so it can be used
for debugging, for automated tests, and as a demo that runs without a camera.

File format (.gmsession):
  line 1: {"format": "gesture-music-session", "version": 1, "created": "...", "note": "..."}
  then one line per frame: {"t": seconds, "hands": [{"hand": "L", "lm": [[x, y, z] x 21], "world": [...]}]}
"""

import gzip
import json
import time
from pathlib import Path
from types import SimpleNamespace

SESSIONS_DIR = Path(__file__).parent / "sessions"
SUFFIX = ".gmsession"


def _points(lms):
    return [[round(p.x, 5), round(p.y, 5), round(p.z, 5)] for p in lms]


def _landmarks(rows):
    return [SimpleNamespace(x=x, y=y, z=z) for x, y, z in rows]


class SessionRecorder:
    def __init__(self):
        self.file = None

    @property
    def active(self):
        return self.file is not None

    def start(self, note=""):
        SESSIONS_DIR.mkdir(exist_ok=True)
        self.path = SESSIONS_DIR / f"session-{time.strftime('%Y%m%d-%H%M%S')}{SUFFIX}"
        self.file = gzip.open(self.path, "wt", encoding="utf-8")
        self.file.write(json.dumps({"format": "gesture-music-session", "version": 1,
                                    "created": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note}) + "\n")
        self.t0, self.frames = None, 0

    def add(self, stamp, detections):
        """detections: [(hand, landmarks, world landmarks)], as given to App.process()."""
        if self.t0 is None:
            self.t0 = stamp
        hands = [{"hand": h, "lm": _points(lm), "world": _points(w)} for h, lm, w in detections]
        self.file.write(json.dumps({"t": round(stamp - self.t0, 4), "hands": hands}, separators=(",", ":")) + "\n")
        self.frames += 1

    def stop(self):
        seconds = 0.0
        if self.file:
            self.file.close()
            self.file = None
            seconds = load(self.path)[-1][0] if self.frames else 0.0
        return self.path, self.frames, seconds


def load(path):
    """[(t, [(hand, landmarks, world)])] from a session file."""
    frames = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        header = json.loads(f.readline())
        if header.get("format") != "gesture-music-session":
            raise ValueError(f"{Path(path).name} isn't a Gesture Music session")
        for line in f:
            row = json.loads(line)
            frames.append((row["t"], [(h["hand"], _landmarks(h["lm"]), _landmarks(h["world"])) for h in row["hands"]]))
    if not frames:
        raise ValueError(f"{Path(path).name} has no frames")
    return frames


def list_sessions():
    return sorted(SESSIONS_DIR.glob("*" + SUFFIX), key=lambda p: p.stat().st_mtime, reverse=True)


class SessionPlayer:
    """Plays a session back in real time, looping, one frame per call to read()."""

    def __init__(self, path, loop=True):
        self.path, self.loop = Path(path), loop
        self.frames = load(path)
        self.length = self.frames[-1][0]
        self.index, self.start = 0, None

    @property
    def position(self):
        return self.frames[min(self.index, len(self.frames) - 1)][0]

    def read(self):
        """Wait until the next frame is due, then return (stamp, detections); None when finished."""
        if self.start is None:
            self.start = time.perf_counter()
        if self.index >= len(self.frames):
            if not self.loop:
                return None
            self.index, self.start = 0, time.perf_counter() + 0.05
        t, detections = self.frames[self.index]
        due = self.start + t
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(min(wait, 0.2))
        self.index += 1
        return max(due, time.perf_counter() - 0.001), detections
