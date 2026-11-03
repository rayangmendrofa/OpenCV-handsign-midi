# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on colours after A. Scriabin's clavier à lumières (1910); NumPy, OpenCV. Full credits: CREDITS.md

"""Chromesthesia backdrop: a slowly mutating colour field that answers the notes being played.

Chromesthesia is a form of synaesthesia in which sounds are experienced as colours. There is no
single "true" mapping (each synaesthete's differs), so this follows the best known artistic one,
Alexander Scriabin's (his "clavier à lumières" for Prometheus, 1910): the 12 pitch classes go
round the colour wheel in **circle-of-fifths** order (C red, G orange, D yellow, A green,
E pale sky blue, B bluish white, F# bright blue, C# violet, G# lilac, D# and A# steely rose,
F deep red). Neighbours on the circle of fifths sound consonant together, so harmonious chords
give neighbouring colours and dissonant ones clash.

How the field is built (at a small size, then scaled up smoothly):
  * Every note blooms on a colour wheel around you, at its circle-of-fifths angle (C at the
    top, G one step clockwise...), low octaves near the middle and high ones further out, so
    the notes of a chord bloom in different places. Each bloom grows, drifts outward like ink
    in water and fades after release. Louder notes bloom bigger and brighter; higher octaves
    are paler, lower ones deeper.
  * Behind the blooms, a two-colour gradient flows and folds over itself. Its colours glide
    (over about a second) toward the colours of what is sounding, so the whole room takes on
    the harmony of the moment, and back to deep indigo in silence.
  * A kick pulses the brightness, a snare or clap flashes, cymbals sparkle.

Events arrive from any thread through send(); everything else runs on the thread that renders.
"""

import math
import random
import time
from collections import deque

import numpy as np

SIZE = (160, 90)           # render size; scaled up with cubic interpolation, so gradients stay smooth
FIFTHS = [(pc * 7) % 12 for pc in range(12)]   # C G D A E B F# C# G# D# A# F
SCRIABIN = {               # pitch class -> RGB, after Scriabin's colour chart
    0: (255, 0, 0), 7: (255, 128, 0), 2: (255, 230, 0), 9: (40, 200, 60), 4: (150, 215, 255),
    11: (190, 205, 255), 6: (80, 110, 255), 1: (140, 0, 255), 8: (190, 110, 250), 3: (190, 70, 140),
    10: (170, 100, 125), 5: (170, 0, 50)}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SILENCE = ((0.10, 0.08, 0.24), (0.03, 0.12, 0.20))   # deep indigo and teal, RGB 0..1
MOOD_TIME = 0.9            # seconds for the background colours to glide to the harmony
ATTACK, SUSTAIN, SUSTAIN_TIME, RELEASE_TIME = 0.06, 0.7, 1.5, 0.9
MAX_BLOOMS = 40
CLICK_DRUMS = {"rim"}      # metronome and count-in clicks don't light up the room


def note_rgb(midi):
    """The colour of a note (RGB 0..1): Scriabin's colour for its pitch class, lighter when higher."""
    base = np.array(SCRIABIN[midi % 12], np.float32) / 255
    height = min(1.0, max(0.0, (midi - 36) / 48))            # C2 .. C6
    if height > 0.5:
        return tuple(base + (1 - base) * (height - 0.5) * 0.7)   # high: paler
    return tuple(base * (0.6 + 0.8 * height))                 # low: deeper


def key_colours():
    """[(name, RGB 0..255)] in circle-of-fifths order, for a legend."""
    return [(NOTE_NAMES[pc], tuple(int(255 * c) for c in note_rgb(60 + pc))) for pc in FIFTHS]


class Bloom:
    __slots__ = ("vid", "rgb", "x", "y", "vx", "vy", "size", "vel", "born", "released", "weight")

    def __init__(self, vid, midi, velocity, weight, now, rng):
        self.vid, self.rgb, self.vel, self.weight = vid, np.array(note_rgb(midi), np.float32), velocity, weight
        # on a colour wheel around the centre: angle from the circle of fifths, distance from the octave
        angle = 2 * math.pi * FIFTHS.index(midi % 12) / 12 + rng.uniform(-0.12, 0.12)
        reach = 0.16 + 0.22 * min(1.0, max(0.0, (midi - 36) / 48))
        dx, dy = math.sin(angle), -math.cos(angle)                # C at the top, then clockwise
        self.x, self.y = 0.5 + reach * dx, 0.5 + reach * dy * 1.6
        drift = rng.uniform(0.02, 0.05)                           # spreads outward slowly
        self.vx, self.vy = drift * dx, drift * dy * 1.6
        self.size = 0.09 + 0.08 * velocity
        self.born, self.released = now, None

    def energy(self, now):
        age = now - self.born
        level = min(1.0, age / ATTACK)
        level *= SUSTAIN + (1 - SUSTAIN) * math.exp(-age / SUSTAIN_TIME)
        if self.released is not None:
            level *= math.exp(-(now - self.released) / RELEASE_TIME)
        return level * (0.45 + 0.55 * self.vel)


