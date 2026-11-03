# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on Google MediaPipe hand landmarks; NumPy. Full credits: CREDITS.md

"""Calibration wizard: hold each sign for 2 seconds and the app fits the thresholds to your hands.

For every finger it collects how bent it is while it should be UP and while it should be DOWN,
then puts the two thresholds inside the gap between those readings (separately for each finger
and each hand). The thumb is calibrated the same way when the Extended signs are included.
Afterwards every collected frame is re-checked with the new thresholds, so you can see how
reliably each sign will be read before you save.
"""

import numpy as np

from gestures import CURLED_MIN_CURL, EXTENDED_MAX_CURL, FINGER_NAMES, SIGN_SETS, THUMB_IN_MAX, THUMB_OUT_MIN

GET_READY = 1.5      # seconds to form the sign
HOLD = 2.0           # seconds of samples per sign
MIN_FRAMES = 12      # per sign and hand, or that hand's step is reported as missing
MIN_GAP = 20         # degrees; a smaller gap between up and down readings is flagged
FIST = ("fist", (0, 0, 0, 0), False)


def steps_for(sign_set):
    """Fist first (everything down), then every sign of the set."""
    return [FIST] + list(SIGN_SETS[sign_set])


class Calibrator:
    def __init__(self, sign_set, now):
        self.sign_set = sign_set
        self.steps = steps_for(sign_set)
        self.index, self.phase, self.phase_start = 0, "ready", now
        # samples[hand][step] = list of (curls[4], thumb_ratio)
        self.samples = {h: [[] for _ in self.steps] for h in ("L", "R")}
        self.result = None

    @property
    def done(self):
        return self.phase == "done"

    @property
    def step(self):
        return self.steps[min(self.index, len(self.steps) - 1)]

    def progress(self, now):
        """Fraction of the current phase that has passed (for the countdown ring)."""
        length = GET_READY if self.phase == "ready" else HOLD
        return min(1.0, (now - self.phase_start) / length)

    def frames(self, hand):
        return len(self.samples[hand][min(self.index, len(self.steps) - 1)])

    def update(self, now, states):
        """Call every frame. states: {hand: HandState} for the hands seen this frame."""
        if self.done:
            return
        if self.phase == "ready" and now - self.phase_start >= GET_READY:
            self.phase, self.phase_start = "hold", now
        elif self.phase == "hold":
            for hand, state in states.items():
                self.samples[hand][self.index].append((list(state.curls), state.thumb_ratio))
            if now - self.phase_start >= HOLD:
                self.index += 1
                if self.index >= len(self.steps):
                    self.phase = "done"
                    self.result = compute(self.steps, self.samples)
                else:
                    self.phase, self.phase_start = "ready", now

    def skip(self, now):
        """Skip the current sign (e.g. one you can't make); it simply contributes no samples."""
        self.phase, self.phase_start = "hold", now - HOLD


def _fit(up, down, default_low, default_high, min_gap, low_clamp, high_clamp):
    """Two thresholds with a keep-state zone between them, from 'up' and 'down' readings.

    Returns (low, high, report). low: below it counts as up; high: above it counts as down.
    """
    if len(up) < MIN_FRAMES or len(down) < MIN_FRAMES:
        return default_low, default_high, {"ok": False, "why": "not enough frames", "up": None, "down": None}
    up_hi, down_lo = float(np.percentile(up, 95)), float(np.percentile(down, 5))
    gap = down_lo - up_hi
    if gap >= min_gap:
        low, high = up_hi + 0.3 * gap, down_lo - 0.3 * gap   # keep-state zone: the middle 40% of the gap
        ok, why = True, ""
    else:
        mid = (up_hi + down_lo) / 2
        low, high = mid - min_gap / 4, mid + min_gap / 4
        ok, why = False, "up and down readings overlap"
    low = float(np.clip(low, *low_clamp))
    high = float(np.clip(max(high, low + min_gap / 2), *high_clamp))
    return low, high, {"ok": ok, "why": why, "up": (float(np.min(up)), up_hi), "down": (down_lo, float(np.max(down)))}


def compute(steps, samples):
    """Thresholds and a report for each hand that was seen."""
    out = {}
    for hand in ("L", "R"):
        if sum(len(s) for s in samples[hand]) < MIN_FRAMES * 2:
            continue
        ext_max, curl_min, fingers = [], [], []
        for f in range(4):
            up = [c[f] for i, (_, pat, _) in enumerate(steps) if pat[f] for c, _ in samples[hand][i]]
            down = [c[f] for i, (_, pat, _) in enumerate(steps) if not pat[f] for c, _ in samples[hand][i]]
            low, high, rep = _fit(up, down, EXTENDED_MAX_CURL, CURLED_MIN_CURL, MIN_GAP, (20, 180), (40, 230))
            ext_max.append(round(low, 1))
            curl_min.append(round(high, 1))
            fingers.append({"name": FINGER_NAMES[f], "ext_max": low, "curl_min": high, **rep})

        # Thumb: only the Extended signs say clearly where it should be
        thumb_out = [r for i, (_, _, th) in enumerate(steps) if th is True for _, r in samples[hand][i]]
        thumb_in = [r for i, (_, _, th) in enumerate(steps) if th is False for _, r in samples[hand][i]]
        t_low, t_high, t_rep = _fit([-r for r in thumb_out], [-r for r in thumb_in], -THUMB_OUT_MIN, -THUMB_IN_MAX,
                                    0.08, (-3, 0), (-3, 0)) if thumb_out else (-THUMB_OUT_MIN, -THUMB_IN_MAX, None)
        cal = {"ext_max": ext_max, "curl_min": curl_min,
               "thumb_out_min": round(-t_low, 3), "thumb_in_max": round(-t_high, 3)}
        out[hand] = {"thresholds": cal, "fingers": fingers, "thumb": t_rep,
                     "steps": _step_scores(steps, samples[hand], cal)}
    return out


def _step_scores(steps, hand_samples, cal):
    """Share of each sign's frames that the new thresholds read correctly (fingers only)."""
    scores = []
    for (name, pattern, _), frames in zip(steps, hand_samples):
        if not frames:
            scores.append((name, None))
            continue
        good = 0
        for curls, _ in frames:
            up = [c < cal["ext_max"][f] for f, c in enumerate(curls)]
            down = [c > cal["curl_min"][f] for f, c in enumerate(curls)]
            good += all((u if pattern[f] else d) for f, (u, d) in enumerate(zip(up, down)))
        scores.append((name, good / len(frames)))
    return scores
