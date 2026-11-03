# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on mido (MIT) for Standard MIDI Files. Full credits: CREDITS.md

"""Standard MIDI files: export what you played (or the loop), and read notes for the song importer.

Export uses the same channels as live MIDI output: right hand 1, left hand 2, loop 3/4, game 5,
drums 10. Instruments become General MIDI program changes, hand-height bend becomes pitch-wheel
messages and volume becomes CC 11, so the file opens in any DAW sounding close to what you heard.
"""

import time
from pathlib import Path

import mido

from drums import GM_NOTES
from gestures import BEND_RANGE
from midi_out import DRUM_CHANNEL, PROGRAMS, channel_for

RECORDINGS_DIR = Path(__file__).parent / "recordings"
TICKS = 480  # per beat


def export(timed_events, path=None, bpm=120.0, name="Gesture Music"):
    """Write [(seconds, event)] (the router's events) to a type-1 MIDI file. Returns the path."""
    if path is None:
        RECORDINGS_DIR.mkdir(exist_ok=True)
        path = RECORDINGS_DIR / f"{name.lower().replace(' ', '-')}-{time.strftime('%Y%m%d-%H%M%S')}.mid"
    def tick(seconds):
        return max(0, round(seconds * bpm / 60 * TICKS))
    per_channel = {}   # channel -> [(tick, order, message)]
    open_notes = {}    # voice id -> (channel, note)
    programs = {}

    def add(ch, t, msg, order=1):
        per_channel.setdefault(ch, []).append((tick(t), order, msg))

    start = min((t for t, _ in timed_events), default=0.0)
    for t, ev in sorted(timed_events, key=lambda e: e[0]):
        t -= start
        kind = ev[0]
        if kind == "note_on":
            _, vid, note, velocity, group = ev[:5]
            ch = channel_for(group)
            if len(ev) > 5 and PROGRAMS.get(ev[5]) is not None and programs.get(ch) != PROGRAMS[ev[5]]:
                programs[ch] = PROGRAMS[ev[5]]
                add(ch, t, mido.Message("program_change", channel=ch, program=programs[ch]), 0)
            if vid in open_notes:
                och, onote = open_notes.pop(vid)
                add(och, t, mido.Message("note_off", channel=och, note=onote), 0)
            note = max(0, min(127, note))
            add(ch, t, mido.Message("note_on", channel=ch, note=note, velocity=max(1, min(127, int(velocity * 127)))))
            open_notes[vid] = (ch, note)
        elif kind == "note_off" and ev[1] in open_notes:
            ch, note = open_notes.pop(ev[1])
            add(ch, t, mido.Message("note_off", channel=ch, note=note), 0)
        elif kind == "drum" and ev[1] in GM_NOTES:
            note, vel = GM_NOTES[ev[1]], max(1, min(127, int(ev[2] * 127)))
            add(DRUM_CHANNEL, t, mido.Message("note_on", channel=DRUM_CHANNEL, note=note, velocity=vel))
            add(DRUM_CHANNEL, t + 0.1, mido.Message("note_off", channel=DRUM_CHANNEL, note=note), 0)
        elif kind == "expr":
            _, group, bend, volume = ev
            ch = channel_for(group)
            add(ch, t, mido.Message("pitchwheel", channel=ch, pitch=int(max(-1, min(1, bend / BEND_RANGE)) * 8191)))
            add(ch, t, mido.Message("control_change", channel=ch, control=11, value=int(volume * 127)))
    end = max((t for t, _ in timed_events), default=0.0) - start
    for vid, (ch, note) in open_notes.items():  # notes still held at the end
        add(ch, end + 0.05, mido.Message("note_off", channel=ch, note=note), 0)

    mid = mido.MidiFile(type=1, ticks_per_beat=TICKS)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=name, time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(meta)
    names = {0: "Right hand", 1: "Left hand", 2: "Loop right", 3: "Loop left", 4: "Game backing", DRUM_CHANNEL: "Drums"}
    for ch in sorted(per_channel):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=names.get(ch, f"Channel {ch + 1}"), time=0))
        last = 0
        for tk, _, msg in sorted(per_channel[ch], key=lambda m: (m[0], m[1])):
            track.append(msg.copy(time=tk - last))
            last = tk
        mid.tracks.append(track)
    mid.save(path)
    return Path(path)


def read_notes(path):
    """Notes in a MIDI file: (tempo bpm, [(start s, length s, pitch, velocity, channel)]).

    Times are in seconds and follow any tempo changes. The first tempo in the file is returned.
    """
    mid = mido.MidiFile(path)
    bpm, now, notes, held = None, 0.0, [], {}
    for msg in mid:  # merged tracks, msg.time in seconds
        now += msg.time
        if msg.type == "set_tempo" and bpm is None:
            bpm = mido.tempo2bpm(msg.tempo)
        elif msg.type == "note_on" and msg.velocity > 0:
            held[(msg.channel, msg.note)] = (now, msg.velocity)
        elif msg.type in ("note_off", "note_on"):
            start = held.pop((msg.channel, msg.note), None)
            if start:
                notes.append((start[0], now - start[0], msg.note, start[1] / 127, msg.channel))
    return bpm or 120.0, sorted(notes)
