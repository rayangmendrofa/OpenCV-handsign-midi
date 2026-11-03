# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on soundfile / libsndfile (BSD-3 / LGPL); beat tracking after D. Ellis (2007); key profiles after Krumhansl & Kessler (1982); NumPy. Full credits: CREDITS.md

"""Find the tempo, beats, key, chords and (roughly) the melody of a music file.

Pure NumPy, plus soundfile for decoding (WAV, MP3, FLAC, OGG...). The steps:
  1. onset strength: how much the spectrum suddenly grows, frame by frame (spectral flux)
  2. tempo: the strongest repetition period in that curve (autocorrelation, with a preference
     for 70-160 BPM so half/double tempo is less likely)
  3. beats: dynamic programming that lines beats up with onsets while keeping the tempo steady
     (Ellis 2007); then a straight-line fit gives one steady BPM and first-beat time for the chart
  4. bar starts: the beat position (of 4) with the strongest bass onsets
  5. key: the averaged pitch-class profile matched against major/minor key profiles
     (Krumhansl-Schmuckler)
  6. chords: each beat's pitch-class profile matched against the 24 major/minor triads, smoothed
     so chords only change when the evidence is clear
  7. melody (approximate on full mixes): the strongest pitch between G3 and C6 by harmonic sum
"""

from dataclasses import dataclass, field

import numpy as np
import soundfile as sf

SR = 22050
N_FFT = 2048
HOP = 512
FRAME_CENTER = N_FFT / 2 / SR  # an onset shows up when it reaches the middle of the analysis window
DOUBLE_TEMPO_PULSE = 0.3      # see _tempo: share of the slow pulse that a double-speed pulse needs
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass
class Analysis:
    duration: float
    bpm: float
    first_beat: float            # seconds: the first bar's downbeat
    beats: list                  # detected beat times, seconds
    key_root: int                # pitch class 0-11
    key_minor: bool
    chords: list = field(default_factory=list)   # per beat: chord name like "Am"
    melody: list = field(default_factory=list)   # per half beat: MIDI note or None
    confidence: float = 0.0      # 0..1, how clearly the beat stands out
    kick: list = field(default_factory=list)     # per half beat: bass-hit strength 0..1
    snare: list = field(default_factory=list)    # per half beat: snare-band hit strength 0..1
    features: object = None                      # spectral data for regrid() after a tempo correction

    @property
    def key_name(self):
        return NOTE_NAMES[self.key_root] + (" minor" if self.key_minor else " major")


def load(path, sr=SR):
    """Mono float32 at the given sample rate."""
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate != sr:
        if rate > sr:  # crude low-pass before downsampling, to limit aliasing
            k = int(round(rate / sr))
            if k > 1:
                mono = np.convolve(mono, np.ones(k) / k, mode="same")
        n = int(len(mono) * sr / rate)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype(np.float32)
    return mono


def _spectrogram(y):
    """Magnitude spectrogram (frames x bins), computed in chunks to keep memory low."""
    window = np.hanning(N_FFT).astype(np.float32)
    n_frames = 1 + max(0, (len(y) - N_FFT) // HOP)
    out = np.empty((n_frames, N_FFT // 2 + 1), np.float32)
    for start in range(0, n_frames, 1024):
        idx = np.arange(start, min(n_frames, start + 1024))[:, None] * HOP + np.arange(N_FFT)[None, :]
        out[start:start + len(idx)] = np.abs(np.fft.rfft(y[idx] * window, axis=1))
    return out


def _onsets(mag, freqs, lo=0, hi=None):
    """Spectral flux in a frequency band: summed increases of log-magnitude, local mean removed."""
    band = (freqs >= lo) & (freqs < (hi or freqs[-1] + 1))
    logm = np.log1p(100 * mag[:, band])
    flux = np.maximum(np.diff(logm, axis=0, prepend=logm[:1]), 0).sum(axis=1)
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")
    flux = np.maximum(flux, 0)
    return flux / (flux.max() + 1e-9)


def _tempo(env, fps):
    lags = np.arange(int(fps * 60 / 220), int(fps * 60 / 50) + 1)
    ac = np.array([np.dot(env[:-lag], env[lag:]) for lag in lags])
    bpms = 60 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpms / 115) / 0.9) ** 2)  # prefer 70-160 BPM
    score = ac * prior
    best = int(np.argmax(score))
    if 0 < best < len(score) - 1:  # parabolic refinement between lags
        a, b, c = score[best - 1:best + 2]
        shift = 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
    else:
        shift = 0.0
    lag = lags[best] + shift
    confidence = float(score[best] / (np.mean(score) + 1e-9))
    bpm = 60 * fps / lag
    # Kicks on beats 1 and 3 repeat every two beats and can outweigh the beat itself (a plain
    # rock beat reads at half speed). If the tempo is slow and there is also a clear pulse at
    # double speed, the double is almost always the beat people tap.
    half = int(np.argmin(np.abs(lags - lag / 2)))
    if bpm < 90 and bpm * 2 <= 180 and ac[half] >= DOUBLE_TEMPO_PULSE * ac[best]:
        bpm *= 2
    return bpm, min(1.0, (confidence - 1) / 3)


