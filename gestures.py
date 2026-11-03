# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on Google MediaPipe hand landmarks; One Euro filter after Casiez, Roussel & Vogel (CHI 2012). Full credits: CREDITS.md

"""Turns hand landmarks into musical intent: hand signs or pinches, and hand-height expression."""

import math

import numpy as np

# Landmark indices (see MediaPipe hand model)
WRIST, THUMB_TIP, MIDDLE_MCP = 0, 4, 9
FINGERTIPS = [8, 12, 16, 20]  # index, middle, ring, pinky
FINGER_NAMES = ["index", "middle", "ring", "pinky"]
FINGER_JOINTS = [(5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)]  # MCP, PIP, DIP, tip

GESTURE_STYLES = ["Signs", "Pinch"]

# ---- Hand signs ----
# A finger's "curl" is how much it bends at its three joints, in degrees (0 = straight).
# Between the two thresholds the finger keeps its previous state, so a half-bent
# finger can't flicker between up and down.
# A straight finger measures about 30-60 degrees (the knuckle sits at an angle to the wrist,
# plus tracking noise); a fist about 200-220.
EXTENDED_MAX_CURL = 90
CURLED_MIN_CURL = 140
REST = -1  # fist: silence
CONFIRM_FRAMES = 2  # a new sign must be seen this many frames in a row before it plays

# Each sign: (name, fingers up as index/middle/ring/pinky, thumb). thumb: True = out,
# False = tucked in, None = ignored. The thumb is the hardest finger for the camera to
# read, so only two pairs depend on it: 4 fingers vs open hand, fist vs thumbs up.
SIGN_SETS = {
    "Basic": [
        ("1 finger", (1, 0, 0, 0), None),
        ("2 fingers", (1, 1, 0, 0), None),
        ("3 fingers", (1, 1, 1, 0), None),
        ("4 fingers", (1, 1, 1, 1), None),
    ],
    "Extended": [
        ("1 finger", (1, 0, 0, 0), None),
        ("2 fingers", (1, 1, 0, 0), None),
        ("3 fingers", (1, 1, 1, 0), None),
        ("4 fingers", (1, 1, 1, 1), False),   # thumb tucked across the palm
        ("open hand", (1, 1, 1, 1), True),    # all five spread
        ("thumbs up", (0, 0, 0, 0), True),
        ("rock", (1, 0, 0, 1), None),         # index + pinky
        ("call me", (0, 0, 0, 1), None),      # pinky (with or without thumb)
    ],
}
SIGN_SET_NAMES = list(SIGN_SETS)

# Thumb: out when its tip is far from the pinky knuckle AND the thumb is straight;
# in when the tip is near the palm OR the thumb is bent. In between it keeps its state.
PINKY_MCP = 17
# Typical values: tucked across the palm ~0.5, wrapped over a fist ~0.65,
# thumbs up ~0.9, spread open hand ~1.3.
THUMB_OUT_MIN = 0.85       # tip-to-pinky-knuckle distance / hand size
THUMB_IN_MAX = 0.72
THUMB_STRAIGHT_MAX = 50    # degrees of bend at the thumb's two upper joints
THUMB_BENT_MIN = 75


# ---- Repeating the same note without changing sign ----
# Finger tap: fold the raised fingers part-way (on average this many degrees past their
# straightest position while you've held the sign) and straighten them again.
# Measured relative to your own hand, so it needs no exact fist.
TAP_DIP = 40
TAP_RETURN = 18
# Hand pump: a quick downward flick of the whole hand, in hand-lengths per second.
# Re-arms once the hand slows down again. Off in Bend mode, where height bends pitch.
PUMP_SPEED = 3.0
PUMP_REARM_SPEED = 0.8
PUMP_WINDOW = 0.10         # seconds; speed is measured over this span so jitter averages out
REPEAT_MIN_GAP = 0.12      # seconds; stops one movement counting twice
TAP_SMOOTHING = 0.5        # 0..1; how much of each new finger reading to take


