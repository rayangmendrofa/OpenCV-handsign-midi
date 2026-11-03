# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on audio_analysis.py; mido for MIDI files; tkinter for file dialogs. Full credits: CREDITS.md

"""Turn a music file into a rhythm-game song: analyse it, let you check the beat, write the sheet.

Two kinds of source:
  * an audio file (WAV, MP3, FLAC, OGG): tempo, bar starts, key, chords, a melody estimate and
    kick/snare hits are detected (audio_analysis.py); the recording itself plays as the backing
  * a MIDI file: notes are exact; the chart follows its melody/chords/drums and the backing is
    synthesized from its chords and bass

Three charts:
  Chords   one sign per chord (both hands share up to 16 chords)
  Melody   one sign per note: the song's notes laid out low (left hand) to high (right hand)
  Rhythm   kick and snare on the left hand, hi-hat on the right
and three difficulties that set how many notes you play (Easy / Normal / Hard).

The Importer below drives the "Add a song" panel: analysis runs in the background, you can listen
with a click track, tap the tempo yourself, nudge the tempo and bar start, then create the song.
"""

import re
import shutil
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import audio_analysis as aa
from game import SONGS_DIR, parse_chord

AUDIO_DIR = SONGS_DIR / "audio"
AUDIO_TYPES = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif")
MIDI_TYPES = (".mid", ".midi")
CHARTS = ["Melody", "Chords", "Rhythm"]
DIFFICULTIES = ["Easy", "Normal", "Hard"]
NOTE_NAMES = aa.NOTE_NAMES
OUTPUT_LATENCY = 0.03   # seconds from scheduling a sound to hearing it (for tap tempo)
TRACK_CACHE = {}        # path -> decoded 44.1 kHz samples, shared with the game


def note_name(m):
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def track_samples(path):
    """The music file decoded for playback (mono, 44.1 kHz), cached."""
    key = str(Path(path).resolve())
    if key not in TRACK_CACHE:
        TRACK_CACHE[key] = aa.load(path, sr=44100)
    return TRACK_CACHE[key]


@dataclass
class Draft:
    """A song being prepared: everything the import panel shows and lets you correct."""
    source: Path
    kind: str                 # "audio" or "midi"
    title: str
    bpm: float
    first_beat: float         # seconds into the music where bar 1 begins
    duration: float
    key_root: int = 0
    key_minor: bool = False
    analysis: object = None   # audio_analysis.Analysis for audio sources
    notes: list = field(default_factory=list)   # MIDI sources: (start, length, pitch, velocity, channel)
    confidence: float = 0.0

    @property
    def beat(self):
        return 60.0 / self.bpm

    @property
    def key_name(self):
        return NOTE_NAMES[self.key_root] + (" minor" if self.key_minor else " major")

    def per_beat(self):
        """(chords per beat, melody per half beat, kick per half beat, snare per half beat) on the current grid."""
        if self.kind == "audio":
            a = self.analysis
            a.bpm, a.first_beat = self.bpm, self.first_beat
            aa.regrid(a)
            return a.chords, a.melody, a.kick, a.snare
        return _midi_grid(self)


def from_audio(path, progress=lambda text: None):
    a = aa.analyze(path, progress)
    return Draft(source=Path(path), kind="audio", title=_title(path), bpm=round(a.bpm, 2), first_beat=a.first_beat,
                 duration=a.duration, key_root=a.key_root, key_minor=a.key_minor, analysis=a,
                 confidence=a.confidence)


def from_midi(path, progress=lambda text: None):
    from midi_file import read_notes
    progress("Reading the MIDI file...")
    bpm, notes = read_notes(path)
    if not notes:
        raise ValueError("The MIDI file has no notes")
    pitched = [n for n in notes if n[4] != 9]
    chroma = np.zeros(12)
    for start, length, pitch, vel, ch in pitched:
        chroma[pitch % 12] += length * vel
    root, minor = aa._key(chroma) if chroma.any() else (0, False)
    beat = 60 / bpm
    first = min(n[0] for n in notes)
    first_beat = max(0.0, np.floor(first / (4 * beat)) * 4 * beat)  # bar containing the first note
    duration = max(n[0] + n[1] for n in notes)
    progress("Done")
    return Draft(source=Path(path), kind="midi", title=_title(path), bpm=round(bpm, 2), first_beat=first_beat,
                 duration=duration, key_root=root, key_minor=minor, notes=notes, confidence=1.0)


