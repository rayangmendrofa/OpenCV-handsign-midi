# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on NumPy synthesis; General MIDI drum map. Full credits: CREDITS.md

"""Drum kit: synthesized by default, replaced by your own samples/<name>.wav if present."""

import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
SAMPLES_DIR = Path(__file__).parent / "samples"

DRUMS = ["kick", "snare", "hat", "open_hat", "clap", "tom_low", "tom_high", "crash",
         "ride", "rim", "cowbell", "shaker"]
LABELS = {
    "kick": "Kick", "snare": "Snare", "hat": "Hat", "open_hat": "Open hat",
    "clap": "Clap", "tom_low": "Tom lo", "tom_high": "Tom hi", "crash": "Crash",
    "ride": "Ride", "rim": "Rim", "cowbell": "Cowbell", "shaker": "Shaker",
}
# General MIDI drum notes (channel 10) so drums map correctly in any DAW/synth
GM_NOTES = {
    "kick": 36, "snare": 38, "hat": 42, "open_hat": 46,
    "clap": 39, "tom_low": 45, "tom_high": 50, "crash": 49,
    "ride": 51, "rim": 37, "cowbell": 56, "shaker": 70,
}

_rng = np.random.default_rng(7)


def _t(seconds):
    return np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE


def _hiss(n):
    """Bright noise: white noise through a crude high-pass (first difference)."""
    return np.diff(_rng.uniform(-1, 1, n + 1))


def _sweep(f_start, f_end, seconds, decay):
    """Sine whose pitch drops quickly: the core of kicks and toms."""
    t = _t(seconds)
    freq = f_end + (f_start - f_end) * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t * decay)


def synth_kit():
    kit = {}
    t = _t(0.5)
    kit["kick"] = _sweep(160, 45, 0.5, 7) + 0.3 * _hiss(len(t)) * np.exp(-t * 200)
    t = _t(0.3)
    kit["snare"] = 0.6 * _hiss(len(t)) * np.exp(-t * 18) + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 20)
    t = _t(0.08)
    kit["hat"] = _hiss(len(t)) * np.exp(-t * 60)
    t = _t(0.5)
    kit["open_hat"] = _hiss(len(t)) * np.exp(-t * 7)
    t = _t(0.35)
    bursts = sum((t >= d) * np.exp(-np.clip(t - d, 0, None) * 150) for d in (0.0, 0.011, 0.022))
    kit["clap"] = _hiss(len(t)) * (bursts + 0.4 * np.exp(-t * 12))
    kit["tom_low"] = _sweep(140, 90, 0.45, 8)
    kit["tom_high"] = _sweep(230, 150, 0.35, 9)
    t = _t(1.8)
    kit["crash"] = _hiss(len(t)) * np.exp(-t * 2.5)
    t = _t(1.4)  # ride: inharmonic metal partials over a soft wash
    bell = sum(np.sin(2 * np.pi * f * t) for f in (523, 811, 1325, 2010, 3150))
    kit["ride"] = 0.5 * bell * np.exp(-t * 3) + 0.4 * _hiss(len(t)) * np.exp(-t * 4)
    t = _t(0.06)  # rim click; also the rhythm game's metronome
    kit["rim"] = np.sin(2 * np.pi * 1700 * t) * np.exp(-t * 80) + 0.4 * _hiss(len(t)) * np.exp(-t * 150)
    t = _t(0.3)
    kit["cowbell"] = (np.sign(np.sin(2 * np.pi * 540 * t)) + np.sign(np.sin(2 * np.pi * 800 * t))) * np.exp(-t * 12)
    t = _t(0.15)
    kit["shaker"] = _hiss(len(t)) * np.minimum(1, t / 0.01) * np.exp(-t * 25)

    fade = int(0.005 * SAMPLE_RATE)
    for name, x in kit.items():
        x = x / np.max(np.abs(x)) * 0.9
        x[-fade:] *= np.linspace(1, 0, fade)
        kit[name] = x.astype(np.float32)
    return kit


def load_wav(path):
    """Load a 16-bit PCM WAV as mono float32 at SAMPLE_RATE."""
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM WAV files are supported")
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        data = data.reshape(-1, w.getnchannels()).mean(axis=1)
        rate = w.getframerate()
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return data.astype(np.float32)


def load_kit():
    kit = synth_kit()
    for name in DRUMS:
        path = SAMPLES_DIR / f"{name}.wav"
        if path.exists():
            try:
                kit[name] = load_wav(path)
                print(f"Loaded drum sample {path.name}")
            except Exception as e:
                print(f"Skipping {path.name}: {e}")
    return kit