# ---- Strike speed -> loudness ----
# How fast the fingers (or the whole hand) moved in the STRIKE_WINDOW before a sign was struck.
# Speeds below the floor are tracking jitter; floor + scale is a full-strength strike.
STRIKE_WINDOW = 0.15          # seconds
STRIKE_FINGER_FLOOR = 250     # degrees of finger bend per second
STRIKE_FINGER_FAST = 2000
STRIKE_HAND_FLOOR = 1.0       # hand-lengths per second
STRIKE_HAND_FAST = 5.0
PINCH_FLOOR = 100             # pinch style: thumb-to-tip distance change, hand-lengths x100 per second
PINCH_FAST = 700


def sign_names(sign_set):
    return [name for name, _, _ in SIGN_SETS[sign_set]]


def classify_sign(fingers, thumb_out, sign_set):
    """fingers: tuple of 4 bools. Returns a slot, REST, or None for 'not a sign'."""
    up = tuple(int(f) for f in fingers)
    if up == (0, 0, 0, 0) and (sign_set == "Basic" or thumb_out is False):
        return REST
    for slot, (_, pattern, thumb) in enumerate(SIGN_SETS[sign_set]):
        if up == pattern and (thumb is None or thumb == thumb_out):
            return slot
    return None

# Pinch thresholds as a fraction of hand size. Distances are measured on MediaPipe's
# 3D "world" landmarks, so tilting or turning the hand doesn't change them.
# Separate press/release values (hysteresis) stop notes flickering.
PRESS_RATIO = 0.32
RELEASE_RATIO = 0.48

# Latency compensation: when a finger is closing fast, trigger when it *will* touch
# LOOKAHEAD seconds from now instead of waiting for the next camera frame.
LOOKAHEAD = 0.04
MIN_CLOSING_SPEED = 1.0  # hand-sizes per second; slower movement is never predicted

EXPRESSION_MODES = ["Off", "Volume", "Bend"]
BEND_RANGE = 2.0    # semitones; matches the default pitch-bend range of most synths
BEND_TRAVEL = 0.20  # fraction of frame height you move the hand for a full bend


def dist3(a, b):
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def bend(a, b, c):
    """How far the joint at b bends away from straight, in degrees."""
    v1 = (a.x - b.x, a.y - b.y, a.z - b.z)
    v2 = (c.x - b.x, c.y - b.y, c.z - b.z)
    n = math.hypot(*v1) * math.hypot(*v2) + 1e-9
    cos = max(-1.0, min(1.0, sum(p * q for p, q in zip(v1, v2)) / n))
    return 180.0 - math.degrees(math.acos(cos))


def finger_curl(pts, mcp, pip, dip, tip):
    return bend(pts[WRIST], pts[mcp], pts[pip]) + bend(pts[mcp], pts[pip], pts[dip]) + bend(pts[pip], pts[dip], pts[tip])


def height_to_volume(y):
    """Hand near the top of the frame = loud, near the bottom = quiet."""
    return 0.1 + 0.9 * float(np.clip((0.85 - y) / 0.7, 0.0, 1.0))