def load_draft(path, progress=lambda text: None):
    suffix = Path(path).suffix.lower()
    if suffix in MIDI_TYPES:
        return from_midi(path, progress)
    if suffix in AUDIO_TYPES:
        return from_audio(path, progress)
    raise ValueError(f"Unsupported file type {suffix}. Use {', '.join(AUDIO_TYPES + MIDI_TYPES)}")


def _title(path):
    return re.sub(r"[_\-]+", " ", Path(path).stem).strip().title() or "New song"


def _midi_grid(d):
    """Per-beat chords, per-half-beat melody (highest note) and drum hits from MIDI notes."""
    n_beats = max(0, int((d.duration - d.first_beat) / d.beat))
    half = d.first_beat + d.beat / 2 * np.arange(2 * n_beats + 1)
    pitched = [n for n in d.notes if n[4] != 9]
    drums = [n for n in d.notes if n[4] == 9]
    melody, kick, snare = [], [], []
    for a, b in zip(half[:-1], half[1:]):
        sounding = [p for s, ln, p, v, c in pitched if s < b - 0.01 and s + ln > a + 0.01]
        melody.append(max(sounding) if sounding else None)  # skyline: the highest note is the tune
        hits = [p for s, ln, p, v, c in drums if a - 0.03 <= s < b - 0.03]
        kick.append(1.0 if any(p in (35, 36) for p in hits) else 0.0)
        snare.append(1.0 if any(p in (37, 38, 39, 40) for p in hits) else 0.0)
    beat_chroma = []
    for i in range(n_beats):
        a, b = d.first_beat + i * d.beat, d.first_beat + (i + 1) * d.beat
        c = np.zeros(12)
        for s, ln, p, v, ch in pitched:
            overlap = min(b, s + ln) - max(a, s)
            if overlap > 0:
                c[p % 12] += overlap * v
        beat_chroma.append(c)
    chords = aa._chords(np.array(beat_chroma), d.key_root, d.key_minor) if beat_chroma else []
    return chords, melody, kick, snare


# ---------------------------------------------------------------- writing the sheet

def _group(values, size):
    """Most common non-None value in each group of `size`, or None."""
    out = []
    for i in range(0, len(values), size):
        chunk = [v for v in values[i:i + size] if v is not None]
        out.append(Counter(chunk).most_common(1)[0][0] if chunk else None)
    return out


def _holds(seq):
    """Tokens with '-' for a value that continues and '.' for silence."""
    out, prev = [], object()
    for v in seq:
        out.append("." if v is None else ("-" if v == prev else v))
        prev = v
    return out


def _bars(tokens, per_bar, key):
    """Sheet lines of 4 bars each: 'play: C - - - | G - - - | ...'."""
    lines = []
    for i in range(0, len(tokens), per_bar * 4):
        chunk = tokens[i:i + per_bar * 4]
        bars = [" ".join(chunk[j:j + per_bar]) for j in range(0, len(chunk), per_bar)]
        lines.append(f"{key}: " + " | ".join(bars) + " |")
    return lines


def _fold(note):
    """Move a note by octaves into C2-B5: sheet notes use octaves 0-5 (a name like C6 means a chord)."""
    while note >= 84:
        note -= 12
    while note < 36:
        note += 12
    return note


def _nearest_chord(name, kept):
    tones = set(n % 12 for n in parse_chord(name)[1:])
    return max(kept, key=lambda k: len(tones & set(n % 12 for n in parse_chord(k)[1:])))


