# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on handmodel.py; NumPy. Full credits: CREDITS.md

"""Generate sessions/demo.gmsession: a 20-second synthetic two-hand performance for --demo.

Run from the project folder:  .venv/Scripts/python tools/make_demo_session.py

The hands are the synthetic model from handmodel.py, so the demo works without a camera.
At 96 BPM in Band mode it plays C - G - Am - F on the right hand (1, 3, 4, 2 fingers, two beats
each) while the left hand alternates kick and snare (1 and 2 fingers), adds finger taps in the
second half, and both hands sway so the stage trails show movement. Every motion has a period
that divides 20 s, so the loop is seamless.
"""

import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import handmodel as hm  # noqa: E402
from gestures import SIGN_SETS  # noqa: E402
from session import SESSIONS_DIR, _points  # noqa: E402

FPS, BPM, BEATS = 30, 96, 32
BEAT = 60 / BPM
RIGHT = [0, 2, 3, 1]          # 1, 3, 4, 2 fingers: C G Am F in Band mode
MORPH = 0.12                  # seconds for fingers to move between signs


def fold_at(t, sequence, beats_per_sign, taps=False):
    """Per-finger curl (0 up, 1 down) at time t, morphing smoothly between signs."""
    k = int(t / (BEAT * beats_per_sign))
    since = t - k * BEAT * beats_per_sign
    cur = SIGN_SETS["Basic"][sequence[k % len(sequence)]]
    prev = SIGN_SETS["Basic"][sequence[(k - 1) % len(sequence)]]
    a = min(1.0, since / MORPH)
    fold = [(1 - a) * (0.0 if prev[1][f] else 1.0) + a * (0.0 if cur[1][f] else 1.0) for f in range(4)]
    if taps and BEAT * 0.5 < since < BEAT * 0.5 + 0.2:  # a finger tap halfway through the sign
        dip = math.sin(math.pi * (since - BEAT * 0.5) / 0.2) * 0.55
        fold = [min(1.0, x + dip) if cur[1][f] else x for f, x in enumerate(fold)]
    return cur, fold, since


def main():
    SESSIONS_DIR.mkdir(exist_ok=True)
    path = SESSIONS_DIR / "demo.gmsession"
    length = BEATS * BEAT
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"format": "gesture-music-session", "version": 1, "created": "generated",
                            "note": "Synthetic demo: Band mode at 96 BPM (tools/make_demo_session.py)"}) + "\n")
        for i in range(int(length * FPS)):
            t = i / FPS
            hands = []
            for hand, seq, per_sign, base in (("R", RIGHT, 2, (0.70, 0.58)), ("L", [0, 1], 1, (0.30, 0.62))):
                sign, fold, since = fold_at(t, seq, per_sign, taps=(hand == "L" and t > length / 2))
                strike = 0.025 * math.exp(-since / 0.08)          # a small downward strike on each new sign
                sway_x = 0.035 * math.sin(2 * math.pi * t / 5.0 + (0 if hand == "R" else 1.5))
                sway_y = 0.025 * math.sin(2 * math.pi * t / 2.5 + (0.7 if hand == "R" else 0))
                screen, world = hm.landmarks(sign[1], sign[2], hand, center=(base[0] + sway_x, base[1] + sway_y + strike),
                                             fold=fold, yaw=8 * math.sin(2 * math.pi * t / 10))
                hands.append({"hand": hand, "lm": _points(screen), "world": _points(world)})
            f.write(json.dumps({"t": round(t, 4), "hands": hands}, separators=(",", ":")) + "\n")
    print(f"Wrote {path} ({length:.0f} s, {int(length * FPS)} frames)")


if __name__ == "__main__":
    main()
