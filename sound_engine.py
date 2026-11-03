# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on sounddevice / PortAudio (MIT); reverb after Jezar's Freeverb (public domain); NumPy. Full credits: CREDITS.md

"""Real-time polyphonic synth with continuous pitch bend and volume, plus drum one-shots.

Sound is generated block by block inside the audio callback, so a note's pitch and
volume can change while it plays. Other threads talk to it only through send(),
which drops events into a lock-free queue that the callback drains.
"""

import collections
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 44100
BLOCK = 256           # ~6 ms per audio block
MASTER_GAIN = 0.35
DRUM_GAIN = 1.2


@dataclass(frozen=True)
class Instrument:
    """How one instrument sounds, built from sine partials (additive synthesis).

    partials: (frequency ratio, amplitude, decay per second); decay 0 = sustains.
    attack/release: fade-in and fade-out times in seconds.
    vibrato: pitch wobble rate (Hz) and depth (semitones), starting after vibrato_delay.
    transpose: semitones added to every note (the bass plays an octave down).
    gm_program: General MIDI program number, sent to MIDI devices.
    gain: loudness trim so instruments sound about equally loud.
    """
    partials: tuple
    attack: float = 0.008
    release: float = 0.25
    vibrato_rate: float = 0.0
    vibrato_depth: float = 0.0
    vibrato_delay: float = 0.3
    transpose: int = 0
    gm_program: int = 0
    gain: float = 1.0


def _saw(n, decay=0.0):
    """Sawtooth-like tone: every harmonic at 1/n strength (bright, buzzy)."""
    return tuple((k, 1.0 / k, decay * k) for k in range(1, n + 1))


INSTRUMENTS = {
    "Piano": Instrument(((1, 1.0, 2.5), (2, 0.5, 3.5), (3, 0.25, 4.5), (4, 0.12, 5.5), (5, 0.06, 6.5)),
                        attack=0.005, release=0.25, gm_program=0),
    "Electric piano": Instrument(((1, 1.0, 1.4), (2, 0.45, 2.6), (3, 0.12, 4.0), (4, 0.06, 6.0), (7, 0.05, 9.0)),
                                 attack=0.004, release=0.35, vibrato_rate=5.0, vibrato_depth=0.04,
                                 vibrato_delay=0.0, gm_program=4),
    "Organ": Instrument(((0.5, 0.4, 0), (1, 1.0, 0), (2, 0.6, 0), (3, 0.3, 0), (4, 0.2, 0)),
                        attack=0.01, release=0.08, vibrato_rate=6.5, vibrato_depth=0.05, gm_program=16, gain=0.9),
    "Strings": Instrument(_saw(10), attack=0.25, release=0.6, vibrato_rate=5.5, vibrato_depth=0.12,
                          gm_program=48, gain=1.1),
    "Pluck": Instrument(tuple((n, 1.0 / n, 3.0 * n) for n in range(1, 9)), attack=0.002, release=0.2, gm_program=24),
    "Bass": Instrument(((1, 1.0, 1.0), (2, 0.5, 2.0), (3, 0.25, 3.5), (4, 0.1, 5.0)),
                       attack=0.005, release=0.15, transpose=-12, gm_program=33, gain=1.2),
    "Synth lead": Instrument(_saw(12, decay=0.15), attack=0.01, release=0.2, vibrato_rate=5.5,
                             vibrato_depth=0.15, vibrato_delay=0.2, gm_program=81, gain=0.9),
    "Bell": Instrument(((1, 1.0, 1.2), (2.0, 0.6, 1.6), (2.76, 0.5, 2.2), (5.4, 0.3, 3.5), (8.9, 0.2, 5.0)),
                       attack=0.002, release=1.0, gm_program=14),
    "Marimba": Instrument(((1, 1.0, 4.0), (3.9, 0.35, 9.0), (9.2, 0.12, 16.0)), attack=0.002, release=0.2,
                          gm_program=12, gain=1.2),
    "Flute": Instrument(((1, 1.0, 0), (2, 0.25, 0), (3, 0.08, 0)), attack=0.08, release=0.15, vibrato_rate=5.0,
                        vibrato_depth=0.1, vibrato_delay=0.25, gm_program=73),
}
INSTRUMENT_NAMES = list(INSTRUMENTS)


def midi_to_freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def hand_of(group):
    """'L'/'R' for a hand's notes (live or looped), None for game backing and previews."""
    if group and group[-1] in "LR" and (len(group) == 1 or group.startswith("loop")):
        return group[-1]
    return None


