# Song sheets

Each `.txt` file here is one song for the rhythm game. Press `n` in the app to pick a song and `j` to start or stop it. Files are listed in name order.

No songs are included. The easiest way to make one is from your own music: press `a` in the app (or Settings > Songs), choose an audio or MIDI file, check the tempo and bar 1 by listening with clicks, pick a chart and create it. That writes a sheet here and copies the music to `audio/`. Generated sheets are ordinary sheets: open them in any text editor to fix a note, change a hand or simplify a passage. You can also write a sheet from scratch, as below.

```
title: Four Chord Jam
bpm: 80
mode: Band            # Notes, Chords, Drums, Band, Custom or Song
scale: Major          # Major, Minor, Pentatonic or Blues
root: 60              # MIDI note of the key (60 = C4)
signs: Basic          # Basic (4 per hand) or Extended (8 per hand)
beats per bar: 4      # optional, default 4
steps per beat: 1     # optional; 2 = each token is an eighth note
count in: 4           # optional; clicks before the song starts
metronome: on         # optional; quiet click on every beat

play r: C - - - | G - - - | Am - - - | F - - - |
play l: Kick . Snare . | Kick . Snare . |
backing: C3 - - - | G2 - - - |
```

## Playing along with a recording
```
audio: audio/my_song.mp3   # a music file in this folder (usually songs/audio/)
audio start: 1.286         # seconds into the music where bar 1 begins
count in: 0                # the music itself leads you in
metronome: off
```
The music starts early enough for the first notes to scroll in, and bar 1 of the sheet lands exactly at `audio start`. If the notes feel early or late against the music, change `audio start` by a few hundredths of a second; if they drift apart over the song, the `bpm` is slightly off. Anything you'd rather hear than play can still go on `backing:` lines.

## Tokens
One token per step (a beat, unless `steps per beat` says otherwise).

| Token | Meaning |
|---|---|
| a sound | a note to play, e.g. `E4`, `Am`, `Kick`, `Open_hat` |
| `-` | keep holding the previous sound |
| `.` | rest |
| `\|` | bar line, only for readability |

## Repeats and comments
- `( C - - - | G - - - ) x4` plays the bracketed part 4 times. Groups can be nested, and the brackets need spaces around them.
- A comment starts with `# ` (hash + space). A `#` inside a name like `D#m` is part of the chord.

## Song mode: your own sound for every sign
For songs whose chords don't fit the built-in modes, set `mode: Song` and list what each sign plays, in sign order (1 finger, 2 fingers, 3 fingers, 4 fingers, then with Extended signs: open hand, thumbs up, rock, call me):
```
mode: Song
signs: Extended
right: G#  D#m6/F#  F7sus  E6  D#m7  A#m/F  C#m  A#m7
left:  Fm  C#  D#  D#7  D#6  A#m7/F
```
Each hand can have up to 8 sounds (4 with Basic signs); missing ones show as `-`. Sounds can be chords, notes or drums. Press `m` until the mode shows **Song** to play the selected song's pads freely, outside the game.

## Chord names
Root (`C`, `F#`, `Bb`...) + type + optional slash bass: `Am`, `G7`, `Fmaj7`, `D#m6/F#`, `A#m7/F`. Types: major, `m`, `dim`, `aug`, `6`, `m6`, `7`, `maj7`, `m7`, `m7b5`, `dim7`, `mmaj7`, `sus2`, `sus4`/`sus`, `7sus4`/`7sus`, `add9`, `madd9`, `9`, `m9`, `maj9`. Single notes use octaves 0–5 (`C4`, `F#2`); a name ending in 6, 7 or 9 is always a chord, so `E6` is E sixth, not a high E.

## Tracks
- `play:` lines are what **you** play. Each sound is matched to the hand and sign that plays it in the song's mode. `play r:` or `play l:` forces a hand. Lines with the same name join end to end.
- `backing:` lines play automatically: chords (`C`, `Am`, `G7`, `Fmaj7`, `Dsus4`...), notes (`C3`, `F#2`...) or drums (`kick`, `hat`, `ride`...). Use different names (`backing bass:`, `backing hats:`) for parts that play at the same time.

## What each sign plays
Basic signs: 1–4 fingers. Extended adds open hand, thumbs up, rock (index + pinky) and call me (pinky).

| Mode | Right hand | Left hand |
|---|---|---|
| Notes, Basic | C4 D4 E4 F4 | G4 A4 B4 C5 |
| Notes, Extended | C4 D4 E4 F4 G4 A4 B4 C5 | the same, an octave lower |
| Chords, Basic | C F G Am | melody G5 A5 B5 C6 |
| Chords, Extended | C Dm Em F G Am Bdim C | melody C5 to C6 |
| Drums, Basic | Kick Snare Hat Open hat | Clap Tom lo Tom hi Crash |
| Band, Basic | C F G Am | Kick Snare Hat Clap |

These are for C major with root 60; other keys and scales shift accordingly. If a sheet uses a sound the mode can't play, the app tells you which sounds are available.
