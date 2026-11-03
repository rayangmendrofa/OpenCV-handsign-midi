# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on mido (MIT) with pygame's PortMidi backend. Full credits: CREDITS.md

"""Send the performance as MIDI so it can drive a hardware/software synth or a DAW."""

import threading

import mido

from drums import GM_NOTES
from gestures import BEND_RANGE
from sound_engine import INSTRUMENTS

DRUM_CHANNEL = 9  # MIDI channel 10 (0-based 9) is the General MIDI drum channel
# General MIDI program numbers matching the built-in instruments
PROGRAMS = {name: inst.gm_program for name, inst in INSTRUMENTS.items()}


def _use_available_backend():
    """Prefer python-rtmidi; fall back to pygame's bundled PortMidi (no compiler needed)."""
    try:
        import rtmidi  # noqa: F401
    except ImportError:
        mido.set_backend("mido.backends.pygame")


def list_ports():
    _use_available_backend()
    return mido.get_output_names()


def channel_for(group):
    """Each hand gets its own channel so pitch bend on one hand doesn't bend the other."""
    if group.startswith("loop"):
        return 2 if group.endswith("R") else 3
    if group == "game":  # rhythm game backing track
        return 4
    return 0 if group == "R" else 1


class MidiOut:
    def __init__(self, port_hint=""):
        names = list_ports()
        if port_hint:
            matches = [n for n in names if port_hint.lower() in n.lower()]
            if not matches:
                raise SystemExit(f"No MIDI output matching '{port_hint}'. Available: {names}")
        else:  # only a virtual cable or real device; Windows' built-in synth is too slow to play live
            matches = [n for n in names if not n.startswith("Microsoft")]
            if not matches:
                raise SystemExit(
                    "No MIDI device or virtual cable found. Install loopMIDI and create a port, "
                    "or run --midi \"GS Wavetable\" to test with Windows' built-in synth "
                    "(it adds 100-200 ms of delay, so use it with --mute).")
        self.name = matches[0]
        if "GS Wavetable" in self.name:
            print("Note: Microsoft GS Wavetable Synth adds 100-200 ms of delay. Fine for testing, not for playing.")
        self.port = mido.open_output(self.name)
        self.lock = threading.Lock()   # main thread and looper thread both send
        self.notes = {}                # voice id -> (channel, note) so note_off finds its note
        self.last_bend, self.last_volume = {}, {}
        self.programs = {}             # channel -> program last sent
        print(f"MIDI out -> {self.name}")

    def send(self, event):
        with self.lock:
            self._handle(event)

    def _program(self, ch, instrument):
        """Switch a channel's sound only when its instrument actually changes."""
        program = PROGRAMS.get(instrument)
        if program is not None and self.programs.get(ch) != program:
            self.port.send(mido.Message("program_change", channel=ch, program=program))
            self.programs[ch] = program

    def _off(self, vid):
        if vid in self.notes:
            ch, note = self.notes.pop(vid)
            self.port.send(mido.Message("note_off", channel=ch, note=note))

    def _handle(self, event):
        kind = event[0]
        if kind == "note_on":
            _, vid, note, velocity, group = event[:5]
            self._off(vid)
            ch = channel_for(group)
            if len(event) > 5:
                self._program(ch, event[5])
            self.port.send(mido.Message("note_on", channel=ch, note=note, velocity=max(1, int(velocity * 127))))
            self.notes[vid] = (ch, note)
        elif kind == "note_off":
            self._off(event[1])
        elif kind == "drum":
            name, velocity = event[1], event[2]
            note = GM_NOTES[name]
            self.port.send(mido.Message("note_on", channel=DRUM_CHANNEL, note=note, velocity=max(1, int(velocity * 127))))
            self.port.send(mido.Message("note_off", channel=DRUM_CHANNEL, note=note))
        elif kind == "expr":
            _, group, bend, volume = event
            ch = channel_for(group)
            pitch = int(max(-1.0, min(1.0, bend / BEND_RANGE)) * 8191)
            value = int(volume * 127)
            if self.last_bend.get(ch) != pitch:
                self.port.send(mido.Message("pitchwheel", channel=ch, pitch=pitch))
                self.last_bend[ch] = pitch
            if self.last_volume.get(ch) != value:  # CC 11 = expression (volume swell)
                self.port.send(mido.Message("control_change", channel=ch, control=11, value=value))
                self.last_volume[ch] = value
        elif kind == "all_off":
            for vid in [v for v in self.notes if v[0] == event[1]]:
                self._off(vid)

    def close(self):
        with self.lock:
            for vid in list(self.notes):
                self._off(vid)
            for ch in range(5):
                self.port.send(mido.Message("pitchwheel", channel=ch, pitch=0))
            self.port.close()