class Reverb:
    """A small room reverb (Freeverb-style: 4 damped comb filters, then 2 allpass filters).

    Every delay is longer than one audio block, so each block can be computed with NumPy in one
    go instead of sample by sample.
    """
    COMBS = (1116, 1188, 1277, 1356)
    ALLPASSES = (556, 441)

    def __init__(self, feedback=0.80, damp=0.35, allpass_gain=0.5):
        self.feedback, self.damp, self.g = feedback, damp, allpass_gain
        self.comb = [np.zeros(d + 1) for d in self.COMBS]       # last d+1 outputs of each comb
        self.ap_in = [np.zeros(d) for d in self.ALLPASSES]      # last d inputs / outputs of each allpass
        self.ap_out = [np.zeros(d) for d in self.ALLPASSES]

    def process(self, x):
        n = len(x)
        out = np.zeros(n)
        for i, d in enumerate(self.COMBS):
            h = self.comb[i]
            delayed = (1 - self.damp) * h[1:n + 1] + self.damp * h[0:n]   # damping: a gentle low-pass
            y = x + self.feedback * delayed
            self.comb[i] = np.concatenate([h, y])[-(d + 1):]
            out += y
        out /= len(self.COMBS)
        for j, d in enumerate(self.ALLPASSES):
            y = -self.g * out + self.ap_in[j][:n] + self.g * self.ap_out[j][:n]
            self.ap_in[j] = np.concatenate([self.ap_in[j], out])[-d:]
            self.ap_out[j] = np.concatenate([self.ap_out[j], y])[-d:]
            out = y
        return out


class Voice:
    """One sounding note. Keeps its own phase so pitch can glide smoothly."""

    def __init__(self, vid, midi, velocity, group, instrument):
        total = sum(a for _, a, _ in instrument.partials)
        self.partials = [(r, a / total, d) for r, a, d in instrument.partials]
        self.inst = instrument
        self.vid, self.freq, self.group = vid, midi_to_freq(midi), group
        self.velocity = velocity * instrument.gain
        self.phase = 0.0
        self.age = 0              # samples rendered so far
        self.released_at = None   # age when the note was released
        self.decays = all(d > 0 for _, _, d in instrument.partials)

    def render(self, frames, bend, volume):
        inst = self.inst
        n = np.arange(frames)
        t = (self.age + n) / SAMPLE_RATE
        if inst.vibrato_depth:  # fades in after vibrato_delay, like a player adding vibrato
            fade = np.clip((t - inst.vibrato_delay) / 0.3, 0.0, 1.0)
            bend = bend + inst.vibrato_depth * fade * np.sin(2 * np.pi * inst.vibrato_rate * t)
        phase = self.phase + np.cumsum(2 * np.pi * self.freq * np.exp2(bend / 12) / SAMPLE_RATE)
        self.phase = phase[-1] % (4 * np.pi)  # 4*pi keeps the 0.5 sub-harmonic continuous

        wave = np.zeros(frames)
        for ratio, amp, decay in self.partials:
            wave += amp * (np.exp(-decay * t) if decay else 1.0) * np.sin(ratio * phase)

        env = np.minimum(1.0, t / inst.attack)
        if self.released_at is not None:
            env *= np.clip(1 - (self.age + n - self.released_at) / (inst.release * SAMPLE_RATE), 0, 1)
        self.age += frames
        return wave * env * volume * self.velocity

    @property
    def finished(self):
        if self.released_at is not None:
            return self.age - self.released_at >= self.inst.release * SAMPLE_RATE
        return self.decays and self.age > 8 * SAMPLE_RATE  # long-decayed piano/pluck


