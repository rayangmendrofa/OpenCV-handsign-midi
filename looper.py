# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on the Python standard library. Full credits: CREDITS.md

"""Record-and-loop: capture what you play and replay it in time, stacking overdub layers.

The looper stores musical *events* (not audio), so loops also replay over MIDI, keep their
notes when you change scale or sound, and can be exported as a MIDI file. A background thread
checks the clock every 2 ms and dispatches events as the loop position passes them.

Timing helpers, all optional:
  metronome  a click on every beat (accent on beat 1) at the loop tempo
  count-in   one bar of clicks before the first recording starts
  quantise   snap note starts to a 1/4, 1/8 or 1/16 grid when a take is saved (lengths kept);
             with the metronome or quantise on, the first loop's length is rounded to whole bars
"""

import math
import threading
import time

QUANTISE = ["Off", "1/4", "1/8", "1/16"]
GRID_BEATS = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25}
CLICK = ("drum", "rim")


class Looper:
    def __init__(self, dispatch, bpm=100.0, metronome=False, count_in=True, quantise="Off"):
        self.dispatch = dispatch      # callable(event): plays an event on synth + MIDI
        self.lock = threading.Lock()
        self.layers = []              # each layer: sorted list of (seconds_into_loop, event)
        self.length = None            # loop length in seconds, set by the first recording
        self.origin = 0.0             # perf_counter() time of loop position 0
        self.state = "empty"          # empty | countin | recording | playing | overdub | stopped
        self.take, self.take_open = [], set()
        self.bpm, self.beats_per_bar = bpm, 4
        self.metronome, self.count_in, self.quantise = metronome, count_in, quantise
        self._last_pos = 0.0
        self._last_click = None
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def beat(self):
        return 60.0 / self.bpm

    @property
    def bar(self):
        return self.beat * self.beats_per_bar

    # ---- controls (main thread) ----

    @property
    def recording(self):
        return self.state in ("recording", "overdub")

    def position(self):
        """Loop progress 0..1 for the UI, or None when nothing is playing."""
        if self.length and self.state in ("playing", "overdub"):
            return ((time.perf_counter() - self.origin) % self.length) / self.length
        return None

    def toggle_record(self):
        now = time.perf_counter()
        with self.lock:
            if self.state == "empty":
                self._new_take()
                if self.count_in:  # one bar of clicks, then recording starts on the downbeat
                    self.state, self.origin = "countin", now + self.bar
                    self._last_click = None
                else:
                    self.state, self.origin = "recording", now
            elif self.state == "countin":  # pressed again during the count-in: cancel
                self.state = "empty"
            elif self.state == "recording":
                raw = max(now - self.origin, 0.25)
                if self.metronome or self.quantise != "Off":
                    self.length = max(1, round(raw / self.bar)) * self.bar  # whole bars
                else:
                    self.length = raw
                self._commit_take(min(raw, self.length) - 1e-3)
                self.state, self._last_pos = "playing", raw % self.length
            elif self.state == "playing":
                self.state = "overdub"
                self._new_take()
            elif self.state == "overdub":
                self._commit_take((now - self.origin) % self.length)
                self.state = "playing"
            elif self.state == "stopped":
                self._restart(now)
                self.state = "overdub"
                self._new_take()

    def toggle_play(self):
        now = time.perf_counter()
        with self.lock:
            if self.state == "overdub":
                self._commit_take((now - self.origin) % self.length)
            if self.state in ("playing", "overdub"):
                self.state = "stopped"
                stop = True
            elif self.state == "stopped":
                self._restart(now)
                self.state, stop = "playing", False
            else:
                return
        if stop:
            self.dispatch(("all_off", "loop"))

    def undo(self):
        with self.lock:
            if self.state in ("recording", "countin") or not self.layers:
                return
            self.layers.pop()
            if not self.layers:
                self.state, self.length = "empty", None
        self.dispatch(("all_off", "loop"))

    def clear(self):
        with self.lock:
            self.layers, self.length, self.state = [], None, "empty"
        self.dispatch(("all_off", "loop"))

    def record(self, event):
        """Called for every live event; stores it if we're recording."""
        if self.state not in ("recording", "overdub", "countin"):
            return
        now = time.perf_counter()
        with self.lock:
            if self.state == "countin":
                if now < self.origin - 0.15:   # well before the downbeat: not part of the take
                    return
                t = 0.0                        # a hair early counts as on the downbeat
            elif self.state == "recording":
                t = now - self.origin
            elif self.state == "overdub":
                t = (now - self.origin) % self.length
            else:
                return
            kind = event[0]
            if kind == "note_on":
                self.take_open.add(event[1])
            elif kind == "note_off":
                if event[1] not in self.take_open:
                    return  # note began before recording started
                self.take_open.discard(event[1])
            elif kind not in ("drum", "expr"):
                return
            self.take.append((t, event))

    def export_events(self, cycles=1):
        """The loop as [(seconds, event)] for a MIDI file, repeated `cycles` times."""
        with self.lock:
            if not self.layers:
                return []
            out = []
            for c in range(cycles):
                for i, layer in enumerate(self.layers):
                    out += [(c * self.length + t, self._as_loop_event(i, e)) for t, e in layer]
        return sorted(out, key=lambda e: e[0])

    def close(self):
        self._running = False

    # ---- internals ----

    def _new_take(self):
        self.take, self.take_open = [], set()

    def _commit_take(self, end_time):
        for vid in self.take_open:  # notes still held when recording stopped
            self.take.append((end_time, ("note_off", vid)))
        if self.take and self.quantise != "Off":
            self.take = self._quantised(self.take)
        if self.take:
            self.layers.append(sorted(self.take, key=lambda e: e[0]))
        self._new_take()

    def _quantised(self, take):
        """Snap note and drum starts to the grid; each note's release moves with its start."""
        grid = GRID_BEATS[self.quantise] * self.beat
        length = self.length or max(t for t, _ in take) + grid
        shift, out = {}, []
        for t, ev in take:
            if ev[0] in ("note_on", "drum"):
                snapped = round(t / grid) * grid
                if ev[0] == "note_on":
                    shift[ev[1]] = snapped - t
                t = snapped
            elif ev[0] == "note_off" and ev[1] in shift:
                t = t + shift[ev[1]]
            out.append((t % length, ev))
        return out

    def _restart(self, now):
        self.origin, self._last_pos = now, 0.0

    @staticmethod
    def _as_loop_event(layer, event):
        """Rename voices/groups so loop notes never collide with live ones."""
        kind = event[0]
        if kind == "note_on":
            _, vid, note, velocity, group, *instrument = event  # loops keep the instrument they were played with
            return ("note_on", ("loop", layer, vid), note, velocity, f"loop{layer}:{group}", *instrument)
        if kind == "note_off":
            return ("note_off", ("loop", layer, event[1]))
        if kind == "expr":
            _, group, bend, volume = event
            return ("expr", f"loop{layer}:{group}", bend, volume)
        return event

    def _click(self, now):
        """Metronome / count-in: one click as each beat begins, accented on beat 1."""
        clicking = self.state == "countin" or (self.metronome and self.state in ("recording", "playing", "overdub"))
        if not clicking:
            self._last_click = None
            return None
        beat = math.floor((now - self.origin) / self.beat + 1e-6)
        if beat == self._last_click:
            return None
        self._last_click = beat
        return CLICK + (0.8 if beat % self.beats_per_bar == 0 else 0.45)

    def _run(self):
        while self._running:
            time.sleep(0.002)
            due = []
            with self.lock:
                now = time.perf_counter()
                if self.state == "countin" and now >= self.origin:
                    self.state = "recording"
                click = self._click(now)
                if click:
                    due.append((0, 0, click))
                if self.state in ("playing", "overdub") and self.layers:
                    pos = (now - self.origin) % self.length
                    last, wrapped = self._last_pos, pos < self._last_pos
                    for i, layer in enumerate(self.layers):
                        for t, event in layer:
                            hit = (t >= last or t < pos) if wrapped else (last <= t < pos)
                            if hit:
                                order = (t < last) if wrapped else 0
                                due.append((order, t, self._as_loop_event(i, event)))
                    self._last_pos = pos
            for _, _, event in sorted(due, key=lambda d: (d[0], d[1])):
                self.dispatch(event)
