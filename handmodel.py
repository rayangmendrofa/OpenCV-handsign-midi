# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on the 21-landmark hand layout of Google MediaPipe; NumPy. Full credits: CREDITS.md

"""A synthetic hand: MediaPipe-style landmarks for any sign.

Used for the in-game ghost hints, the built-in demo session and the tests. Geometry is in
"hand lengths" (wrist to middle knuckle = 1) for a right hand with the palm facing the camera;
x to the right, y down, z towards the camera negative (MediaPipe's convention). A left hand is
the mirror image.
"""

import math
from types import SimpleNamespace

import numpy as np

# Knuckle (MCP) positions and bone lengths (proximal, middle, distal) for index..pinky
MCP = [(-0.33, -0.92), (-0.10, -1.00), (0.13, -0.95), (0.33, -0.84)]
BONES = [(0.42, 0.25, 0.20), (0.47, 0.29, 0.22), (0.43, 0.27, 0.21), (0.33, 0.21, 0.18)]
FULL_CURL = (70, 100, 60)  # degrees at MCP, PIP, DIP when fully curled
# Thumb CMC, MCP, IP, tip for each thumb position
THUMB = {
    "out": [(-0.28, -0.16, 0.0), (-0.50, -0.32, -0.02), (-0.70, -0.48, -0.03), (-0.88, -0.62, -0.03)],
    "in": [(-0.28, -0.16, 0.0), (-0.32, -0.42, -0.12), (-0.10, -0.58, -0.24), (0.12, -0.64, -0.28)],
    "up": [(-0.28, -0.16, 0.0), (-0.40, -0.48, -0.10), (-0.46, -0.80, -0.11), (-0.52, -1.18, -0.10)],
    "fist": [(-0.28, -0.16, 0.0), (-0.40, -0.48, -0.15), (-0.30, -0.78, -0.32), (-0.10, -0.96, -0.36)],
}


def thumb_mode(pattern, thumb):
    """Where the thumb goes for a sign: pattern = fingers up (index..pinky), thumb True/False/None."""
    if not any(pattern):
        return "up" if thumb else "fist"
    if thumb is True:
        return "out"
    if thumb is None and tuple(pattern) == (0, 0, 0, 1):
        return "out"  # "call me" usually has the thumb out
    return "in"


def pose(pattern, thumb, fold=None):
    """21 (x, y, z) points in hand lengths. fold: optional curl 0..1 per finger, overriding pattern."""
    pts = np.zeros((21, 3))
    pts[1:5] = THUMB[thumb_mode(pattern, thumb)]
    for f in range(4):
        curl = fold[f] if fold is not None else (0.0 if pattern[f] else 1.0)
        base = 5 + 4 * f
        p = np.array([*MCP[f], 0.0])
        pts[base] = p
        total = 0.0
        for j, (length, full) in enumerate(zip(BONES[f], FULL_CURL)):
            total += math.radians(5 + (full - 5) * curl)
            # bend towards the camera: the finger tip moves into negative z as it curls
            p = p + length * np.array([0.0, -math.cos(total), -math.sin(total)])
            pts[base + 1 + j] = p
    return pts


def landmarks(pattern, thumb, hand="R", center=(0.5, 0.6), size=0.17, fold=None, yaw=0.0, aspect=16 / 9):
    """(screen landmarks, world landmarks) like MediaPipe's, for a sign at a screen position.

    center: where the middle knuckle sits (0..1); size: wrist-to-knuckle length as a fraction
    of the image height.
    """
    pts = pose(pattern, thumb, fold)
    if hand == "L":
        pts[:, 0] *= -1
    if yaw:
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        x, z = pts[:, 0].copy(), pts[:, 2].copy()
        pts[:, 0], pts[:, 2] = x * c + z * s, -x * s + z * c
    rel = pts - pts[9]  # middle knuckle at the given centre
    screen = [SimpleNamespace(x=center[0] + x * size / aspect, y=center[1] + y * size, z=z * size)
              for x, y, z in rel]
    centroid = pts.mean(axis=0)
    world = [SimpleNamespace(x=(x - centroid[0]) * 0.09, y=(y - centroid[1]) * 0.09, z=(z - centroid[2]) * 0.09)
             for x, y, z in pts]
    return screen, world


class FakeResult:
    """Looks like MediaPipe's HandLandmarkerResult, for feeding synthetic hands to assign_hands()."""

    def __init__(self, hands):
        self.hand_landmarks = [h[0] for h in hands]
        self.hand_world_landmarks = [h[1] for h in hands]