class SoundEngine:
    def __init__(self, kit, timbre="Piano", enabled=True):
        self.kit = kit
        self.timbre = timbre
        self.enabled = enabled
        self.events = collections.deque()   # thread-safe for append/popleft
        self.voices = []
        self.oneshots = []                  # [samples, position, gain]
        self.current = {}                   # group -> (bend, volume) last applied
        self.targets = {}                   # group -> (bend, volume) requested
        self.capture = None                 # list of output blocks while a demo capture runs
        self.stream = None
        self.hand_gain = {"L": 1.0, "R": 1.0}   # per-hand volume (mixer), applies immediately
        self.hand_send = {"L": 0.15, "R": 0.15}  # per-hand reverb send
        self.reverb = Reverb()
        self.track = None                   # music file playing as the game's backing: {"data", "at", "pos"}
        self.track_gain = 0.7

    def start(self):
        if not self.enabled:
            return
        kwargs = dict(samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=2,
                      dtype="float32", latency="low", callback=self._callback)
        try:  # WASAPI has much lower latency than Windows' default MME driver
            wasapi = next(h for h in sd.query_hostapis() if "WASAPI" in h["name"])
            self.stream = sd.OutputStream(device=wasapi["default_output_device"],
                                          extra_settings=sd.WasapiSettings(auto_convert=True), **kwargs)
        except Exception:
            self.stream = sd.OutputStream(**kwargs)
        self.stream.start()

    def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

    def send(self, event):
        """Queue an event from any thread. See gesture_music.py for event shapes."""
        if self.enabled:
            self.events.append(event)

    # ---- everything below runs on the audio thread ----

    def _release(self, match):
        for v in self.voices:
            if v.released_at is None and match(v.vid):
                v.released_at = v.age

    def _apply(self, event):
        kind = event[0]
        if kind == "note_on":
            _, vid, midi, velocity, group = event[:5]
            # Optional 6th field names the instrument; without it (game backing) use the default
            name = event[5] if len(event) > 5 and event[5] in INSTRUMENTS else self.timbre
            self._release(lambda x: x == vid)
            if not any(v.group == group for v in self.voices):
                self.current[group] = self.targets.get(group, (0.0, 1.0))  # no glide from old bend
            self.voices.append(Voice(vid, midi, velocity, group, INSTRUMENTS[name]))
        elif kind == "note_off":
            self._release(lambda x: x == event[1])
        elif kind == "drum":
            name, velocity = event[1], event[2]
            hand = event[3] if len(event) > 3 else None   # optional: which hand struck it (for the mixer)
            self.oneshots.append([self.kit[name], 0, velocity * DRUM_GAIN, hand])
        elif kind == "track":   # ("track", samples at 44.1 kHz, perf_counter time to start)
            self.track = {"data": event[1], "at": event[2], "pos": None}
        elif kind == "track_stop":
            self.track = None
        elif kind == "expr":
            _, group, bend, volume = event
            self.targets[group] = (bend, volume)
        elif kind == "all_off":
            self._release(lambda x: x[0] == event[1])

    def _callback(self, outdata, frames, time_info, status):
        while self.events:
            self._apply(self.events.popleft())

        # Ramp bend/volume across the block to avoid zipper noise
        ramp = (np.arange(frames) + 1) / frames
        params = {}
        for group in {v.group for v in self.voices}:
            b0, v0 = self.current.get(group, (0.0, 1.0))
            b1, v1 = self.targets.get(group, (0.0, 1.0))
            params[group] = (b0 + (b1 - b0) * ramp, v0 + (v1 - v0) * ramp)
            self.current[group] = (b1, v1)

        # Mix each hand separately so its volume and reverb send apply (even to notes already sounding)
        mixes = {"L": np.zeros(frames), "R": np.zeros(frames), None: np.zeros(frames)}
        for v in self.voices:
            mixes[hand_of(v.group)] += v.render(frames, *params[v.group])
        self.voices = [v for v in self.voices if not v.finished]

        alive = []
        for shot in self.oneshots:
            samples, pos, gain, hand = shot
            chunk = samples[pos:pos + frames]
            mixes[hand if hand in ("L", "R") else None][:len(chunk)] += chunk * gain
            shot[1] += frames
            if shot[1] < len(samples):
                alive.append(shot)
        self.oneshots = alive

        dry = mixes[None] + self.hand_gain["L"] * mixes["L"] + self.hand_gain["R"] * mixes["R"]
        send = (self.hand_gain["L"] * self.hand_send["L"] * mixes["L"]
                + self.hand_gain["R"] * self.hand_send["R"] * mixes["R"] + 0.1 * mixes[None])
        mix = dry + 1.4 * self.reverb.process(send)
        out = np.tanh(mix * MASTER_GAIN)  # soft clip keeps chords clean

        track = self.track
        if track is not None:  # the imported song's own audio, outside the soft clip
            now = time.perf_counter()
            if track["pos"] is None and now >= track["at"]:
                track["pos"] = int((now - track["at"]) * SAMPLE_RATE)
            if track["pos"] is not None:
                chunk = track["data"][track["pos"]:track["pos"] + frames]
                out[:len(chunk)] += chunk * self.track_gain
                track["pos"] += frames
                if track["pos"] >= len(track["data"]):
                    self.track = None
            out = np.clip(out, -1.0, 1.0)
        out = out.astype(np.float32)
        outdata[:, 0] = out
        outdata[:, 1] = out
        capture = self.capture
        if capture is not None:
            capture.append(out.copy())