class Synesthesia:
    def __init__(self, seed=7):
        self.events = deque()
        self.blooms = []
        self.mood = [np.array(c, np.float32) for c in SILENCE]
        self.kick = self.flash = self.sparkle = 0.0
        self.last = None
        self.rng = random.Random(seed)
        w, h = SIZE
        self.x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        self.y = np.linspace(0, h / w, h, dtype=np.float32)[:, None]   # square pixels
        self.glitter = np.random.default_rng(seed).random((h, w)).astype(np.float32)
        self.accent = np.array(SILENCE[0], np.float32)   # the strongest colour now (RGB), for a rim light

    def send(self, event):
        """Any musical event (thread-safe). Notes, releases and drums are used; the rest ignored."""
        if event[0] in ("note_on", "note_off", "all_off", "drum"):
            self.events.append(event)

    def _apply(self, event, now):
        kind = event[0]
        if kind == "note_on":
            vid, midi, velocity, group = event[1:5]
            for b in self.blooms:      # the same voice re-struck: release the old bloom
                if b.vid == vid and b.released is None:
                    b.released = now
            weight = 1.0 if group in ("L", "R") or str(group).startswith("loop") else 0.5   # backing counts less
            self.blooms.append(Bloom(vid, midi, velocity, weight, now, self.rng))
            if len(self.blooms) > MAX_BLOOMS:
                self.blooms.pop(0)
        elif kind == "note_off":
            for b in self.blooms:
                if b.vid == event[1] and b.released is None:
                    b.released = now
        elif kind == "all_off":
            for b in self.blooms:
                if b.released is None and isinstance(b.vid, tuple) and b.vid and b.vid[0] == event[1]:
                    b.released = now
        elif kind == "drum" and event[1] not in CLICK_DRUMS:
            name, velocity = event[1], event[2]
            if name in ("kick", "tom_low", "tom_high"):
                self.kick = max(self.kick, velocity)
            elif name in ("snare", "clap", "crash"):
                self.flash = max(self.flash, velocity * (1.3 if name == "crash" else 1.0))
            else:   # hats, ride, shaker, cowbell
                self.sparkle = max(self.sparkle, velocity)

    def render(self, now=None):
        """The field as RGB float32 (SIZE[1] x SIZE[0] x 3, 0..1)."""
        now = time.perf_counter() if now is None else now
        dt = 0.0 if self.last is None else min(0.2, max(0.0, now - self.last))
        self.last = now
        while self.events:
            self._apply(self.events.popleft(), now)

        # the harmony of the moment: energy-weighted colours of what is sounding
        live = [(b, b.energy(now) * b.weight) for b in self.blooms]
        self.blooms = [b for b, e in live if e > 0.01 or b.released is None]
        live = [(b, e) for b, e in live if e > 0.01]
        live.sort(key=lambda be: -be[1])
        if live:
            total = sum(e for _, e in live)
            avg = sum(b.rgb * e for b, e in live) / total
            avg = np.clip(avg.mean() + (avg - avg.mean()) * 1.6, 0, 1)   # mixing greys colours out: restore
            targets = [0.55 * live[0][0].rgb + 0.45 * avg, 0.75 * avg + 0.25 * live[-1][0].rgb]
            self.accent = live[0][0].rgb
        else:
            targets = [np.array(c, np.float32) for c in SILENCE]
        k = 1 - math.exp(-dt / MOOD_TIME)
        self.mood = [m + (t - m) * k for m, t in zip(self.mood, targets)]

        # flowing, folding two-colour gradient
        x, y, t = self.x, self.y, now
        angle = 0.07 * t
        u = x * math.cos(angle) + y * math.sin(angle)
        warp = 0.35 * np.sin(3.1 * x + 0.6 * t) * np.cos(2.3 * y - 0.4 * t) + 0.15 * np.sin(5.3 * y + 0.9 * t)
        w = (0.5 + 0.5 * np.sin(2 * np.pi * (0.8 * u + warp) + 0.5 * t))[..., None]
        a, b = self.mood
        field = (a * (1 - w) + b * w) * 0.38

        # blooms, added with a screen blend so overlapping colours mix toward light
        for bloom, e in live:
            age = now - bloom.born
            bloom.x += bloom.vx * dt
            bloom.y += bloom.vy * dt
            r = bloom.size * (1 + 0.6 * (1 - math.exp(-age / 1.5)))
            g = np.exp(-((x - bloom.x) ** 2 + (y - bloom.y * SIZE[1] / SIZE[0]) ** 2) / (r * r))[..., None]
            field = 1 - (1 - field) * (1 - bloom.rgb * (0.8 * e) * g)

        # drums
        decay = math.exp(-dt / 0.18)
        if self.kick > 0.01:
            field = field * (1 + 0.45 * self.kick)
        if self.flash > 0.01:
            field = 1 - (1 - field) * (1 - 0.35 * self.flash * (0.6 + 0.4 * self.mood[1]))
        if self.sparkle > 0.01:
            dots = (self.glitter > 0.985 - 0.02 * self.sparkle).astype(np.float32)[..., None]
            field = field + dots * 0.5 * self.sparkle
            self.glitter = np.roll(self.glitter, 7, axis=1)
        self.kick *= decay
        self.flash *= decay
        self.sparkle *= math.exp(-dt / 0.1)
        return np.clip(field, 0.0, 1.0).astype(np.float32)

    def image(self, size=None, now=None):
        """The field as a BGR uint8 image (for OpenCV), scaled to size if given."""
        import cv2
        img = (self.render(now)[..., ::-1] * 255).astype(np.uint8)
        return cv2.resize(img, size, interpolation=cv2.INTER_CUBIC) if size else img