def _track_beats(env, period, tightness=100):
    """Ellis dynamic-programming beat tracker. Returns beat frame indices."""
    n = len(env)
    score = env.astype(np.float64).copy()
    back = np.full(n, -1)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    offsets = np.arange(lo, hi + 1)
    penalty = -tightness * np.log(offsets / period) ** 2
    for t in range(hi, n):
        cand = score[t - offsets] + penalty
        k = int(np.argmax(cand))
        score[t] = env[t] + cand[k]
        back[t] = t - offsets[k]
    t = int(np.argmax(score[-int(period * 2):]) + n - int(period * 2))
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    return np.array(beats[::-1])


def _chroma(mag, freqs):
    """12 pitch-class energies per frame (55 Hz - 2 kHz)."""
    band = (freqs >= 55) & (freqs <= 2000)
    pcs = (np.round(12 * np.log2(freqs[band] / 440.0) + 69).astype(int)) % 12
    chroma = np.zeros((mag.shape[0], 12), np.float32)
    power = mag[:, band] ** 2
    for pc in range(12):
        chroma[:, pc] = power[:, pcs == pc].sum(axis=1)
    return chroma / (chroma.sum(axis=1, keepdims=True) + 1e-9)


def _key(chroma_total):
    best = (-2.0, 0, False)
    for root in range(12):
        for minor, profile in ((False, MAJOR_PROFILE), (True, MINOR_PROFILE)):
            r = np.corrcoef(chroma_total, np.roll(profile, root))[0, 1]
            if r > best[0]:
                best = (r, root, minor)
    return best[1], best[2]


def _chords(beat_chroma, key_root, key_minor, change_penalty=0.08):
    """Best major/minor triad per beat, smoothed with a Viterbi pass that discourages changes."""
    names, templates = [], []
    for root in range(12):
        for minor in (False, True):
            t = np.zeros(12)
            t[[root, (root + (3 if minor else 4)) % 12, (root + 7) % 12]] = 1
            names.append(NOTE_NAMES[root] + ("m" if minor else ""))
            templates.append(t / np.linalg.norm(t))
    templates = np.array(templates)
    scale = {(s + key_root) % 12 for s in ([0, 2, 3, 5, 7, 8, 10] if key_minor else [0, 2, 4, 5, 7, 9, 11])}
    in_key = np.array([set(np.nonzero(t)[0]) <= scale for t in templates], dtype=float)
    norm = beat_chroma / (np.linalg.norm(beat_chroma, axis=1, keepdims=True) + 1e-9)
    sim = norm @ templates.T + 0.04 * in_key  # small bonus for chords that belong to the key
    n, k = sim.shape
    score, back = sim[0].copy(), np.zeros((n, k), int)
    for i in range(1, n):
        stay = score
        move = score.max() - change_penalty
        back[i] = np.where(stay >= move, np.arange(k), int(np.argmax(score)))
        score = np.maximum(stay, move) + sim[i]
    path = [int(np.argmax(score))]
    for i in range(n - 1, 0, -1):
        path.append(back[i][path[-1]])
    return [names[j] for j in path[::-1]]


