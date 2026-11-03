# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on the Python standard library. Full credits: CREDITS.md

"""Rhythm game: follow a timed song sheet by making the right hand sign on the beat.

Song sheets are plain text files in songs/ (see songs/README.md). Notes scroll toward a
hit line; make the matching sign as a note reaches it. A backing track and metronome
play along through the same synth/MIDI router as your hands. This module holds the game
logic only; ui.py draws the lanes.
"""

import json
import math
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from drums import DRUMS, LABELS

SONGS_DIR = Path(__file__).parent / "songs"
SCORES_PATH = Path(__file__).parent / "scores.json"

# Timing windows around each note, in seconds. Generous because a webcam only sees
# a new frame every 33-100 ms.
PERFECT_WINDOW = 0.10
GOOD_WINDOW = 0.22
BACKING_VELOCITY = 0.5
CLICK_VELOCITY = 0.35

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
CHORD_QUALITIES = {
    "": [0, 4, 7], "m": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8],
    "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10], "m7b5": [0, 3, 6, 10], "dim7": [0, 3, 6, 9], "mmaj7": [0, 3, 7, 11],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "sus": [0, 5, 7], "7sus4": [0, 5, 7, 10], "7sus": [0, 5, 7, 10],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14], "9": [0, 4, 7, 10, 14], "m9": [0, 3, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
}
# Longest names first, so "m7b5" isn't read as "m7" followed by junk
_QUALITY_RE = "|".join(sorted((re.escape(q) for q in CHORD_QUALITIES if q), key=len, reverse=True))


def norm(text):
    """Loose match for sheet tokens: 'Open hat', 'open_hat' and 'openhat' are the same."""
    return re.sub(r"[\s_]", "", text.lower())


DRUM_LOOKUP = {norm(k): k for k in DRUMS} | {norm(v): k for k, v in LABELS.items()}


def parse_note(token):
    """Single note like 'C4' or 'F#2'. Octaves 0-5 only, so 'E6' or 'G7' read as chords."""
    m = re.fullmatch(r"([A-Ga-g])([#b]?)([0-5])", token)
    if not m:
        return None
    letter, accidental, octave = m.groups()
    return 12 * (int(octave) + 1) + PITCH[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental]


def parse_chord(token):
    """Chord name -> [bass, chord tones...] as MIDI notes, e.g. 'Am', 'F7sus', 'D#m6/F#'.

    Chord tones sit between G3 and F#5 so every chord has a similar register; the bass
    (the slash note if there is one, else the root) sits between E2 and D#3.
    """
    m = re.fullmatch(rf"([A-G])([#b]?)({_QUALITY_RE})?(?:/([A-G])([#b]?))?", token)
    if not m:
        return None
    letter, accidental, quality, bass_letter, bass_accidental = m.groups()
    shift = {"#": 1, "b": -1, "": 0, None: 0}
    pc = (PITCH[letter] + shift[accidental]) % 12
    root = 60 + pc if pc <= 6 else 48 + pc
    bass_pc = (PITCH[bass_letter] + shift[bass_accidental]) % 12 if bass_letter else pc
    bass = 36 + bass_pc if 36 + bass_pc >= 40 else 48 + bass_pc
    return [bass] + [root + i for i in CHORD_QUALITIES[quality or ""]]


def expand_repeats(tokens):
    """'( a b ) x3' -> a b a b a b. Groups can be nested; the xN is optional."""
    out, i = [], 0
    while i < len(tokens):
        if tokens[i] == "(":
            depth, j = 1, i + 1
            while j < len(tokens) and depth:
                depth += {"(": 1, ")": -1}.get(tokens[j], 0)
                j += 1
            if depth:
                raise ValueError("a '(' has no matching ')'")
            group, times = expand_repeats(tokens[i + 1:j - 1]), 1
            if j < len(tokens) and re.fullmatch(r"[xX]\d+", tokens[j]):
                times, j = int(tokens[j][1:]), j + 1
            out += group * times
            i = j
        elif tokens[i] == ")":
            raise ValueError("a ')' has no matching '('")
        else:
            out.append(tokens[i])
            i += 1
    return out


