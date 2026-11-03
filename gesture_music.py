# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on Google MediaPipe Hand Landmarker (Apache 2.0) for hand tracking; OpenCV for the camera. Full credits: CREDITS.md

"""Gesture Music: play notes, chords and drums with hand signs in front of a webcam.

Signs (default): Basic set = hold up 1, 2, 3 or 4 fingers; fist = silence.
  Extended set (press x) adds open hand, thumbs up, rock (index + pinky) and
  call me (pinky): 8 sounds per hand. Changing sign changes the note.
Repeat the same note without changing sign: TAP (fold the raised fingers halfway
  and straighten them) or PUMP (a quick downward flick of the hand; off in Bend mode).
Strike speed sets loudness: a quick, snappy sign plays louder than a slow one.
Pinch (press g): touch your thumb to index/middle/ring/pinky instead.
Hands: the hand on the LEFT half of the screen is your left hand, and vice versa.

Window: camera view on the left, the hand stage (your tracked hands redrawn on a plain
background) on the right, pads for each hand along the bottom. Click the chips at the top,
the instrument buttons above each hand's pads, or press Tab for settings. Clicking a pad plays it.

Calibrate (F2): hold each sign for 2 seconds and the thresholds are fitted to your hands.
Sessions: F5 records your hand movements; replay them with --replay FILE, or try --demo.
Rhythm game: add your own music file in Settings > Songs (or press a); n picks a song,
  j starts/stops it, , and . adjust timing. A ghost hand on the stage shows the next sign.
Looper: r record/overdub, p play/stop, u undo, c clear; z metronome, w quantise, - and = tempo.
MIDI files: F7 records what you play, F8 exports the loop (both go to recordings/).

Keys:  m mode   x sign set   g signs/pinch   s scale   [ ] octave
       t / y next instrument for right / left hand   e expression (off/volume/bend)
       i strike-speed dynamics   space sustain   n next song   j start/stop song
       b backdrop: colour / blur / off   k stage colour   o stage view   v demo video   d debug view
       h swap hands   l camera skeleton   Tab settings   F11 fullscreen   Esc close panel   q quit

Every musical action is an event tuple, sent to the synth, MIDI and looper:
  ("note_on", voice_id, midi_note, velocity, group, instrument)   ("note_off", voice_id)
  ("drum", name, velocity, hand)   ("expr", group, bend_semitones, volume)
  ("all_off", voice_id_prefix)
"""

import argparse
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

import settings as settings_store
from calibration import Calibrator
from capture import DemoCapture
from drums import LABELS, load_kit
from game import RhythmGame, backing_sound, norm, parse_chord
from gestures import (CONFIRM_FRAMES, EXPRESSION_MODES, GESTURE_STYLES, LOOKAHEAD, SIGN_SET_NAMES,
                      WRIST, HandState, sign_names)
from looper import QUANTISE, Looper
from session import SESSIONS_DIR, SessionPlayer, SessionRecorder, list_sessions
from sound_engine import INSTRUMENT_NAMES, INSTRUMENTS, SoundEngine
from synesthesia import Synesthesia

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).parent / "hand_landmarker.task"

# Scales as semitone offsets from the root; 8 notes each.
SCALES = {
    "Major": [0, 2, 4, 5, 7, 9, 11, 12],
    "Minor": [0, 2, 3, 5, 7, 8, 10, 12],
    "Pentatonic": [0, 2, 4, 7, 9, 12, 14, 16],
    "Blues": [0, 3, 5, 6, 7, 10, 12, 15],
}
SCALE_NAMES = list(SCALES)
# Chords are built from the 7-note key that each scale belongs to
MAJOR_KEY, MINOR_KEY = [0, 2, 4, 5, 7, 9, 11], [0, 2, 3, 5, 7, 8, 10]
CHORD_KEYS = {"Major": MAJOR_KEY, "Minor": MINOR_KEY, "Pentatonic": MAJOR_KEY, "Blues": MINOR_KEY}
CHORD_DEGREES = {4: [0, 3, 4, 5],                 # I, IV, V, vi: the four-chord progression
                 8: [0, 1, 2, 3, 4, 5, 6, 7]}     # every chord in the key, plus I an octave up
CHORD_VELOCITY = 0.7                  # chords have 4 voices, so play each a bit softer
DRUM_LAYOUT = {
    4: {"R": ["kick", "snare", "hat", "open_hat"], "L": ["clap", "tom_low", "tom_high", "crash"]},
    8: {"R": ["kick", "snare", "hat", "open_hat", "clap", "tom_low", "tom_high", "crash"],
        "L": ["ride", "rim", "cowbell", "shaker", "clap", "tom_low", "tom_high", "crash"]},
}
BAND_DRUMS = {4: ["kick", "snare", "hat", "clap"],
              8: ["kick", "snare", "hat", "clap", "open_hat", "crash", "tom_low", "tom_high"]}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODES = ["Notes", "Chords", "Drums", "Band", "Custom", "Song"]
BACKGROUNDS = ["Colour", "Blur", "Off"]   # camera backdrop
# Song mode: each sign plays whatever the selected song sheet's right:/left: lines say
SONG_PADS = {"R": [], "L": []}
# Custom mode: your own mapping from Settings > Key mapping, 8 pads per hand
CUSTOM_PADS = {"R": [None] * 8, "L": [None] * 8}
DEFAULT_VELOCITY = 0.85