def _melody(mag, freqs, times, fps):
    """Strongest pitch per time step between G3 and C6, or None when nothing stands out."""
    midis = np.arange(55, 84)  # G3-B5 (sheets read C6 as a chord, so notes stay below it)
    out = []
    for a, b in zip(times[:-1], times[1:]):
        fa = max(0, int((a - FRAME_CENTER) * fps))
        fb = max(fa + 1, int((b - FRAME_CENTER) * fps))
        spec = mag[fa:fb].mean(axis=0) if fb <= len(mag) else None
        if spec is None or not spec.any():
            out.append(None)
            continue
        sal = np.zeros(len(midis))
        for i, m in enumerate(midis):
            f0 = 440.0 * 2 ** ((m - 69) / 12)
            # fundamental weighted most: summing many harmonics favours the octave below
            for h, w in ((1, 1.0), (2, 0.5), (3, 0.3)):
                bin_ = int(round(f0 * h * N_FFT / SR))
                if bin_ < len(spec):
                    sal[i] += w * spec[max(0, bin_ - 1):bin_ + 2].max()
        strong = np.nonzero(sal >= 0.6 * sal.max())[0]
        best = int(strong.max())  # the melody is usually the highest strong voice
        out.append(int(midis[best]) if sal[best] > 2.5 * (np.median(sal) + 1e-9) else None)
    for i in range(1, len(out) - 1):  # remove single-step blips
        if out[i - 1] is not None and out[i - 1] == out[i + 1] and out[i] != out[i - 1]:
            out[i] = out[i - 1]
    return out


def analyze(path, progress=lambda text: None):
    progress("Reading the file...")
    y = load(path)
    duration = len(y) / SR
    if duration < 5:
        raise ValueError("The music is shorter than 5 seconds")
    progress("Finding onsets...")
    mag = _spectrogram(y)
    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    fps = SR / HOP
    env = _onsets(mag, freqs)

    def frame(t):  # analysis frame for a time in seconds
        return max(0, int((t - FRAME_CENTER) * fps))
    progress("Finding the tempo...")
    bpm, confidence = _tempo(env, fps)
    progress("Following the beat...")
    frames = _track_beats(env, 60 * fps / bpm)
    beats = frames / fps + FRAME_CENTER
    if len(beats) >= 8:  # one steady tempo and phase that best fits all detected beats
        idx = np.arange(len(beats))
        slope, intercept = np.polyfit(idx, beats, 1)
        bpm, grid = 60 / slope, intercept + slope * idx
    else:
        grid = beats
    # Bar starts: the beat position with the strongest bass onsets
    bass = _onsets(mag, freqs, 30, 150)
    strength = [sum(bass[min(len(bass) - 1, frame(t))] for t in grid[k::4]) for k in range(4)]
    downbeat = int(np.argmax(strength))
    first_beat = float(grid[downbeat]) if len(grid) > downbeat else 0.0
    period = 60 / bpm
    while first_beat - 4 * period >= 0:  # earliest bar start (same beat-of-bar) inside the music
        first_beat -= 4 * period
    progress("Finding the key, chords and melody...")
    chroma = _chroma(mag, freqs)
    key_root, key_minor = _key(chroma.sum(axis=0))
    feats = Features(mag=mag, freqs=freqs, chroma=chroma, bass=bass, snare=_onsets(mag, freqs, 1500, 5000),
                     duration=duration)
    a = Analysis(duration=duration, bpm=float(bpm), first_beat=max(0.0, first_beat), beats=list(map(float, beats)),
                 key_root=key_root, key_minor=key_minor, confidence=max(0.0, confidence), features=feats)
    regrid(a)
    progress("Done")
    return a


@dataclass
class Features:
    """What the per-beat readings are computed from, kept so a corrected tempo can be re-read quickly."""
    mag: np.ndarray
    freqs: np.ndarray
    chroma: np.ndarray
    bass: np.ndarray
    snare: np.ndarray
    duration: float


def regrid(a):
    """(Re)compute chords per beat, melody and drum hits per half beat on a's current tempo grid."""
    f = a.features
    fps = SR / HOP
    period = 60 / a.bpm

    def frame(t):
        return max(0, int((t - FRAME_CENTER) * fps))
    n_beats = max(0, int((f.duration - a.first_beat) / period))
    beat_times = a.first_beat + period * np.arange(n_beats + 1)
    beat_chroma = np.array([f.chroma[frame(x):max(frame(x) + 1, frame(y))].mean(axis=0)
                            for x, y in zip(beat_times[:-1], beat_times[1:])])
    a.chords = _chords(beat_chroma, a.key_root, a.key_minor) if len(beat_chroma) else []
    half = a.first_beat + period / 2 * np.arange(2 * n_beats + 1)
    a.melody = _melody(f.mag, f.freqs, half, fps)

    def hit(env, t):  # strongest onset within a frame of the half beat
        i = frame(t)
        return float(env[max(0, i - 1):i + 2].max()) if i < len(env) else 0.0
    a.kick = [hit(f.bass, t) for t in half[:-1]]
    a.snare = [hit(f.snare, t) for t in half[:-1]]
    return a
