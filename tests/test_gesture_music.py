# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on unittest (Python standard library); soundfile for test audio. Full credits: CREDITS.md

"""Tests for the parts of Gesture Music that don't need a camera or a sound card.

Run from the project folder:   .venv/Scripts/python -m unittest discover tests -v

Hands come from the synthetic hand model (handmodel.py) and songs are synthesized here, so the
tests are repeatable. Every file is written to a temporary folder: your settings, scores, songs,
sessions and recordings are never touched.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import calibration  # noqa: E402
import handmodel as hm  # noqa: E402
from gestures import CURLED_MIN_CURL, EXTENDED_MAX_CURL, REST, SIGN_SETS, HandState  # noqa: E402


def make_sign(state, pattern, thumb, hand="R", frames=3, t0=0.0, sign_set="Extended", fold=None):
    """Feed a few frames of one sign; returns the (pressed, released, repeat) of the last frame."""
    out = None
    for k in range(frames):
        screen, world = hm.landmarks(pattern, thumb, hand, fold=fold)
        out = state.update_signs(screen, world, t0 + k / 30, 2, sign_set)
    return out


class SignTests(unittest.TestCase):
    def test_every_sign_is_recognised_on_both_hands(self):
        for hand in "LR":
            for slot, (name, pattern, thumb) in enumerate(SIGN_SETS["Extended"]):
                state = HandState()
                make_sign(state, pattern, thumb, hand)
                self.assertEqual(state.sign, slot, f"{hand} {name}")
            state = HandState()
            make_sign(state, (0, 0, 0, 0), False, hand)
            self.assertEqual(state.sign, REST, f"{hand} fist")

    def test_faster_strike_is_louder(self):
        def strike(frames_to_open):
            state, t = HandState(), 0.0
            for _ in range(6):
                make_sign(state, (0, 0, 0, 0), False, frames=1, t0=t, sign_set="Basic")
                t += 1 / 30
            for k in range(1, frames_to_open + 4):
                c = max(0.0, 1 - k / frames_to_open)
                pressed = make_sign(state, (1, 1, 0, 0), None, frames=1, t0=t, sign_set="Basic",
                                    fold=[c, c, 1, 1])[0]
                t += 1 / 30
                if pressed:
                    return state.strike
            self.fail("the sign was never pressed")
        fast, medium, slow = strike(2), strike(4), strike(14)
        self.assertGreater(fast, medium)
        self.assertGreater(medium, slow)
        self.assertLessEqual(fast, 1.0)
        self.assertGreaterEqual(slow, 0.0)

    def test_calibrated_thresholds_are_used(self):
        state = HandState({"ext_max": [10] * 4, "curl_min": [20] * 4, "thumb_out_min": 0.9, "thumb_in_max": 0.7})
        state.reset()  # calibration survives a reset
        self.assertEqual(state.ext_max, [10] * 4)
        state.calibrate(None)
        self.assertEqual(state.ext_max, [EXTENDED_MAX_CURL] * 4)


class CalibrationTests(unittest.TestCase):
    def run_wizard(self, sign_set, curl_up=40.0, curl_down=200.0, noise=8.0):
        rng = np.random.default_rng(0)
        cal = calibration.Calibrator(sign_set, 0.0)
        t = 0.0

        class Fake:
            pass
        while not cal.done:
            t += 1 / 30
            _, pattern, thumb = cal.step
            states = {}
            for hand in "LR":
                s = Fake()
                s.curls = [(curl_up if p else curl_down) + rng.normal(0, noise) for p in pattern]
                s.thumb_ratio = 1.1 if thumb else 0.5
                states[hand] = s
            cal.update(t, states)
        return cal

    def test_thresholds_land_between_up_and_down(self):
        cal = self.run_wizard("Extended")
        for hand in "LR":
            res = cal.result[hand]
            th = res["thresholds"]
            for f in range(4):
                self.assertTrue(40 < th["ext_max"][f] < th["curl_min"][f] < 200, th)
                self.assertTrue(res["fingers"][f]["ok"])
            self.assertTrue(0.5 < th["thumb_in_max"] < th["thumb_out_min"] < 1.1, th)
            self.assertTrue(all(score == 1.0 for _, score in res["steps"]))

    def test_overlapping_readings_are_flagged(self):
        cal = self.run_wizard("Basic", curl_up=100, curl_down=110, noise=3)
        fingers = cal.result["R"]["fingers"]
        self.assertFalse(any(f["ok"] for f in fingers))
        for f in fingers:
            self.assertLess(f["ext_max"], f["curl_min"])  # still a usable keep-state zone

    def test_unseen_hand_gets_no_result(self):
        cal = calibration.Calibrator("Basic", 0.0)
        cal.skip(0.0)
        for i in range(30 * 30):  # longer than the whole wizard
            cal.update(i / 30, {})
        self.assertTrue(cal.done)
        self.assertEqual(cal.result, {})


class LooperTests(unittest.TestCase):
    def setUp(self):
        from looper import Looper
        self.looper = Looper(lambda e: None, bpm=120.0, quantise="1/8")

    def tearDown(self):
        self.looper.close()

    def test_quantise_snaps_starts_and_keeps_lengths(self):
        lp = self.looper
        lp.length = 2.0  # one bar at 120 BPM
        take = [(0.27, ("note_on", "a", 60, 0.8, "R")), (0.61, ("note_off", "a")),
                (0.74, ("drum", "kick", 0.9, "L"))]
        out = dict((e[0] if e[0] == "drum" else (e[0], e[1]), t) for t, e in lp._quantised(take))
        self.assertAlmostEqual(out[("note_on", "a")], 0.25)
        self.assertAlmostEqual(out[("note_off", "a")], 0.59)   # moved with its note: length kept
        self.assertAlmostEqual(out["drum"], 0.75)

    def test_export_events_repeats_cycles(self):
        lp = self.looper
        lp.length, lp.layers = 2.0, [[(0.5, ("note_on", "a", 60, 0.8, "R", "Piano")), (1.0, ("note_off", "a"))]]
        events = lp.export_events(cycles=2)
        self.assertEqual([round(t, 3) for t, _ in events], [0.5, 1.0, 2.5, 3.0])
        self.assertEqual(events[0][1][5], "Piano")


class MidiFileTests(unittest.TestCase):
    def test_round_trip(self):
        import midi_file
        events = [(10.0, ("note_on", "a", 60, 0.8, "R", "Piano")), (10.5, ("note_off", "a")),
                  (10.5, ("note_on", "b", 64, 0.5, "L", "Strings")), (11.0, ("note_off", "b")),
                  (11.0, ("drum", "kick", 1.0, "L"))]
        with tempfile.TemporaryDirectory() as tmp:
            path = midi_file.export(events, Path(tmp) / "t.mid", bpm=100)
            bpm, notes = midi_file.read_notes(path)
        self.assertAlmostEqual(bpm, 100, places=1)
        by_pitch = {n[2]: n for n in notes}
        self.assertAlmostEqual(by_pitch[60][0], 0.0, places=2)    # starts at the first event
        self.assertAlmostEqual(by_pitch[60][1], 0.5, places=2)
        self.assertAlmostEqual(by_pitch[64][0], 0.5, places=2)
        self.assertEqual(by_pitch[36][4], 9)                     # kick on the drum channel
        self.assertNotEqual(by_pitch[60][4], by_pitch[64][4])    # one channel per hand


class SessionTests(unittest.TestCase):
    def test_record_and_replay(self):
        import session
        with tempfile.TemporaryDirectory() as tmp:
            old = session.SESSIONS_DIR
            session.SESSIONS_DIR = Path(tmp)
            try:
                rec = session.SessionRecorder()
                rec.start("test")
                for k in range(5):
                    screen, world = hm.landmarks((1, 0, 0, 0), None, "R")
                    rec.add(100.0 + k / 30, [("R", screen, world)])
                path, frames, seconds = rec.stop()
                self.assertEqual(frames, 5)
                self.assertAlmostEqual(seconds, 4 / 30, places=3)
                player = session.SessionPlayer(path, loop=False)
                got = [player.read() for _ in range(6)]
            finally:
                session.SESSIONS_DIR = old
        self.assertIsNone(got[-1])
        hand, screen, world = got[0][1][0]
        self.assertEqual(hand, "R")
        state = HandState()
        for stamp, dets in got[:-1]:
            state.update_signs(dets[0][1], dets[0][2], stamp, 2, "Basic")
        self.assertEqual(state.sign, 0)  # the replayed hand still reads as 1 finger


class SynesthesiaTests(unittest.TestCase):
    def test_colours_follow_the_circle_of_fifths(self):
        from synesthesia import key_colours, note_rgb
        names = [name for name, _ in key_colours()]
        self.assertEqual(names, ["C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#", "F"])
        r, g, b = note_rgb(60)
        self.assertGreater(r, 0.6)
        self.assertLess(max(g, b), 0.1)               # C is red
        self.assertGreater(sum(note_rgb(84)), sum(note_rgb(36)))   # higher octaves are lighter

    def test_field_answers_notes_then_fades(self):
        from synesthesia import Synesthesia
        s = Synesthesia()
        quiet = s.render(0.0).mean(axis=(0, 1))
        s.send(("note_on", ("live", "R", 0, 0), 60, 1.0, "R"))   # C: red
        for k in range(15):                                       # half a second of frames
            lit = s.render(0.5 + k / 30).mean(axis=(0, 1))
        self.assertGreater(lit[0] - lit[2], quiet[0] - quiet[2] + 0.05)   # the room turned red
        s.send(("drum", "rim", 1.0, "L"))                         # clicks don't flash
        self.assertEqual(s.flash, 0.0)
        s.send(("all_off", "live"))
        for k in range(1, 200):
            faded = s.render(1.0 + k / 30)
        self.assertEqual(s.blooms, [])
        self.assertLess(faded.mean(), lit.mean())


class PresetTests(unittest.TestCase):
    def test_save_load_and_reject(self):
        import settings
        with tempfile.TemporaryDirectory() as tmp:
            old = settings.MAPPINGS_DIR
            settings.MAPPINGS_DIR = Path(tmp)
            try:
                pads = {"L": [{"kind": "drum", "name": "kick"}], "R": [{"kind": "note", "midi": 999}]}
                settings.write_preset("My set", pads)
                self.assertEqual(settings.list_presets(), ["My set"])
                loaded = settings.load_preset("My set")
                self.assertEqual(loaded["L"][0], {"kind": "drum", "name": "kick"})
                self.assertEqual(len(loaded["L"]), 8)
                self.assertIsNone(loaded["R"][0])       # invalid pad dropped
                bad = Path(tmp) / "bad.json"
                bad.write_text("{}")
                with self.assertRaises(ValueError):
                    settings.read_preset(bad)
                settings.delete_preset("My set")
                self.assertNotIn("My set", settings.list_presets())
            finally:
                settings.MAPPINGS_DIR = old


def synth_song(path, bpm=112.0, start=1.3, bars=16, sr=22050):
    """Drums, chords C G Am F and a melody, written to a WAV file."""
    import soundfile as sf
    beat = 60 / bpm
    y = np.zeros(int((start + bars * 4 * beat + 1) * sr))
    rng = np.random.default_rng(0)

    def add(t, sig):
        i = int(t * sr)
        y[i:i + len(sig)] += sig[:len(y) - i]

    def tone(midis, length, amp, decay):
        tt = np.arange(int(length * sr)) / sr
        return sum(amp * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * tt) * np.exp(-decay * tt) for m in midis)
    chords = {"C": [48, 60, 64, 67], "G": [43, 55, 59, 62], "Am": [45, 57, 60, 64], "F": [41, 53, 57, 60]}
    melody = [72, 74, 76, 79, 79, 77, 76, 74]
    for bar in range(bars):
        t0 = start + bar * 4 * beat
        add(t0, tone(chords[["C", "G", "Am", "F"][bar % 4]], 4 * beat, 0.12, 0.6))
        for b in range(4):
            tb = t0 + b * beat
            tt = np.arange(int(0.3 * sr)) / sr
            if b in (0, 2):
                add(tb, 0.9 * np.sin(2 * np.pi * np.cumsum(60 + 100 * np.exp(-tt * 30)) / sr) * np.exp(-tt * 9))
            else:
                add(tb, 0.35 * rng.uniform(-1, 1, len(tt)) * np.exp(-tt * 20))
            add(tb, tone([melody[(bar * 4 + b) % 8]], beat * 0.9, 0.18, 1.5))
    sf.write(path, y / (np.abs(y).max() * 1.1), sr)


class SongImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import game
        import songmaker
        cls.tmp = tempfile.TemporaryDirectory()
        cls.old_songs, game.SONGS_DIR = game.SONGS_DIR, Path(cls.tmp.name)   # the game finds the audio here
        cls.wav = Path(cls.tmp.name) / "audio" / "groove.wav"
        cls.wav.parent.mkdir()
        synth_song(cls.wav)
        cls.draft = songmaker.load_draft(cls.wav)

    @classmethod
    def tearDownClass(cls):
        import game
        game.SONGS_DIR = cls.old_songs
        cls.tmp.cleanup()

    def test_tempo_downbeat_and_key(self):
        d = self.draft
        self.assertAlmostEqual(d.bpm, 112.0, delta=0.5)
        self.assertAlmostEqual(d.first_beat, 1.3, delta=0.05)
        self.assertEqual(d.key_name, "C major")

    def test_chords_and_melody(self):
        chords, melody, kick, snare = self.draft.per_beat()
        bar_chords = [chords[i] for i in range(0, 32, 4)]
        self.assertEqual(bar_chords, ["C", "G", "Am", "F"] * 2)
        names = [m % 12 for m in melody[0:16:2] if m]
        self.assertGreaterEqual(sum(a == b % 12 for a, b in zip(names, [72, 74, 76, 79, 79, 77, 76, 74])), 7)
        # half-beat steps: beat 1 (step 0) reads as a kick, beat 2 (step 2) as a snare, as the Rhythm chart needs
        self.assertGreater(kick[0], snare[0])
        self.assertGreater(snare[2], kick[2])

    def test_every_chart_makes_a_playable_sheet(self):
        import game
        import songmaker
        from gesture_music import make_lookup
        from gestures import sign_names
        for chart in songmaker.CHARTS:
            for difficulty in songmaker.DIFFICULTIES:
                text = songmaker.make_sheet(self.draft, chart, difficulty)
                path = Path(self.tmp.name) / f"{chart}_{difficulty}.txt"
                path.write_text(text, encoding="utf-8")
                song = game.load_song(path)
                self.assertEqual(song.audio, "audio/groove.wav")
                self.assertAlmostEqual(song.audio_start, self.draft.first_beat, places=2)
                g = game.RhythmGame(lambda e: None)
                n = 8 if song.signs == "Extended" else 4
                g.start(song, make_lookup(song, n), sign_names(song.signs), 0.0)
                self.assertGreaterEqual(len(g.notes), 16, f"{chart} {difficulty}")  # Easy chords: one per bar
                g.stop()


if __name__ == "__main__":
    unittest.main()