# Hand identity
SIDE_DEAD_ZONE = 0.08   # a lone hand within this distance of the screen centre keeps its label
DUPLICATE_DIST = 0.06   # two detections this close are the same hand seen twice
LOST_GRACE = 0.20       # seconds a hand may vanish before its notes are released
PREVIEW_TIME = 0.45     # seconds an instrument/mapping preview note plays


def ensure_model():
    if not MODEL_PATH.exists():
        print(f"Downloading hand model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return str(MODEL_PATH)


def midi_to_name(midi):
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def build_chord(root, key, degree):
    """Triad on a scale degree plus the root an octave below. Returns (notes, name)."""
    def note(d):
        return root + key[d % 7] + 12 * (d // 7)
    tones = [note(degree), note(degree + 2), note(degree + 4)]
    third, fifth = tones[1] - tones[0], tones[2] - tones[0]
    quality = "" if third == 4 else ("dim" if fifth == 6 else "m")
    return [tones[0] - 12] + tones, NOTE_NAMES[tones[0] % 12] + quality


def pad_sound(pad):
    """A Custom-mode pad ({'kind': 'note'|'chord'|'drum', ...} or None) as a slot_for result."""
    if not pad:
        return "none", None, "-"
    if pad["kind"] == "note":
        return "notes", [pad["midi"]], midi_to_name(pad["midi"])
    if pad["kind"] == "chord":
        tones = parse_chord(pad["name"])
        return ("notes", tones, pad["name"]) if tones else ("none", None, "-")
    if pad["kind"] == "drum" and pad["name"] in LABELS:
        return "drum", pad["name"], LABELS[pad["name"]]
    return "none", None, "-"


def slot_for(mode, hand, slot, scale, root, nslots=4):
    """What a slot (sign or pinch) plays: ('notes', [midi, ...], label), ('drum', name, label),
    or ('none', None, '-') for an empty Song/Custom slot."""
    if mode == "Custom":
        pads = CUSTOM_PADS[hand]
        return pad_sound(pads[slot] if slot < len(pads) else None)
    if mode == "Song":
        pads = SONG_PADS[hand]
        if slot >= len(pads):
            return "none", None, "-"
        kind, value = backing_sound(pads[slot])
        return kind, value, (LABELS[value] if kind == "drum" else pads[slot])
    notes = [root + s for s in SCALES[scale]]
    if mode == "Notes":
        if nslots == 4:
            n = notes[slot if hand == "R" else 4 + slot]
        else:
            n = notes[slot] - (12 if hand == "L" else 0)
        return "notes", [n], midi_to_name(n)
    if mode == "Drums":
        d = DRUM_LAYOUT[nslots][hand][slot]
        return "drum", d, LABELS[d]
    if hand == "R":  # Chords and Band
        tones, name = build_chord(root, CHORD_KEYS[scale], CHORD_DEGREES[nslots][slot])
        return "notes", tones, name
    if mode == "Chords":
        melody = (notes[4 + slot] if nslots == 4 else notes[slot]) + 12
        return "notes", [melody], midi_to_name(melody)
    d = BAND_DRUMS[nslots][slot]
    return "drum", d, LABELS[d]


def as_custom_pad(kind, value, label):
    """Turn a slot_for result back into a Custom pad, for 'copy this mode into Custom'."""
    if kind == "drum":
        return {"kind": "drum", "name": value}
    if kind == "notes" and len(value) == 1:
        return {"kind": "note", "midi": value[0]}
    if kind == "notes":
        return {"kind": "chord", "name": label}
    return None


def assign_hands(result, hands, swap):
    """Label each detected hand L or R by which side of the screen it's on.

    In the mirrored view your left hand appears on the left, so screen side is a
    predictable rule you can see (the centre line is drawn on screen). MediaPipe's
    own left/right guess is not used: it flips too easily. Two hands: the leftmost
    is L. One hand: its side decides, except near the centre, where it keeps the
    label it had last frame so it can't flicker while crossing.
    """
    found = []
    for lm, world in zip(result.hand_landmarks, result.hand_world_landmarks):
        x, y = lm[WRIST].x, lm[WRIST].y
        if all(math.dist((x, y), (f[0][WRIST].x, f[0][WRIST].y)) > DUPLICATE_DIST for f in found):
            found.append((lm, world))
    found = found[:2]
    left, right = ("R", "L") if swap else ("L", "R")

    if len(found) == 2:
        found.sort(key=lambda f: f[0][WRIST].x)
        return [(left, *found[0]), (right, *found[1])]
    if len(found) == 1:
        lm, world = found[0]
        x = (lm[WRIST].x + lm[9].x) / 2  # wrist + middle knuckle: steadier than either alone
        if x < 0.5 - SIDE_DEAD_ZONE:
            label = left
        elif x > 0.5 + SIDE_DEAD_ZONE:
            label = right
        else:
            tracked = [(math.dist((lm[WRIST].x, lm[WRIST].y), s.wrist), k) for k, s in hands.items() if s.wrist]
            near = min(tracked) if tracked else None
            label = near[1] if near and near[0] < 0.2 else (left if x < 0.5 else right)
        return [(label, lm, world)]
    return []


def make_lookup(song, nslots):
    """For the rhythm game: map a sheet token ('Am', 'E4', 'Kick') to the (hand, slot, label) that plays it."""
    if song.mode == "Song":  # the song brings its own pads
        SONG_PADS["R"], SONG_PADS["L"] = song.pads.get("R", []), song.pads.get("L", [])
    table = {}
    for hand in ("R", "L"):  # right hand first, so it wins when both hands can play a sound
        for slot in range(nslots):
            kind, value, label = slot_for(song.mode, hand, slot, song.scale, song.root, nslots)
            if kind == "none":
                continue
            for key in {norm(label), norm(value) if kind == "drum" else norm(label)}:
                table.setdefault(key, []).append((hand, slot, label))

    def lookup(token, hand):
        options = [o for o in table.get(norm(token), []) if hand is None or o[0] == hand]
        if not options:
            playable = sorted({o[2] for opts in table.values() for o in opts if hand in (None, o[0])})
            raise ValueError(f"'{token}' can't be played in {song.mode} mode with {song.signs} signs. "
                             f"Playable: {', '.join(playable)}")
        return options[0]
    return lookup




class Router:
    """Fans every musical event out to the synth, MIDI, and (if live) the looper and MIDI recorder."""

    def __init__(self, engine, midi):
        self.engine, self.midi, self.looper = engine, midi, None
        self.performance = None   # list of (time, event) while recording a MIDI file
        self.visual = None        # the chromesthesia backdrop sees every sound too

    def play(self, event):
        self.engine.send(event)
        if self.midi:
            self.midi.send(event)
        if self.visual:
            self.visual.send(event)

    def live(self, event):
        self.play(event)
        if self.looper:
            self.looper.record(event)
        if self.performance is not None:
            self.performance.append((time.perf_counter(), event))


VELOCITY_SOFT = 0.3   # strike-speed dynamics: the slowest sign plays at this velocity, the fastest at 1.0


class App:
    """All the instrument's state, plus one method per action (used by keys and mouse alike).

    hardware=False builds everything except the camera, hand tracker, blur and audio output,
    so the UI can be tested with simulated hands. With --replay/--demo there is no camera:
    a recorded hand session drives the app instead.
    """

    def __init__(self, args, prefs, hardware=True):
        self.args, self.prefs = args, prefs
        self.engine = SoundEngine(load_kit(), timbre="Piano", enabled=hardware and not args.mute)
        self.engine.hand_gain.update(prefs["hand_volume"])
        self.engine.hand_send.update(prefs["hand_reverb"])
        self.midi = None
        if args.midi is not None and hardware:
            from midi_out import MidiOut
            self.midi = MidiOut(args.midi)
        self.router = Router(self.engine, self.midi)
        self.visual = self.router.visual = Synesthesia()
        self.looper = self.router.looper = Looper(self.router.play, bpm=prefs["loop_bpm"],
                                                  metronome=prefs["metronome"], count_in=prefs["count_in"],
                                                  quantise=prefs["quantise"] if prefs["quantise"] in QUANTISE else "Off")
        self.game = RhythmGame(self.router.play)
        self.game.offset = (args.game_offset if args.game_offset is not None else prefs["game_offset_ms"]) / 1000
        self.capture = DemoCapture(self.engine)
        from songmaker import Importer
        self.importer = Importer(self.router.play)

        # State, starting from the saved settings (command-line options win)
        self.mode = prefs["mode"] if prefs["mode"] in MODES else "Notes"
        self.scale = prefs["scale"] if prefs["scale"] in SCALES else "Major"
        self.root = args.root if args.root is not None else max(24, min(96, prefs["root"]))
        self.style = (args.style.capitalize() if args.style else prefs["style"])
        self.style = self.style if self.style in GESTURE_STYLES else "Signs"
        self.sign_set = (args.signs.capitalize() if args.signs else prefs["sign_set"])
        self.sign_set = self.sign_set if self.sign_set in SIGN_SET_NAMES else "Basic"
        self.expression = prefs["expression"] if prefs["expression"] in EXPRESSION_MODES else "Off"
        self.instruments = {h: (prefs["instruments"].get(h) if prefs["instruments"].get(h) in INSTRUMENTS
                                else "Piano") for h in ("L", "R")}
        CUSTOM_PADS["L"], CUSTOM_PADS["R"] = prefs["custom_pads"]["L"], prefs["custom_pads"]["R"]
        self.calibration = dict(prefs["calibration"])
        self.stage_color = prefs["stage_color"]
        self.stage_view = prefs["stage_view"]
        self.trails = prefs["trails"]
        self.camera_skeleton = prefs["camera_skeleton"]
        self.dynamics = prefs["dynamics"]
        self.confirm = max(args.confirm, 1)
        self.lookahead = max(args.lookahead, 0) / 1000
        self.sustain = self.swap_hands = self.show_debug = False

        self.hands = {h: HandState(self.calibration.get(h)) for h in ("R", "L")}
        self.last_seen = {"R": 0.0, "L": 0.0}
        self.sounding = {}        # (hand, slot) -> voice ids it started
        self.notes_on = {}        # (hand, slot) -> MIDI notes it is playing (for the on-screen keyboard)
        self.velocity_on = {}     # (hand, slot) -> velocity it was struck with (for the pads)
        self.sustained = set()    # voice ids held by the sustain toggle
        self.mouse_pads = set()   # pads held down with the mouse
        self.timed_offs = []      # (time, voice id) for preview notes
        self.view_hands = []      # what the UI draws this frame
        self.frame, self.frame_size = None, (1280, 720)
        self.message, self.message_until = "", 0.0
        self.seq, self.last_ts = 0, 0
        self.track_ms = self.latency_ms = 0.0
        self.running = True
        self.capture_toggle = False
        self.calibrator = None             # the calibration wizard while it runs
        self.session_recorder = SessionRecorder()
        self.player = None                 # SessionPlayer while replaying a session

        # Hardware: hand tracker, background blur, camera, audio output
        self.landmarker = self.blur = self.camera = None
        self.blur_pool = ThreadPoolExecutor(max_workers=1)  # blurs while the hands are being tracked
        replay = getattr(args, "replay", None) or (getattr(args, "demo", False) and str(SESSIONS_DIR / "demo.gmsession"))
        self.kept_prefs = None
        if getattr(args, "demo", False):  # the demo was recorded for Band mode; your saved mode is kept
            self.kept_prefs = {"mode": self.mode, "sign_set": self.sign_set, "style": self.style}
            self.mode, self.sign_set, self.style = "Band", "Basic", "Signs"
        if hardware:
            if replay:
                self.start_replay(replay)
            else:
                self._open_camera()
            self.engine.start()
        self.background = "Off" if args.no_blur else prefs["background"] if prefs["background"] in BACKGROUNDS else "Colour"
        self.load_song_pads()

    def _open_camera(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
        from camera import Camera
        self._mp = mp
        self.landmarker = HandLandmarker.create_from_options(HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=ensure_model()),
            running_mode=RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        ))
        try:
            from background import Background
            self.blur = Background()
        except Exception as e:  # e.g. no internet for the first model download
            print(f"Camera backdrop unavailable: {e}")
        self.camera = Camera(self.args.camera)

    # ---------------------------------------------------------------- layout helpers

    @property
    def effective_sign_set(self):
        return self.sign_set if self.style == "Signs" else "Basic"  # pinch only has 4 slots

    @property
    def nslots(self):
        return 8 if self.effective_sign_set == "Extended" else 4

    def slot(self, hand, slot, mode=None):
        return slot_for(mode or self.mode, hand, slot, self.scale, self.root, self.nslots)

    def hand_plays_drums(self, hand):
        kinds = {self.slot(hand, s)[0] for s in range(self.nslots)} - {"none"}
        return kinds == {"drum"}

    def notify(self, text, seconds=3.0):
        self.message, self.message_until = text, time.time() + seconds

    # ---------------------------------------------------------------- playing sounds

    def press(self, hand, slot, velocity=DEFAULT_VELOCITY):
        kind, value, _ = self.slot(hand, slot)
        if kind == "none":
            return
        self.velocity_on[(hand, slot)] = velocity
        if kind == "drum":
            self.router.live(("drum", value, velocity, hand))
            return
        if len(value) > 1:
            velocity *= CHORD_VELOCITY
        inst = self.instruments[hand]
        shift = INSTRUMENTS[inst].transpose
        vids = []
        for k, note in enumerate(value):
            vid = ("live", hand, slot, k)
            self.sustained.discard(vid)  # re-pressing restarts the note; don't let sustain cut it later
            self.router.live(("note_on", vid, note + shift, velocity, hand, inst))
            vids.append(vid)
        self.sounding[(hand, slot)] = vids
        self.notes_on[(hand, slot)] = [note + shift for note in value]

    def release(self, hand, slot):
        self.notes_on.pop((hand, slot), None)
        for vid in self.sounding.pop((hand, slot), []):
            if self.sustain:
                self.sustained.add(vid)
            else:
                self.router.live(("note_off", vid))

    def flush_sustain(self):
        for vid in self.sustained:
            self.router.live(("note_off", vid))
        self.sustained.clear()

    def release_all(self):
        for hand, state in self.hands.items():
            for slot in state.lost():
                self.release(hand, slot)
        for hand, slot in list(self.mouse_pads):
            self.release(hand, slot)
        self.mouse_pads.clear()
        self.flush_sustain()

    def pad_down(self, hand, slot):
        """Clicking a pad plays it, so you can try sounds without the camera."""
        self.mouse_pads.add((hand, slot))
        self.press(hand, slot)
        self.game.on_press(hand, slot, time.perf_counter())

    def pad_up(self, hand, slot):
        if (hand, slot) in self.mouse_pads:
            self.mouse_pads.discard((hand, slot))
            self.release(hand, slot)

    def preview(self, hand, sound):
        """Play a short preview of a sound ((kind, value, label)) on a hand's instrument."""
        kind, value, _ = sound
        if kind == "drum":
            self.router.play(("drum", value, DEFAULT_VELOCITY, hand))
        elif kind == "notes":
            inst = self.instruments[hand]
            for k, note in enumerate(value):
                vid = ("preview", hand, k)
                self.router.play(("note_on", vid, note + INSTRUMENTS[inst].transpose,
                                  DEFAULT_VELOCITY * (CHORD_VELOCITY if len(value) > 1 else 1), hand, inst))
                self.timed_offs.append((time.perf_counter() + PREVIEW_TIME, vid))

    # ---------------------------------------------------------------- actions

    def save(self):
        settings_store.save({
            "mode": self.mode, "scale": self.scale, "root": self.root, "sign_set": self.sign_set,
            "style": self.style, **(self.kept_prefs or {}), "expression": self.expression,
            "instruments": dict(self.instruments),
            "custom_pads": {h: list(CUSTOM_PADS[h]) for h in ("L", "R")}, "stage_color": self.stage_color,
            "stage_view": self.stage_view, "trails": self.trails, "camera_skeleton": self.camera_skeleton,
            "background": self.background, "game_offset_ms": round(self.game.offset * 1000),
            "calibration": self.calibration, "hand_volume": dict(self.engine.hand_gain),
            "hand_reverb": dict(self.engine.hand_send), "dynamics": self.dynamics,
            "loop_bpm": self.looper.bpm, "metronome": self.looper.metronome, "count_in": self.looper.count_in,
            "quantise": self.looper.quantise,
        })

    def set_mode(self, mode):
        self.release_all()
        self.mode = mode
        self.load_song_pads()
        self.save()

    def cycle_mode(self, step=1):
        self.set_mode(MODES[(MODES.index(self.mode) + step) % len(MODES)])

    def cycle_sign_set(self):
        self.release_all()
        self.sign_set = SIGN_SET_NAMES[(SIGN_SET_NAMES.index(self.sign_set) + 1) % len(SIGN_SET_NAMES)]
        self.save()

    def cycle_style(self):
        self.release_all()
        self.style = GESTURE_STYLES[(GESTURE_STYLES.index(self.style) + 1) % len(GESTURE_STYLES)]
        self.save()

    def cycle_scale(self):
        self.scale = SCALE_NAMES[(SCALE_NAMES.index(self.scale) + 1) % len(SCALE_NAMES)]
        self.save()

    def octave(self, step):
        self.root = max(24, min(96, self.root + 12 * step))
        self.save()

    def set_instrument(self, hand, name, preview=True):
        self.instruments[hand] = name
        if preview:
            self.preview(hand, ("notes", [60], "C4"))
        self.save()

    def cycle_instrument(self, hand, step=1):
        i = INSTRUMENT_NAMES.index(self.instruments[hand])
        self.set_instrument(hand, INSTRUMENT_NAMES[(i + step) % len(INSTRUMENT_NAMES)])
        self.notify(f"{'Right' if hand == 'R' else 'Left'} hand: {self.instruments[hand]}", 2)

    def set_mix(self, hand, volume=None, reverb=None):
        """Per-hand volume and reverb send (0..1). Applies at once, even to notes already sounding."""
        if volume is not None:
            self.engine.hand_gain[hand] = max(0.0, min(1.0, volume))
        if reverb is not None:
            self.engine.hand_send[hand] = max(0.0, min(1.0, reverb))

    def toggle_dynamics(self):
        self.dynamics = not self.dynamics
        self.notify("Strike speed sets loudness" if self.dynamics else "Every sign plays at the same loudness", 2)
        self.save()

    def cycle_expression(self):
        self.expression = EXPRESSION_MODES[(EXPRESSION_MODES.index(self.expression) + 1) % len(EXPRESSION_MODES)]
        self.save()

    def toggle_sustain(self):
        self.sustain = not self.sustain
        if not self.sustain:
            self.flush_sustain()

    def cycle_background(self, name=None):
        """Camera backdrop: Colour (chromesthesia), Blur or Off."""
        self.background = name or BACKGROUNDS[(BACKGROUNDS.index(self.background) + 1) % len(BACKGROUNDS)]
        if self.blur is None and self.camera is not None and self.background != "Off":
            self.notify("The backdrop needs the person model (see the console)")
        else:
            self.notify({"Colour": "Backdrop: chromesthesia colours follow the notes", "Blur": "Backdrop: blur",
                         "Off": "Backdrop: off"}[self.background], 2)
        self.save()

    def toggle_swap(self):
        self.release_all()
        self.swap_hands = not self.swap_hands

    def cycle_stage_color(self, count):
        self.stage_color = (self.stage_color + 1) % count
        self.save()

    def cycle_stage_view(self, count):
        self.stage_view = (self.stage_view + 1) % count
        self.save()

    def toggle(self, attr):
        setattr(self, attr, not getattr(self, attr))
        self.save()

    # -- looper and MIDI files

    def loop_action(self, action):
        getattr(self.looper, action)()

    def set_loop_bpm(self, bpm):
        self.looper.bpm = round(max(40.0, min(240.0, bpm)), 1)
        self.save()

    def toggle_metronome(self):
        self.looper.metronome = not self.looper.metronome
        self.save()

    def toggle_count_in(self):
        self.looper.count_in = not self.looper.count_in
        self.save()

    def cycle_quantise(self):
        self.looper.quantise = QUANTISE[(QUANTISE.index(self.looper.quantise) + 1) % len(QUANTISE)]
        self.notify(f"Quantise: {self.looper.quantise}", 2)
        self.save()

    def toggle_midi_recording(self):
        """Record everything you play to a MIDI file (recordings/)."""
        from midi_file import export
        if self.router.performance is None:
            self.router.performance = []
            self.notify("Recording a MIDI file... press F7 again to save it", 3)
            return
        events, self.router.performance = self.router.performance, None
        if not events:
            self.notify("Nothing was played, so no MIDI file was saved", 3)
            return
        path = export(events, bpm=self.looper.bpm, name="Performance")
        self.notify(f"Saved {path.name} in recordings/", 5)

    def export_loop(self):
        from midi_file import export
        events = self.looper.export_events(cycles=1)
        if not events:
            self.notify("Record a loop first (press r)", 3)
            return
        path = export(events, bpm=self.looper.bpm, name="Loop")
        self.notify(f"Saved the loop as {path.name} in recordings/", 5)

    # -- calibration

    def start_calibration(self, sign_set=None):
        self.release_all()
        self.calibrator = Calibrator(sign_set or self.effective_sign_set, time.perf_counter())

    def finish_calibration(self, save=True):
        cal, self.calibrator = self.calibrator, None
        if save and cal and cal.result:
            for hand, res in cal.result.items():
                self.calibration[hand] = res["thresholds"]
                self.hands[hand].calibrate(res["thresholds"])
            self.save()
            self.notify(f"Calibration saved for: {', '.join('left hand' if h == 'L' else 'right hand' for h in cal.result)}", 4)

    def reset_calibration(self):
        self.calibration = {}
        for state in self.hands.values():
            state.calibrate(None)
        self.save()
        self.notify("Thresholds reset to the defaults", 3)

    # -- hand sessions

    def toggle_session_recording(self):
        rec = self.session_recorder
        if rec.active:
            path, frames, seconds = rec.stop()
            self.notify(f"Saved {path.name}: {seconds:.0f} s of hand movement", 5)
        elif self.player:
            self.notify("Stop the replay before recording a new session", 3)
        else:
            rec.start()
            self.notify("Recording your hand movements... press F5 again to save", 3)

    def start_replay(self, path):
        try:
            player = SessionPlayer(path)
        except (OSError, ValueError) as e:
            self.notify(str(e), 5)
            print(e)
            return
        self.release_all()
        self.player, self.frame = player, None
        self.notify(f"Replaying {Path(path).name}", 3)

    def stop_replay(self):
        if not self.player:
            return
        self.player = None
        self.release_all()
        if self.camera is None and not getattr(self.args, "no_camera", False):
            try:
                self._open_camera()
            except SystemExit as e:  # no camera available: stay without one
                self.notify(str(e), 5)
        self.notify("Back to the live camera", 2)

    def replay_latest(self):
        if self.player:
            self.stop_replay()
            return
        sessions = [p for p in list_sessions() if p.stem != "demo"]
        if sessions:
            self.start_replay(sessions[0])
        else:
            self.notify("No recorded sessions yet: press F5 to record one", 3)

    # -- songs

    def next_song(self):
        self.release_all()
        self.game.next_song()
        self.load_song_pads()

    def select_song(self, index, play=False):
        """Choose a song from the list; play=True also starts it (or stops it if it is playing)."""
        if self.game.state == "playing":
            same = index == self.game.index
            self.game.stop()
            if same:
                return
        self.release_all()
        self.game.index = index
        self.load_song_pads()
        if play:
            self.toggle_game()

    def load_song_pads(self):
        """Song mode plays the selected sheet's own sounds (its right:/left: lines)."""
        try:
            pads = self.game.load_selected().pads
        except (ValueError, OSError):
            pads = {}
        SONG_PADS["R"], SONG_PADS["L"] = pads.get("R", []), pads.get("L", [])

    def toggle_game(self):
        if self.game.state == "playing":
            self.game.stop()
            return
        try:
            song = self.game.load_selected()
            if song.mode not in MODES:
                raise ValueError(f"{song.path.name}: mode must be one of {', '.join(MODES)}")
            if song.mode == "Song" and not song.pads:
                raise ValueError(f"{song.path.name}: Song mode needs right: and/or left: lines")
            self.release_all()
            self.load_song_pads()
            self.mode, self.scale, self.root = song.mode, song.scale, song.root
            self.style, self.sign_set = "Signs", song.signs
            self.game.start(song, make_lookup(song, self.nslots), sign_names(self.effective_sign_set),
                            time.perf_counter())
        except ValueError as e:
            self.notify(str(e), 6)
            print(e)

    def add_song(self):
        """Open a music or MIDI file and start analysing it (Settings > Songs shows the result)."""
        path = self.importer.pick_file()
        if path:
            self.importer.open(path)

    def create_song(self):
        path = self.importer.create()
        self.game.refresh(select=path)
        self.load_song_pads()
        self.notify(f"Added {path.stem}: press j to play it", 5)

    def adjust_offset(self, ms):
        self.game.offset += ms / 1000
        self.notify(f"Game timing offset {self.game.offset * 1000:+.0f} ms", 2)
        self.save()

    # -- key mapping

    def set_custom_pad(self, hand, slot, pad):
        CUSTOM_PADS[hand][slot] = pad
        if self.mode != "Custom":
            self.set_mode("Custom")
            self.notify("Switched to Custom mode, where your mapping plays", 3)
        self.preview(hand, pad_sound(pad))
        self.save()

    def copy_mode_to_custom(self, mode):
        for hand in ("L", "R"):
            CUSTOM_PADS[hand] = [as_custom_pad(*slot_for(mode, hand, s, self.scale, self.root, 8)) for s in range(8)]
        self.set_mode("Custom")
        self.notify(f"Copied the {mode} layout into Custom: edit any sign", 3)

    def reset_custom(self):
        from settings import DEFAULT_CUSTOM_PADS
        for hand in ("L", "R"):
            CUSTOM_PADS[hand] = [dict(p) for p in DEFAULT_CUSTOM_PADS[hand]]
        self.save()
        self.notify("Custom mapping reset to a two-octave keyboard", 3)

    def save_preset(self, name):
        name = name.strip()
        if not name:
            return
        settings_store.write_preset(name, CUSTOM_PADS)
        self.notify(f"Saved the mapping as '{name}'", 3)

    def load_preset(self, name):
        try:
            pads = settings_store.load_preset(name)
        except ValueError as e:
            self.notify(str(e), 4)
            return
        CUSTOM_PADS["L"], CUSTOM_PADS["R"] = pads["L"], pads["R"]
        self.set_mode("Custom")
        self.notify(f"Loaded '{name}'", 3)

    def delete_preset(self, name):
        settings_store.delete_preset(name)
        self.notify(f"Deleted '{name}'", 3)

    def import_preset(self):
        path = _ask_file(save=False, title="Import a key mapping", types=[("Key mapping", "*.json")])
        if not path:
            return
        try:
            pads = settings_store.read_preset(path)
        except ValueError as e:
            self.notify(str(e), 4)
            return
        settings_store.write_preset(Path(path).stem, pads)
        self.notify(f"Imported '{Path(path).stem}'", 3)

    def export_preset(self, name):
        path = _ask_file(save=True, title="Export the key mapping", types=[("Key mapping", "*.json")],
                         initial=f"{name}.json")
        if path:
            settings_store.write_preset(name, settings_store.load_preset(name), path=path)
            self.notify(f"Exported to {Path(path).name}", 3)

    # ---------------------------------------------------------------- each frame

    def step(self):
        """Get the next hands (camera or replay) and play. Returns False if nothing came."""
        if self.player:
            got = self.player.read()
            if got is None:
                self.stop_replay()
                return False
            stamp, detections = got
            self.process(detections, stamp)
            # no camera picture in a replay: the colour field fills the camera panel instead
            self.frame = self.visual.image(self.frame_size) if self.background == "Colour" else None
            return True
        if self.camera is None:
            time.sleep(0.03)
            return False
        got = self.camera.read(self.seq, timeout=0.5)
        if got is None:
            self.notify("The camera isn't sending frames. Is another app using it?", 1)
            return False
        self.seq, frame, stamp = got
        frame = cv2.flip(frame, 1)  # mirror view feels natural
        ts = max(int(stamp * 1000), self.last_ts + 1)  # MediaPipe needs strictly increasing timestamps
        self.last_ts = ts
        # The backdrop runs on another thread alongside hand tracking (both are native code),
        # so it costs ~1 ms instead of ~12 ms per frame
        blurred = None
        if self.blur and self.background != "Off":
            colour = self.visual if self.background == "Colour" else None
            blurred = self.blur_pool.submit(self.blur.apply, frame, ts, colour)
        t0 = time.perf_counter()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp = self._mp
        result = self.landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        self.track_ms += 0.1 * ((time.perf_counter() - t0) * 1000 - self.track_ms)
        self.process(assign_hands(result, self.hands, self.swap_hands), stamp)
        self.frame = blurred.result() if blurred is not None else frame
        self.frame_size = (frame.shape[1], frame.shape[0])
        return True

    def process(self, detections, stamp):
        """Turn this frame's hands into sound. detections: [(hand, landmarks, world landmarks)]."""
        if self.session_recorder.active:
            self.session_recorder.add(stamp, detections)
        seen, view = set(), []
        calibrating = self.calibrator is not None
        for hand, landmarks, world in detections:
            seen.add(hand)
            self.last_seen[hand] = stamp
            state = self.hands[hand]
            if self.style == "Signs" or calibrating:
                pressed, released, points = state.update_signs(landmarks, world, stamp, self.confirm,
                                                               self.effective_sign_set,
                                                               pump=self.expression != "Bend")
            else:
                pressed, released, points = state.update(landmarks, world, stamp, self.lookahead)
            view.append({"hand": hand, "landmarks": landmarks, "world": world, "points": points,
                         "bend": 0.0, "volume": 1.0, "state": state})
            if calibrating:  # the wizard only measures; nothing plays
                continue

            # Hand height -> expression, sent before note_on so new notes start correctly
            bend, volume = state.expression(self.expression)
            if abs(bend - state.last_expr[0]) > 0.02 or abs(volume - state.last_expr[1]) > 0.01:
                self.router.live(("expr", hand, bend, volume))
                state.last_expr = (bend, volume)
            view[-1]["bend"], view[-1]["volume"] = bend, volume
            if self.expression == "Volume":
                velocity = volume
            elif self.dynamics:
                velocity = VELOCITY_SOFT + (1 - VELOCITY_SOFT) * state.strike
            else:
                velocity = DEFAULT_VELOCITY

            for slot in released:
                self.release(hand, slot)
            for slot in sorted(pressed):
                self.press(hand, slot, velocity)
                self.game.on_press(hand, slot, state.onset)

        if calibrating:
            self.calibrator.update(stamp, {v["hand"]: v["state"] for v in view})

        for hand in self.hands.keys() - seen:
            # Tracking often drops a hand for a frame or two; only let go after a short grace period
            if stamp - self.last_seen[hand] > LOST_GRACE:
                for slot in self.hands[hand].lost():
                    self.release(hand, slot)

        # All sound for this frame has been sent; measure how long that took from capture
        now = time.perf_counter()
        if self.player is None:
            self.latency_ms += 0.1 * ((now - stamp) * 1000 - self.latency_ms)
        self.game.update(now)
        for t, vid in [o for o in self.timed_offs if o[0] <= now]:
            self.router.play(("note_off", vid))
        self.timed_offs = [o for o in self.timed_offs if o[0] > now]
        self.view_hands = view

    def active_pads(self):
        """(hand, slot) pairs sounding right now, from gestures or the mouse."""
        pads = set(self.mouse_pads)
        for hand, state in self.hands.items():
            if state.wrist is not None:
                pads |= {(hand, s) for s in state.active}
        return pads

    def run(self, ui):
        while self.running:
            if not ui.handle_events():
                break
            if not self.step():
                self.process([], time.perf_counter())
            ui.draw()
            if self.capture_toggle:  # started/stopped from the UI; records the whole window
                self.capture_toggle = False
                if self.capture.active:
                    self.notify(self.capture.stop(), 5)
                else:
                    self.capture.start(ui.snapshot())
                    self.notify("Capturing a demo of the whole window... press v to stop", 3)
            elif self.capture.active:
                self.capture.add_frame(ui.snapshot())

    def close(self):
        if self.capture.active:
            print(self.capture.stop())
        if self.session_recorder.active:
            print("Saved session:", self.session_recorder.stop()[0])
        if self.router.performance:
            self.toggle_midi_recording()
        self.importer.stop_preview()
        self.game.stop()
        self.release_all()
        self.save()
        self.looper.close()
        if self.camera:
            self.camera.release()
        if self.landmarker:
            self.landmarker.close()
        self.blur_pool.shutdown(wait=True)
        if self.blur:
            self.blur.close()
        self.engine.close()
        if self.midi:
            self.midi.close()


def _ask_file(save, title, types, initial=""):
    """A native open/save dialog (tkinter); returns a path or None."""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if save:
        path = filedialog.asksaveasfilename(title=title, filetypes=types, initialfile=initial, parent=root,
                                            defaultextension=".json")
    else:
        path = filedialog.askopenfilename(title=title, filetypes=types, parent=root)
    root.destroy()
    return path or None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument("--root", type=int, default=None, help="MIDI root note (60 = middle C)")
    parser.add_argument("--midi", nargs="?", const="", metavar="PORT",
                        help="send MIDI to a virtual cable/device (or a port whose name contains PORT)")
    parser.add_argument("--list-midi", action="store_true", help="list MIDI output ports and exit")
    parser.add_argument("--mute", action="store_true", help="disable the built-in synth (MIDI only)")
    parser.add_argument("--style", choices=[s.lower() for s in GESTURE_STYLES], default=None,
                        help="how you select sounds: hand signs or pinches (default: last used)")
    parser.add_argument("--signs", choices=[s.lower() for s in SIGN_SET_NAMES], default=None,
                        help="sign set: basic (1-4 fingers) or extended (8 signs per hand)")
    parser.add_argument("--confirm", type=int, default=CONFIRM_FRAMES, metavar="N",
                        help=f"frames a new hand sign must be held before it plays (default {CONFIRM_FRAMES}; 1 = fastest)")
    parser.add_argument("--lookahead", type=float, default=LOOKAHEAD * 1000, metavar="MS",
                        help=f"pinch style: trigger this many ms early when fingers close fast (default {LOOKAHEAD * 1000:.0f}, 0 = off)")
    parser.add_argument("--game-offset", type=float, default=None, metavar="MS",
                        help="rhythm game: your camera's delay in ms (default: last used; , and . adjust it)")
    parser.add_argument("--no-blur", action="store_true", help="start with the plain camera background (b cycles colour / blur / off)")
    parser.add_argument("--window", default=None, metavar="WxH", help="window size, e.g. 1600x900 (default: fits your screen)")
    parser.add_argument("--replay", default=None, metavar="FILE", help="replay a recorded hand session instead of the camera")
    parser.add_argument("--demo", action="store_true", help="play the built-in demo session (no camera needed)")
    parser.add_argument("--no-camera", action="store_true", help="don't open the camera after a replay ends")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    if args.list_midi:
        from midi_out import list_ports
        print("\n".join(list_ports()) or "No MIDI outputs found")
        return
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from ui import UI
    app = App(args, settings_store.load())
    ui = UI(app, window=args.window)
    print(__doc__)
    try:
        app.run(ui)
    finally:
        app.close()
        ui.close()


if __name__ == "__main__":
    main()