def make_sheet(d, chart, difficulty):
    """The song sheet text for a draft."""
    chords, melody, kick, snare = d.per_beat()
    steps_per_beat = 2 if (chart != "Chords" and difficulty == "Hard") else 1
    per_bar = 4 * steps_per_beat
    signs, right, left, play = "Extended", [], [], {}

    if chart == "Chords":
        size = {"Easy": 4, "Normal": 2, "Hard": 1}[difficulty]   # beats per chord change
        seq = [c for c in _group(chords, size) for _ in range(size)]
        common = [c for c, _ in Counter(c for c in seq if c).most_common(16)]
        seq = [c if c in common or c is None else _nearest_chord(c, common) for c in seq]
        right, left = common[:8], common[8:16]
        play["play"] = _holds(seq)
    elif chart == "Melody":
        size = {"Easy": 4, "Normal": 2, "Hard": 1}[difficulty]   # half beats per note
        notes = _group([None if n is None else _fold(n) for n in melody], size)
        seq = [n for n in notes for _ in range(size * steps_per_beat // 2)]
        used = sorted({n for n in seq if n is not None})
        if len(used) > 16:  # keep the 16 most frequent notes; others move to the nearest kept one
            keep = sorted(n for n, _ in Counter(n for n in seq if n).most_common(16))
            seq = [None if n is None else min(keep, key=lambda k: abs(k - n)) for n in seq]
            used = keep
        low = used[:len(used) // 2] if len(used) > 1 else []
        high = used[len(used) // 2:]
        left, right = [note_name(n) for n in low], [note_name(n) for n in high]
        play["play"] = _holds([note_name(n) if n is not None else None for n in seq])
    else:  # Rhythm
        signs = "Basic"
        step = 2 // steps_per_beat           # half-beat values per step
        k = [max(kick[i:i + step]) for i in range(0, len(kick), step)]
        s = [max(snare[i:i + step]) for i in range(0, len(snare), step)]
        threshold = {"Easy": 0.5, "Normal": 0.35, "Hard": 0.25}[difficulty]
        left_seq, right_seq = [], []
        for i, (kv, sv) in enumerate(zip(k, s)):
            on_beat = i % steps_per_beat == 0
            if max(kv, sv) >= threshold and (on_beat or difficulty == "Hard"):
                left_seq.append("Kick" if kv >= sv else "Snare")
                right_seq.append(".")
            else:
                left_seq.append(".")
                right_seq.append("Hat" if difficulty != "Easy" and on_beat else ".")
        left, right = ["Kick", "Snare"], ["Hat"]
        play["play l"], play["play r"] = left_seq, right_seq

    lines = [f'# Generated by Gesture Music from "{d.source.name}" on {time.strftime("%Y-%m-%d")}.',
             "# Tempo, bar start, key and notes were detected automatically. Check them in the game",
             "# and edit this file freely (see songs/README.md).",
             f"title: {d.title}", f"bpm: {d.bpm:.2f}", "mode: Song", f"signs: {signs}", "beats per bar: 4",
             f"steps per beat: {steps_per_beat}", f"# chart: {chart}, {difficulty}; key {d.key_name}"]
    if d.kind == "audio":
        lines += ["count in: 0", "metronome: off", f"audio: audio/{d.source.name}", f"audio start: {d.first_beat:.3f}"]
    else:
        lines += ["count in: 4", "metronome: off"]
    lines += ["", "# What each sign plays (1 finger, 2 fingers, ... see songs/README.md)"]
    if right:
        lines.append("right: " + "  ".join(right))
    if left:
        lines.append("left:  " + "  ".join(left))
    lines.append("")
    for key, tokens in play.items():
        lines += _bars(tokens, per_bar, key)
    if d.kind == "midi":  # synthesized backing: chords per bar and their roots in the bass
        bar_chords = _group(chords, 4)
        steps = [c for c in bar_chords for _ in range(per_bar)]
        lines += [""] + _bars(_holds(steps), per_bar, "backing chords")
        roots = [None if c is None else c.rstrip("m") + "2" for c in bar_chords]
        lines += _bars(_holds([r for r in roots for _ in range(per_bar)]), per_bar, "backing bass")
    return "\n".join(lines) + "\n"


def slug(title):
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "song"


def create_song(d, chart, difficulty):
    """Write songs/<title>.txt (and copy the audio into songs/audio/). Returns the sheet path."""
    SONGS_DIR.mkdir(exist_ok=True)
    if d.kind == "audio":
        AUDIO_DIR.mkdir(exist_ok=True)
        target = AUDIO_DIR / d.source.name
        if target.resolve() != d.source.resolve():
            shutil.copy2(d.source, target)
    name = slug(d.title)
    path = SONGS_DIR / f"{name}.txt"
    n = 2
    while path.exists():
        path = SONGS_DIR / f"{name}_{n}.txt"
        n += 1
    path.write_text(make_sheet(d, chart, difficulty), encoding="utf-8")
    return path


# ---------------------------------------------------------------- the import panel's logic

class Importer:
    """State behind the 'Add a song' panel. All methods are safe to call from the UI thread."""

    def __init__(self, play):
        self.play = play                  # router.play: sends events to the synth (and MIDI)
        self.state = "idle"               # idle | analysing | ready | error
        self.message = ""
        self.draft = None
        self.chart, self.difficulty = "Melody", "Normal"
        self.previewing = False
        self.preview_start = 0.0          # perf time when the music's 0 s plays
        self.taps = []
        self.lock = threading.Lock()
        self.schedule = []
        threading.Thread(target=self._run, daemon=True).start()

    def pick_file(self):
        """Native file dialog; returns a path or None."""
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Choose a song", parent=root,
            filetypes=[("Music and MIDI", " ".join("*" + s for s in AUDIO_TYPES + MIDI_TYPES)),
                       ("Audio", " ".join("*" + s for s in AUDIO_TYPES)),
                       ("MIDI", " ".join("*" + s for s in MIDI_TYPES))])
        root.destroy()
        return path or None

    def open(self, path):
        self.stop_preview()
        self.state, self.message, self.draft, self.taps = "analysing", "Starting...", None, []

        def work():
            try:
                draft = load_draft(path, progress=lambda text: setattr(self, "message", text))
                if draft.kind == "audio":
                    self.message = "Preparing playback..."
                    track_samples(path)
                self.draft, self.state, self.message = draft, "ready", ""
            except Exception as e:  # unreadable file, too short, etc.
                self.state, self.message = "error", f"Couldn't read that file: {e}"
        threading.Thread(target=work, daemon=True).start()

    # -- corrections
    def set_bpm(self, bpm):
        if self.draft:
            self.draft.bpm = round(max(40.0, min(240.0, bpm)), 2)

    def shift_start(self, seconds):
        if self.draft:
            self.draft.first_beat = max(0.0, self.draft.first_beat + seconds)

    def tap(self, now):
        """Tap along on the downbeat first, then every beat. 4+ taps set the tempo and bar start."""
        if not (self.draft and self.previewing):
            return
        self.taps.append(now - self.preview_start - OUTPUT_LATENCY)
        taps = np.array(self.taps[-16:])
        if len(taps) >= 4:
            period = float(np.median(np.diff(taps)))
            if period <= 0.2:
                return
            idx = np.round((taps - taps[0]) / period)
            slope, intercept = np.polyfit(idx, taps, 1)
            self.draft.bpm = round(60 / slope, 2)
            start = intercept - idx[0] * slope
            bar = 4 * slope
            self.draft.first_beat = float(start - np.floor(start / bar) * bar)
            self.message = f"Tapped tempo: {self.draft.bpm:.1f} BPM"

    # -- listening with a click track
    def preview(self, seconds=20.0):
        if self.previewing:
            self.stop_preview()
            return
        d = self.draft
        if not d:
            return
        begin = max(0.0, d.first_beat - 4 * d.beat)
        now = time.perf_counter() + 0.15
        self.preview_start = now - begin
        events = []
        if d.kind == "audio":
            data = track_samples(d.source)
            events.append((now, ("track", data[int(begin * 44100):], now)))
        else:  # MIDI: play its notes on the synth
            for i, (s, ln, p, v, ch) in enumerate(d.notes):
                if begin <= s < begin + seconds and ch != 9:
                    events.append((self.preview_start + s, ("note_on", ("preview", i), p, 0.6 * v, "game")))
                    events.append((self.preview_start + s + ln, ("note_off", ("preview", i))))
        k = 0
        while d.first_beat + (k - 4) * d.beat < begin + seconds:  # clicks on the grid, accent on bar 1
            t = d.first_beat + (k - 4) * d.beat
            if t >= begin:
                events.append((self.preview_start + t, ("drum", "rim", 0.8 if k % 4 == 0 else 0.45)))
            k += 1
        with self.lock:
            self.schedule = sorted(events, key=lambda e: e[0])
        self.previewing, self.taps = True, []
        self.preview_until = now + seconds

    def stop_preview(self):
        with self.lock:
            self.schedule = []
        if self.previewing:
            self.play(("track_stop",))
            self.play(("all_off", "preview"))
        self.previewing = False

    def create(self):
        self.stop_preview()
        path = create_song(self.draft, self.chart, self.difficulty)
        self.state, self.draft = "idle", None
        return path

    def _run(self):
        while True:
            time.sleep(0.002)
            now = time.perf_counter()
            due = []
            with self.lock:
                while self.schedule and self.schedule[0][0] <= now:
                    due.append(self.schedule.pop(0)[1])
            for ev in due:
                self.play(ev)
            if self.previewing and now > self.preview_until:
                self.stop_preview()