def backing_sound(token):
    """A backing-track token as ('drum', name) or ('notes', [midi...]) or None."""
    if norm(token) in DRUM_LOOKUP:
        return "drum", DRUM_LOOKUP[norm(token)]
    note = parse_note(token)
    if note is not None:
        return "notes", [note]
    chord = parse_chord(token)
    return ("notes", chord) if chord else None


def to_events(tokens):
    """Tokens -> [start_step, length_steps, token]. '-' holds the previous sound, '.' is a rest."""
    events = []
    for i, tok in enumerate(tokens):
        if tok == "-":
            if events:
                events[-1][1] += 1
        elif tok != ".":
            events.append([i, 1, tok])
    return events


@dataclass
class Song:
    path: Path
    title: str
    bpm: float
    mode: str
    scale: str
    root: int
    signs: str
    beats_per_bar: int
    steps_per_beat: int
    count_in: int
    metronome: bool
    play: dict      # "play", "play r", "play l" -> tokens
    backing: dict   # "backing ..." -> tokens
    pads: dict      # mode Song: {"R": [sound per sign], "L": [...]}
    audio: str = None        # music file (relative to songs/) played as the backing
    audio_start: float = 0.0  # seconds into that file where bar 1 begins

    @property
    def step(self):
        return 60.0 / self.bpm / self.steps_per_beat

    @property
    def beat(self):
        return 60.0 / self.bpm