class OneEuroFilter:
    """Adaptive smoothing: steady when the hand is still, almost no lag when it moves fast.

    A fixed smoothing factor has to trade jitter against delay; this filter raises its
    cutoff frequency with speed (Casiez et al., 2012).
    """

    def __init__(self, min_cutoff=1.0, beta=6.0, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(t - self.t, 1e-3)
        self.dx += self._alpha(self.d_cutoff, dt) * ((x - self.x) / dt - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += self._alpha(cutoff, dt) * (x - self.x)
        self.t = t
        return self.x


class HandState:
    """Tracks one hand across frames: which slots are active and where the hand is.

    A slot (0-3) is what selects the sound: a hand sign or a pinched finger.
    """

    def __init__(self, calibration=None):
        self.calibrate(calibration)
        self.reset()

    def calibrate(self, cal=None):
        """Use this hand's calibrated thresholds (from calibration.py), or the defaults.

        These survive reset(), which runs whenever the hand leaves the frame.
        """
        cal = cal or {}
        self.ext_max = list(cal.get("ext_max", [EXTENDED_MAX_CURL] * 4))
        self.curl_min = list(cal.get("curl_min", [CURLED_MIN_CURL] * 4))
        self.thumb_out_min = cal.get("thumb_out_min", THUMB_OUT_MIN)
        self.thumb_in_max = cal.get("thumb_in_max", THUMB_IN_MAX)

    def reset(self):
        self.motion = []            # recent (time, finger values, palm height in hand-lengths): strike speed
        self.strike = 0.5           # how hard the last sign was struck, 0..1
        self.active = set()         # slots currently sounding
        self.ratios = [1.0] * 4     # pinch: thumb-to-fingertip distance / hand size
        self.curls = [0.0] * 4      # signs: bend of each finger in degrees
        self.extended = [None] * 4  # signs: True = up, False = curled, None = not yet known
        self.thumb_ratio, self.thumb_bend = 0.0, 0.0
        self.thumb_out = None       # signs: True = out, False = in, None = not yet known
        self.sign = REST            # signs: confirmed sign (slot or REST)
        self.candidate, self.candidate_frames, self.candidate_since = None, 0, 0.0
        self.onset = 0.0            # time the current sign was first seen (for the rhythm game)
        self.tap_level = None       # smoothed fold of the raised fingers, degrees
        self.tap_base = None        # their usual straight position during this sign
        self.tap_dip = 0.0          # how far they're folded past that, degrees
        self.tap_armed = False
        self.pump_armed = False
        self.pump_speed = 0.0       # downward hand speed, hand-lengths per second
        self.palm_track = []        # recent (time, palm height in hand-lengths)
        self.last_repeat = -1.0
        self.repeat_flash = ("", -1.0)  # ("TAP" or "PUMP", time) for the screen
        self.label = ""             # what the hand is showing, for the screen
        self.last_t = None
        self.y = None               # filtered palm height, 0 (top) .. 1 (bottom)
        self.y_filter = OneEuroFilter()
        self.bend_ref = None        # palm height when the current phrase started
        self.last_expr = (0.0, 1.0)
        self.wrist = None           # screen position, keeps left/right labels stable

    def update_signs(self, landmarks, world, t, confirm=CONFIRM_FRAMES, sign_set="Basic", pump=True):
        """Hand-sign mode. Returns (pressed, released, label_points) for this frame.

        A repeat (tap or pump) of the current sign shows up as the same slot in both
        released and pressed, so the note is struck again.
        """
        previous_sign = self.sign
        dt = None if self.last_t is None else t - self.last_t
        pts = world or landmarks
        self.curls = [finger_curl(pts, *joints) for joints in FINGER_JOINTS]
        for f, curl in enumerate(self.curls):
            if curl < self.ext_max[f]:
                self.extended[f] = True
            elif curl > self.curl_min[f]:
                self.extended[f] = False

        hand_size = dist3(pts[WRIST], pts[MIDDLE_MCP]) + 1e-6
        self.thumb_ratio = dist3(pts[THUMB_TIP], pts[PINKY_MCP]) / hand_size
        self.thumb_bend = bend(pts[1], pts[2], pts[3]) + bend(pts[2], pts[3], pts[4])
        if self.thumb_ratio > self.thumb_out_min and self.thumb_bend < THUMB_STRAIGHT_MAX:
            self.thumb_out = True
        elif self.thumb_ratio < self.thumb_in_max or self.thumb_bend > THUMB_BENT_MIN:
            self.thumb_out = False
        self._track_motion(landmarks, t, self.curls)

        observed = None if None in self.extended else classify_sign(self.extended, self.thumb_out, sign_set)
        if observed is not None:  # unrecognised shapes (e.g. mid-change) are ignored
            if observed == self.candidate:
                self.candidate_frames += 1
            else:
                self.candidate, self.candidate_frames, self.candidate_since = observed, 1, t
            if self.candidate_frames >= confirm and observed != self.sign:
                self.sign = observed
                self.onset = self.candidate_since  # when the sign was first seen, not confirmed

        self.label = "fist (silent)" if self.sign == REST else sign_names(sign_set)[self.sign]
        now = set() if self.sign == REST else {self.sign}
        top = min(lm.y for lm in landmarks)
        points = {s: (landmarks[MIDDLE_MCP].x, top - 0.04) for s in now}

        repeat = self._detect_repeat(landmarks, t, dt, sign_set, pump, changed=self.sign != previous_sign)
        pressed, released, points = self._finish(landmarks, now, points, t)
        if repeat:
            pressed, released = pressed | now, released | now
            self.onset = t
        if pressed:
            self.strike = self._strike(finger_scale=STRIKE_FINGER_FAST, finger_floor=STRIKE_FINGER_FLOOR)
        return pressed, released, points

    def _track_motion(self, landmarks, t, values):
        """Keep ~0.25 s of finger values and palm height, to measure how fast a sign was struck."""
        size = math.hypot(landmarks[WRIST].x - landmarks[MIDDLE_MCP].x,
                          landmarks[WRIST].y - landmarks[MIDDLE_MCP].y) + 1e-6
        self.motion.append((t, list(values), landmarks[MIDDLE_MCP].y / size))
        self.motion = [m for m in self.motion if t - m[0] <= STRIKE_WINDOW + 0.1]

    def _strike(self, finger_scale, finger_floor):
        """How hard the sign was struck, 0..1: the fastest finger or hand movement just before it.

        Finger speed is in degrees (or, for pinches, hand-lengths x100) per second; hand speed in
        hand-lengths per second. A floor ignores tracking jitter, so holding still reads as soft.
        """
        recent = [m for m in self.motion if self.motion[-1][0] - m[0] <= STRIKE_WINDOW]
        finger_speed = hand_speed = 0.0
        for (t0, v0, y0), (t1, v1, y1) in zip(recent, recent[1:]):
            dt = t1 - t0
            if dt <= 0 or dt > 0.2:
                continue
            finger_speed = max(finger_speed, max(abs(a - b) for a, b in zip(v0, v1)) / dt)
            hand_speed = max(hand_speed, abs(y1 - y0) / dt)
        strength = max((finger_speed - finger_floor) / finger_scale,
                       (hand_speed - STRIKE_HAND_FLOOR) / STRIKE_HAND_FAST)
        return float(np.clip(strength, 0.0, 1.0))

    def _detect_repeat(self, landmarks, t, dt, sign_set, pump, changed):
        """Finger tap or hand pump while holding the same sign. Returns "TAP", "PUMP" or ""."""
        # Hand speed (down = positive) in hand-lengths per second, so distance from the camera
        # doesn't matter. Measured over the last ~0.1 s rather than one frame, so jitter averages out.
        size = math.hypot(landmarks[WRIST].x - landmarks[MIDDLE_MCP].x, landmarks[WRIST].y - landmarks[MIDDLE_MCP].y) + 1e-6
        if dt is not None and not 0 < dt < 0.25:
            self.palm_track = []  # a gap in tracking: old positions say nothing about speed
        self.palm_track.append((t, landmarks[MIDDLE_MCP].y, size))
        self.palm_track = [p for p in self.palm_track if t - p[0] <= PUMP_WINDOW + 0.06]
        older = [p for p in self.palm_track if t - p[0] >= PUMP_WINDOW - 1e-6] or self.palm_track[:1]
        span = t - older[-1][0]
        mean_size = sum(p[2] for p in self.palm_track) / len(self.palm_track)
        moved = self.palm_track[-1][1] - older[-1][1]
        self.pump_speed = moved / mean_size / span if span >= 0.03 else 0.0

        if changed or self.sign == REST:
            # New sign (or silence): start fresh. The pump must wait for the hand to slow
            # down first, so the movement that formed the sign doesn't also re-strike it.
            self.tap_level = self.tap_base = None
            self.tap_dip, self.tap_armed, self.pump_armed = 0.0, False, False
            return ""

        _, fingers, _ = SIGN_SETS[sign_set][self.sign]
        raised = [f for f, up in enumerate(fingers) if up]
        level = sum(self.curls[f] for f in raised) / len(raised) if raised else self.thumb_bend
        self.tap_level = level if self.tap_level is None else self.tap_level + TAP_SMOOTHING * (level - self.tap_level)
        # Baseline follows the fingers down at once but drifts up only slowly, and never while
        # a tap is under way, so a real fold stands out while ordinary jitter doesn't
        if self.tap_base is None or self.tap_level < self.tap_base:
            self.tap_base = self.tap_level
        elif not self.tap_armed:
            self.tap_base += 0.05 * (self.tap_level - self.tap_base)
        self.tap_dip = self.tap_level - self.tap_base

        kind = ""
        if not self.tap_armed and self.tap_dip > TAP_DIP:
            self.tap_armed = True
        elif self.tap_armed and self.tap_dip < TAP_RETURN:
            self.tap_armed = False
            kind = "TAP"
        if pump:
            if self.pump_armed and self.pump_speed > PUMP_SPEED:
                self.pump_armed = False
                kind = kind or "PUMP"
            elif not self.pump_armed and self.pump_speed < PUMP_REARM_SPEED:
                self.pump_armed = True
        if kind and t - self.last_repeat >= REPEAT_MIN_GAP:
            self.last_repeat = t
            self.repeat_flash = (kind, t)
            return kind
        return ""

    def update(self, landmarks, world, t, lookahead=LOOKAHEAD):
        """Pinch mode. Returns (pressed, released, pinch_points) for this frame."""
        pts = world or landmarks
        hand_size = dist3(pts[WRIST], pts[MIDDLE_MCP]) + 1e-6
        thumb = pts[THUMB_TIP]
        ratios = [dist3(thumb, pts[i]) / hand_size for i in FINGERTIPS]
        dt = None if self.last_t is None else t - self.last_t

        now = {f for f in self.active if ratios[f] < RELEASE_RATIO}
        candidates = []
        for f, r in enumerate(ratios):
            if f in now:
                continue
            predicted = r
            if dt and 0 < dt < 0.2:
                speed = (r - self.ratios[f]) / dt
                if speed < -MIN_CLOSING_SPEED:
                    predicted = r + speed * lookahead
            if min(r, predicted) < PRESS_RATIO:
                candidates.append((r, f))
        if candidates:
            # One new press per hand per frame, the closest finger. When you pinch the
            # middle finger, the index tip often comes close too; this stops it ghosting.
            now.add(min(candidates)[1])

        points = {}
        for f in now:
            tip = landmarks[FINGERTIPS[f]]
            points[f] = ((landmarks[THUMB_TIP].x + tip.x) / 2, (landmarks[THUMB_TIP].y + tip.y) / 2)
        self.ratios = ratios
        self.label = ""
        self.onset = t
        self._track_motion(landmarks, t, [r * 100 for r in ratios])
        result = self._finish(landmarks, now, points, t)
        if result[0]:
            self.strike = self._strike(finger_scale=PINCH_FAST, finger_floor=PINCH_FLOOR)
        return result

    def _finish(self, landmarks, now, points, t):
        self.y = self.y_filter(landmarks[MIDDLE_MCP].y, t)
        if now and not self.active:
            self.bend_ref = self.y  # bend is relative to where you started the phrase
        self.wrist = (landmarks[WRIST].x, landmarks[WRIST].y)

        pressed, released = now - self.active, self.active - now
        self.active, self.last_t = now, t
        return pressed, released, points

    def lost(self):
        """Hand left the frame: release everything it was holding."""
        released = self.active
        self.reset()
        return released

    def expression(self, mode):
        """Returns (bend in semitones, volume 0..1) for the hand's current position."""
        if self.y is None:
            return 0.0, 1.0
        if mode == "Volume":
            return 0.0, height_to_volume(self.y)
        if mode == "Bend" and self.bend_ref is not None:
            amount = np.clip((self.bend_ref - self.y) / BEND_TRAVEL, -1.0, 1.0)
            return float(amount * BEND_RANGE), 1.0
        return 0.0, 1.0