def load_song(path):
    meta, play, backing, pads = {}, {}, {}, {}
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        # Comments start with "# " (a # inside a chord name like D#m is not a comment)
        line = re.split(r"(?:^|\s)#(?:\s|$)", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{Path(path).name} line {line_no}: expected 'name: value'")
        key = " ".join(key.lower().split())
        try:
            tokens = expand_repeats([t for t in value.split() if t != "|"])
        except ValueError as e:
            raise ValueError(f"{Path(path).name} line {line_no}: {e}")
        if key.startswith("play"):
            play.setdefault(key, []).extend(tokens)
        elif key.startswith("backing"):
            backing.setdefault(key, []).extend(tokens)
        elif key in ("right", "left"):
            for tok in tokens:
                if backing_sound(tok) is None:
                    raise ValueError(f"{Path(path).name} line {line_no}: '{tok}' isn't a chord, note or drum")
            pads[key[0].upper()] = tokens
        else:
            meta[key] = value.strip()
    if not play:
        raise ValueError(f"{Path(path).name}: needs at least one 'play:' line")
    return Song(
        path=Path(path),
        title=meta.get("title", Path(path).stem),
        bpm=float(meta.get("bpm", 90)),
        mode=meta.get("mode", "Notes").capitalize(),
        scale=meta.get("scale", "Major").capitalize(),
        root=int(meta.get("root", 60)),
        signs=meta.get("signs", "Basic").capitalize(),
        beats_per_bar=int(meta.get("beats per bar", 4)),
        steps_per_beat=int(meta.get("steps per beat", 1)),
        count_in=int(meta.get("count in", 4)),
        metronome=meta.get("metronome", "on").lower() in ("on", "yes", "true"),
        play=play,
        backing=backing,
        pads=pads,
        audio=meta.get("audio") or None,
        audio_start=float(meta.get("audio start", 0) or 0),
    )


@dataclass
class Note:
    time: float     # seconds after the song starts
    length: float
    hand: str
    slot: int
    label: str      # what it plays, e.g. "Am"
    sign: str       # how to play it, e.g. "4 fingers"
    result: str = ""
    error: float = 0.0


class RhythmGame:
    def __init__(self, dispatch):
        self.dispatch = dispatch          # callable(event): synth + MIDI (not recorded by the looper)
        self.paths = []
        self.index = 0
        self.refresh()
        self.state = "idle"               # idle | playing | results
        self.song, self.notes, self.message = None, [], ""
        self.offset = 0.0                 # camera latency compensation, seconds
        self.scores = self._load_scores()
        self.lock = threading.Lock()
        self.schedule, self.next_event = [], 0
        threading.Thread(target=self._run, daemon=True).start()

    # ---- song selection ----

    def refresh(self, select=None):
        """Re-scan songs/ (after adding a song); optionally select a sheet by path."""
        self.paths = sorted(SONGS_DIR.glob("*.txt"))
        if select is not None and Path(select) in self.paths:
            self.index = self.paths.index(Path(select))
        self.index = min(self.index, max(0, len(self.paths) - 1))

    @property
    def selected_title(self):
        if not self.paths:
            return "No songs yet: add one"
        try:
            return load_song(self.paths[self.index]).title
        except (ValueError, OSError) as e:
            return f"error: {e}"

    def next_song(self):
        if self.state != "playing" and self.paths:
            self.index = (self.index + 1) % len(self.paths)
            self.state = "idle"

    def load_selected(self):
        if not self.paths:
            raise ValueError("No songs found in the songs/ folder")
        return load_song(self.paths[self.index])

    # ---- playing ----

    def start(self, song, lookup, sign_names, now):
        """lookup(token, hand or None) -> (hand, slot, label) or raises ValueError."""
        notes = []
        for key, tokens in song.play.items():
            hand = {"play r": "R", "play l": "L"}.get(key)
            for start, length, tok in to_events(tokens):
                h, slot, label = lookup(tok, hand)
                notes.append(Note(start * song.step, length * song.step, h, slot, label, sign_names[slot]))
        notes.sort(key=lambda n: n.time)

        song_start = now + song.count_in * song.beat
        schedule = []
        if song.audio:  # the song's own recording is the backing; bar 1 lines up with audio_start
            from songmaker import track_samples
            path = SONGS_DIR / song.audio
            if not path.exists():
                raise ValueError(f"The music file {song.audio} is missing from the songs folder")
            # start the music early enough that the first notes can be seen scrolling in
            music_at = max(now + 0.3, now + 2.0 - song.audio_start, song_start - song.audio_start)
            song_start = music_at + song.audio_start
            schedule.append((now, ("track", track_samples(path), music_at)))
        steps = max(len(t) for t in list(song.play.values()) + list(song.backing.values()))
        self.length = steps * song.step
        for i in range(song.count_in):  # count-in clicks, accent on the first
            schedule.append((song_start - (song.count_in - i) * song.beat, ("drum", "rim", 0.7 if i == 0 else 0.5)))
        if song.metronome:
            beats = math.ceil(self.length / song.beat)
            for b in range(beats):
                vel = CLICK_VELOCITY * (1.4 if b % song.beats_per_bar == 0 else 1.0)
                schedule.append((song_start + b * song.beat, ("drum", "rim", vel)))
        for ti, tokens in enumerate(song.backing.values()):
            for ei, (start, length, tok) in enumerate(to_events(tokens)):
                sound = backing_sound(tok)
                if sound is None:
                    raise ValueError(f"Backing token '{tok}' isn't a drum, note (like C4) or chord (like Am)")
                t0 = song_start + start * song.step
                if sound[0] == "drum":
                    schedule.append((t0, ("drum", sound[1], BACKING_VELOCITY + 0.2)))
                    continue
                for k, midi in enumerate(sound[1]):
                    vid = ("game", ti, ei, k)
                    schedule.append((t0, ("note_on", vid, midi, BACKING_VELOCITY * 0.7, "game")))
                    schedule.append((t0 + length * song.step - 0.03, ("note_off", vid)))
        schedule.sort(key=lambda e: e[0])

        with self.lock:
            self.song, self.notes, self.start_time = song, notes, song_start
            self.schedule, self.next_event = schedule, 0
            self.score = self.combo = self.max_combo = 0
            self.counts = {"perfect": 0, "good": 0, "miss": 0}
            self.feedback = {}
            self.bar_texts = self._bar_texts(song)
            self.state = "playing"

    def stop(self):
        with self.lock:
            self.state = "idle" if self.state == "playing" else self.state
            self.schedule = []
        self.dispatch(("all_off", "game"))
        self.dispatch(("track_stop",))

    def on_press(self, hand, slot, onset):
        """Judge a new sign. onset = camera time the sign was first seen."""
        if self.state != "playing":
            return
        t = onset - self.offset - self.start_time
        near = [n for n in self.notes if not n.result and n.hand == hand and abs(n.time - t) <= GOOD_WINDOW]
        match = [n for n in near if n.slot == slot]
        if not match:
            if near:
                self.feedback[hand] = ("WRONG SIGN", time.perf_counter(), "wrong")
            return
        n = min(match, key=lambda n: abs(n.time - t))
        n.error = t - n.time
        n.result = "perfect" if abs(n.error) <= PERFECT_WINDOW else "good"
        self.counts[n.result] += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.score += (100 if n.result == "perfect" else 50) * min(4, 1 + self.combo // 8)
        timing = "" if n.result == "perfect" else (" late" if n.error > 0 else " early")
        # (text, time, kind): the UI picks the colour from the kind
        self.feedback[hand] = (n.result.upper() + timing, time.perf_counter(), n.result)

    def update(self, now):
        if self.state != "playing":
            return
        t = now - self.offset - self.start_time
        for n in self.notes:
            if not n.result and t > n.time + GOOD_WINDOW:
                n.result = "miss"
                self.counts["miss"] += 1
                self.combo = 0
                self.feedback[n.hand] = ("MISS", time.perf_counter(), "miss")
        if now - self.start_time > self.length + self.song.beat:
            self._finish()

    @property
    def accuracy(self):
        """Of the notes judged so far (all of them once the song ends)."""
        judged = sum(self.counts.values()) or 1
        return 100.0 * (self.counts["perfect"] + 0.5 * self.counts["good"]) / judged

    @property
    def grade(self):
        a = self.accuracy
        return "S" if a >= 95 else "A" if a >= 85 else "B" if a >= 70 else "C" if a >= 55 else "D"

    def _finish(self):
        self.state = "results"
        best = self.scores.get(self.song.title, 0)
        self.new_best = self.score > best
        if self.new_best:
            self.scores[self.song.title] = self.score
            try:
                SCORES_PATH.write_text(json.dumps(self.scores, indent=2), encoding="utf-8")
            except OSError:
                pass
        self.dispatch(("all_off", "game"))
        self.dispatch(("track_stop",))

    def _load_scores(self):
        try:
            return json.loads(SCORES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _run(self):
        """Backing track + metronome on a 2 ms timer, independent of the camera."""
        while True:
            time.sleep(0.002)
            due = []
            with self.lock:
                now = time.perf_counter()
                while self.next_event < len(self.schedule) and self.schedule[self.next_event][0] <= now:
                    due.append(self.schedule[self.next_event][1])
                    self.next_event += 1
            for event in due:
                self.dispatch(event)

    @staticmethod
    def _bar_texts(song):
        """The sheet, bar by bar: what to play in each bar, for the scrolling chord/note strip."""
        steps_per_bar = song.beats_per_bar * song.steps_per_beat
        n_steps = max(len(t) for t in song.play.values())
        bars = []
        for b in range(math.ceil(n_steps / steps_per_bar)):
            parts = []
            for tokens in song.play.values():
                chunk = [t for t in tokens[b * steps_per_bar:(b + 1) * steps_per_bar] if t not in ("-", ".")]
                if chunk:
                    parts.append(" ".join(chunk))
            bars.append(" / ".join(parts) or "rest")
        return bars
