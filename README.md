# Gesture Music

*A webcam instrument played with hand signs. Hand tracking by [Google MediaPipe](https://github.com/google-ai-edge/mediapipe); see [Credits](#credits-and-licence).*

A computer-vision instrument. A webcam tracks both hands, and hand signs play notes, chords and drums. How fast you strike a sign sets how loud it plays, hand height bends pitch or controls volume, and everything can be looped in layers over a metronome. A rhythm game scores you against timed song sheets that it can make from your own music files, and the performance can drive a real synth or DAW over MIDI or be saved as a MIDI file.

## The window
```
┌ top bar: mode · signs · key · octave − + · height · sustain · backdrop · rhythm game ▶ ⏭ · Settings ┐
├──────────────── CAMERA ───────────────┬──────────────── HAND STAGE ─────────────────┤
│ your mirrored camera view, skeletons, │ your tracked hands redrawn as 3D models on a │
│ L/R badges, the note on each hand     │ plain background, with motion trails; raised │
│ NOW PLAYING: 5-octave keyboard        │ fingers glow, half-bent fingers turn amber   │
├──────── rhythm-game lanes (while a song plays) or the calibration wizard ──────────┤
├── LEFT HAND  instrument ▾ · one pad per sign ──┬── RIGHT HAND  instrument ▾ · pads ──┤
└ footer: looper · BPM · click · quantise · REC · messages · camera fps / latency ─────┘
```
- **Everything is clickable.** The chips at the top cycle their setting; clicking a pad plays it, so you can try sounds without the camera.
- **Hand stage:** choose its background colour (5 solid colours), view angle (front, three-quarter, side) and trails from the buttons in its corner, or with `k` and `o`. The models are built from MediaPipe's 3D world landmarks, so they keep the same size whether your hand is near or far, and move around the stage as your hands move.
- **Settings (Tab):** *Instruments* (instrument, volume and reverb per hand, strike dynamics), *Key mapping* (any note, chord or drum on each sign, plus named presets), *Looper & MIDI*, *Sessions*, *Songs* (add your own music), *Calibrate*, *Display* and *Keys*. Long tabs scroll with the mouse wheel.
- The window is sharp on high-DPI screens (it follows Windows display scaling), resizable, and goes full screen with F11.
- Your choices (instruments, mixer, mapping, calibration, looper tempo, colours, mode, key, offsets...) are saved in `settings.json` and restored next time.

## Features
| | |
|---|---|
| **Instruments** | 10 synthesized instruments (Piano, Electric piano, Organ, Strings, Pluck, Bass, Synth lead, Bell, Marimba, Flute), chosen **separately for each hand** |
| **Mixer** | Volume and reverb for each hand (Settings > Instruments) |
| **Dynamics** | A quick, snappy sign plays louder than a slow one (`i` turns it off) |
| **Calibration** | `F2`: hold each sign for 2 s and the finger thresholds are fitted to your hands |
| **Key mapping** | Custom mode: give every sign on each hand its own note, chord or drum; save, load, import and export named presets |
| **Hand stage** | Your hands redrawn as clean 3D models on a single-colour background, with trails, to see your movement clearly |
| **Hand signs** | Basic: 1–4 fingers. Extended (`x`): 8 signs per hand, a full octave on one hand. Fist = silence |
| **Repeat the same note** | Without changing sign: **tap** (fold the raised fingers halfway and straighten) or **pump** (quick downward flick of the hand) |
| **Chromesthesia backdrop** | `b`: the room behind you becomes a flowing colour field that answers the notes you play (or a blur, or off) |
| **Clear left/right** | The hand on the left half of the screen is your left hand. Each hand is drawn in its own colour with an L/R badge |
| **Rhythm game** | Timed song sheets scroll toward a hit line; make the right sign on the beat. A see-through **ghost hand** on the stage shows your next sign. Perfect/Good/Miss, combo, grade, best scores |
| **Your own songs** | Add an MP3/WAV/FLAC/OGG or MIDI file: the app finds the tempo, bar 1, key, chords and melody and writes a song sheet (melody, chords or rhythm chart; easy, normal or hard). Your music plays along in the game |
| **Chords** | One sign plays a full chord, so two hands can be a whole band |
| **Sustain** | `space` lets notes ring after you let go, for building up layered sounds |
| **Hand-height expression** | *Volume*: raise your hand for louder. *Bend*: move up/down while holding a sign to bend ±2 semitones |
| **Drums** | 12-piece synthesized kit, or drop your own WAVs into `samples/` |
| **MIDI out** | Each hand gets its own channel, drums go to GM channel 10, plus pitch bend and CC11 expression |
| **Looper** | Record a phrase, then overdub layers, undo, stop or clear. Metronome, one-bar count-in, quantise (1/4, 1/8, 1/16), tempo |
| **MIDI files** | `F7` records everything you play, `F8` exports the loop; both open in any DAW |
| **Hand sessions** | `F5` records your hand movements (landmarks only, no images); replay them for testing, debugging or a camera-free demo (`--demo`) |
| **Demo capture** | Records the whole window plus the exact audio for sharing |
| **Pinch style** | `g` switches to touching your thumb to a fingertip instead of signs |

## Hand signs
| Slot | Sign | Basic | Extended |
|---|---|---|---|
| 1 | index up | ✓ | ✓ |
| 2 | index + middle (peace) | ✓ | ✓ |
| 3 | index + middle + ring | ✓ | ✓ |
| 4 | four fingers up | ✓ (thumb ignored) | ✓ **thumb tucked across the palm** |
| 5 | open hand, all five spread | | ✓ |
| 6 | thumbs up | | ✓ |
| 7 | rock (index + pinky) | | ✓ |
| 8 | call me (pinky, thumb optional) | | ✓ |
| – | fist | silence | silence (thumb wrapped over the fingers) |

- Keep your **palm facing the camera**. Changing sign changes the note.
- To **repeat the same note**, keep the sign and do one of these (the screen flashes TAP or PUMP when it registers):
  - **Tap:** fold your raised fingers about halfway forward, then straighten them. The note plays again as they straighten. For thumbs up, bend and straighten the thumb. It's measured against your own straight-finger position, so it doesn't need a full fist.
  - **Pump:** a quick downward flick of the whole hand, like knocking. Lift the hand back up before the next one. Off in Bend mode, where moving your hand bends the pitch.
  - **Fist:** close to a fist and open again also still works. If the fist is too quick to register, it counts as a tap.
- Shapes that aren't one of the signs are ignored. That includes the in-between shapes while you change sign. A new sign must be seen for 2 frames before it plays.
- A finger counts as **up** when it bends less than 90° in total across its three joints, and **down** past 140°. In between, it keeps its last state. Calibration (below) replaces these defaults with thresholds fitted to each of your fingers.
- In the Extended set, the thumb only matters for 4 fingers vs open hand, and for fist vs thumbs up. For "4 fingers", tuck the thumb across your palm; if it sticks out, that's "open hand".

## Which hand is which
The app doesn't use MediaPipe's own left/right guess, because it flips too easily. Instead:
- **Two hands:** the one further left on screen is your left hand.
- **One hand:** the half of the screen it's in decides. Near the dashed centre line, it keeps whatever label it had, so it can't flicker while crossing.
- If tracking drops a hand for up to 0.2 s, its notes keep playing instead of cutting out.
- Each hand is drawn in its colour (left blue, right orange) with an **L** or **R** badge on the wrist. Press `h` if they're ever backwards.

## Modes (`m`)
| Mode | Right hand | Left hand |
|---|---|---|
| Notes | Basic: scale notes 1-4. Extended: notes 1-8 | Basic: notes 5-8. Extended: notes 1-8 an octave lower |
| Chords | Basic: I IV V vi (C F G Am). Extended: I ii iii IV V vi vii° I | melody notes, an octave up |
| Drums | kick, snare, hat, open hat (+ clap, toms, crash) | clap, toms, crash (Extended: ride, rim, cowbell, shaker, ...) |
| Band | chords, as in Chords mode | kick, snare, hat, clap (+ open hat, crash, toms) |
| Custom | your own mapping (Settings > Key mapping) | your own mapping |
| Song | whatever the selected song sheet assigns (`right:` line) | whatever it assigns (`left:` line) |

### Custom mode: assign your own sounds
Press Tab, open **Key mapping**, pick a hand and a sign, then choose a **Note** (click a key on the two-octave keyboard), a **Chord** (a root plus a type: maj, m, 7, maj7, m7, 6, m6, sus2, sus4, dim, aug, add9) or a **Drum**. Each choice plays a preview and switches you to Custom mode. "Start from a built-in layout" copies Notes, Chords, Drums or Band into Custom as a starting point. The mapping has 8 sounds per hand; signs 5–8 need the Extended sign set. It starts as a two-octave keyboard (left hand C3–C4, right hand C4–C5).

### Instruments
Each hand has its own instrument: click the instrument button above its pads, use Settings > Instruments, or press `t` (right) / `y` (left). Bass plays an octave lower. Loops keep the instrument they were recorded with, and over MIDI each hand's channel gets the matching General MIDI program.

## Calibration (F2)
Everyone's hands bend differently, and cameras and lighting change what the tracker sees, so fixed thresholds are the main cause of misread signs. Press `F2` (or Settings > Calibrate) and follow the strip that appears above the pads:
1. It shows a picture of each sign in turn: a fist, then every sign of your current set (5 steps for Basic, 9 for Extended, about 3.5 s each).
2. You get 1.5 s to form the sign, then hold it for 2 s. Move it a little while holding, so the fit covers how you really play. A dot per finger turns green when that finger is read correctly. Both hands are calibrated at once; `Skip` passes over a sign you can't make.
3. For every finger, the app collects how bent it is when it should be up and when it should be down, and puts the two thresholds 30% of the way into the gap from each side, keeping the middle 40% as the "keep last state" zone. Extended calibration also fits the thumb.
4. The results card shows each finger's up range (green) and down range (grey) with the new thresholds, warns about fingers whose ranges overlap, and re-checks every recorded frame: the score per sign is how often it would have been read correctly. **Save**, **Try again** or **Discard**.

Thresholds are saved per hand in `settings.json`; Settings > Calibrate shows them and can reset to the defaults.

## Dynamics, mixer and reverb
- **Strike speed:** each time a sign starts, the app measures how fast the fingers moved over the last 0.15 s (or how fast the hand moved, for a pump) and maps it to a velocity from 0.3 to 1.0. A snappy sign plays louder, a slow one softer, and MIDI gets the same velocity. Press `i` to switch it off (every sign at the same loudness). Hand-height *Volume* mode takes over when it is on.
- **Mixer:** Settings > Instruments has a volume and a reverb slider for each hand. The reverb is a Freeverb-style room (4 comb and 2 all-pass filters) on a send, so each hand can be drier or wetter.

## Looper
`r` records, `r` again sets the loop length and starts playback; later presses toggle overdub. `p` play/stop, `u` undo the last layer, `c` clear.
- **Metronome** (`z`): a click on every beat, louder on the first beat of each bar.
- **Count-in:** the first recording starts after one bar of clicks, so you come in on time.
- **Quantise** (`w`: Off, 1/4, 1/8, 1/16): each note's start moves to the nearest grid step and keeps its length.
- **Tempo:** `-` and `=`, or Settings > Looper & MIDI. With the metronome or quantise on, the first take is rounded to whole bars.

## MIDI files
`F7` starts recording everything you play live; press it again to save `recordings/performance-<date-time>.mid`. `F8` saves the loop (all layers, one cycle) as `recordings/loop-<date-time>.mid`. Files are type 1 with one track per channel (left hand, right hand, loop layers, drums on channel 10), General MIDI program changes for each instrument, velocities, pitch bend and expression, at the looper's tempo.

## Hand sessions and demo mode
`F5` records a **session**: the 21 tracked points of each hand, 30 times a second, to `sessions/session-<time>.gmsession` (compressed text, about 20 KB per second). No camera images are stored. Uses:
- **Debugging:** replay the moment a sign was misread with the `d` view on, and try other settings on exactly the same movement.
- **Testing:** a session is repeatable input for the app.
- **Demo without a camera:** `gesture_music.py --demo` replays the built-in demo (Band mode at 96 BPM: C G Am F on the right hand, kick and snare with taps on the left; your saved mode is left alone), and `--replay FILE` replays any session. `F6` replays your latest session or stops a replay; Settings > Sessions lists them all.

## Rhythm game
1. Add a song first (next section). Press `n` to pick a song (shown at the top right) and `j` to start.
2. Notes scroll right to left in a lane for each hand. Each block shows what it plays (`Am`) and the sign to make (`4 fingers`). A **ghost hand** on the hand stage shows each hand's next sign over your own hand, with a ring that fills as the note gets closer; it turns green when you're already making the right sign.
3. Make the sign as the block reaches the white line. Within ±0.10 s is **Perfect**, within ±0.22 s is **Good**, and later is a **Miss**. The strip under the lanes is the sheet: what to play in this bar and the next three.
4. At the end you get a grade (S/A/B/C/D) and your best score per song, saved in `scores.json`.

Timing is judged from the camera frame where your sign first appeared, not when it was confirmed. If you're consistently "late", your camera has extra delay: press `.` to shift the timing window (shown as `offset`, and remembered), or start with `--game-offset 60`.

### Adding your own music
No songs come with the app: you add the music you want to play. Press `a` (or Settings > Songs > Add a music file).
1. **Choose a file:** MP3, WAV, FLAC, OGG or AIFF audio, or a MIDI file (.mid).
2. **The app analyses it** (a few seconds):
   - *tempo* from how regularly the sound suddenly gets louder (spectral flux and autocorrelation), then a beat tracker that follows the actual beats and a straight-line fit for one steady tempo;
   - *bar 1* from which beat of four has the strongest bass hits;
   - *key* by comparing the song's pitch content with major and minor key profiles;
   - *chords* per beat by matching pitch content against 24 chord shapes, smoothed so chords don't flicker;
   - *melody* per half beat as the highest strong pitch in the singing range (the tune usually sits on top);
   - *kick and snare* from low and high frequency hits, for rhythm charts.

   MIDI files skip the guessing: their notes, tempo and chords are read exactly.
3. **Check and correct it.** *Listen with clicks* plays the music with a rim click on every beat (loud on bar 1). If the clicks drift, fix the tempo (±0.1, ±1, ×2, ÷2); if they're steady but off, move bar 1 (±0.01 s, ±1 beat). Or **tap Space on every beat** while listening, starting on a bar's first beat: 4 or more taps set both for you.
4. **Pick a chart and difficulty:** *Melody* (the tune note by note: low notes on the left hand, high on the right), *Chords* (the chord changes) or *Rhythm* (kick and snare on the left hand, hi-hat on the right). Easy, Normal or Hard set how often notes change. A preview shows the pads and the first bars.
5. **Create song.** The sheet is written to `songs/<title>.txt` and the music is copied to `songs/audio/`. In the game the music plays with bar 1 lined up to the sheet.

The analysis works well on music with a clear beat; melody detection on full mixes is approximate (vocals, solos and harmony all compete), so treat the melody chart as a starting point. Sheets are plain text in [`songs/`](songs/README.md), so you can fix any note afterwards. You can also write sheets by hand: one token per beat, `-` to hold, `.` for rest, backing chords, bass and drums, a chord for every sign (`mode: Song`), full chord names like `D#m6/F#`, and repeats with `( ... ) x4`.

## Setup
```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python gesture_music.py
```
On first run the script downloads two models from Google: the hand model (`hand_landmarker.task`, about 7.8 MB) and the background model (`selfie_segmenter.tflite`, about 250 KB).

No camera handy? Run `.venv\Scripts\python gesture_music.py --demo`.

Run the tests (no camera or sound card needed; nothing in your own folders is touched):
```
.venv\Scripts\python -m unittest discover tests -v
```

## Camera backdrop: chromesthesia colours
[Chromesthesia](https://en.wikipedia.org/wiki/Chromesthesia) is hearing sounds as colours. Press `b` to cycle the backdrop behind you: **Colour** → **Blur** → **Off** (also in Settings > Display, with a colour key).
- **Colour** replaces the room with a slowly mutating gradient. Each pitch class has Scriabin's colour (from his *clavier à lumières*), laid out in circle-of-fifths order: C red, G orange, D yellow, A green, E pale sky blue, B bluish white, F# bright blue, C# violet, G# lilac, D# and A# steely rose, F deep red. Neighbours on the circle of fifths sound consonant, so harmonious chords give neighbouring colours.
- Every note **blooms** around you at its place on that colour wheel (C at the top, clockwise by fifths), low octaves near the middle and high ones further out, so a chord's notes bloom in different places. Louder notes bloom bigger; higher notes are paler, lower ones deeper. Blooms drift outward like ink in water and fade after you release.
- Behind the blooms, two colours flow and fold over each other, gliding (over about a second) toward the harmony being played, and back to deep indigo in silence. A soft rim of the loudest note's colour outlines you.
- Kicks pulse the brightness, snares and claps flash, cymbals sparkle. Metronome clicks don't.
- It reacts to everything that sounds: your hands, loops, the game's backing. In a replay (`--demo`) the colour field fills the camera panel.

MediaPipe's selfie segmenter finds you in each frame; only the room behind you changes, on screen and in demo captures. Hand tracking always uses the sharp image, so the backdrop can't affect recognition. It runs on a background thread at the same time as hand tracking.

| Option | |
|---|---|
| `--camera 1` | use a different webcam |
| `--root 48` | start an octave lower (MIDI note number) |
| `--signs extended` | start with 8 signs per hand |
| `--style pinch` | start in pinch style instead of hand signs |
| `--confirm 2` | frames a new hand sign must be held before it plays; 1 is fastest, 3 is steadiest |
| `--game-offset 60` | rhythm game: your camera's delay in ms |
| `--no-blur` | start with the plain camera backdrop (`b` cycles colour / blur / off) |
| `--window 1600x900` | window size in pixels (default: fits your screen) |
| `--demo` | replay the built-in demo session instead of using the camera |
| `--replay FILE` | replay a recorded hand session instead of using the camera |
| `--no-camera` | stay without a camera after a replay is stopped |
| `--midi` / `--midi loopMIDI` | send MIDI to a virtual cable or MIDI device |
| `--list-midi` | list MIDI ports |
| `--mute` | MIDI only, no built-in sound |
| `--lookahead 40` | pinch style: trigger fast pinches this many ms early (0 = off) |

## Getting it responsive
The footer shows `camera fps · tracking ms · frame→sound ms`. Press `d` for live per-finger measurements. Each finger's bend is shown against the 90° and 140° lines, and the thumb row shows its distance from the pinky knuckle against the in/out lines.

- **Light matters most.** Webcams slow down in dim rooms, often from 30 fps to 10 fps. Light your hands from the front. The app warns you when the camera drops below 24 fps.
- **Keep both hands in view.** MediaPipe searches the whole image every frame until it has found both hands.
- **Don't play live through Windows' GS Wavetable synth.** It adds 100–200 ms.
- **If a sign isn't recognised**, run the calibration (`F2`). The `d` view shows each finger against its thresholds; record a session (`F5`) of the problem and replay it while you look.

### MIDI into a DAW (Ableton, FL Studio, Reaper...)
1. Install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) and create a port.
2. Run `gesture_music.py --midi loopMIDI --mute`.
3. In your DAW, enable loopMIDI as a MIDI input. Channels: 1-2 live hands, 3-4 loop, 5 game backing, 10 drums.

### Custom drum samples
Put 16-bit WAV files in `samples/` named after a drum: `kick`, `snare`, `hat`, `open_hat`, `clap`, `tom_low`, `tom_high`, `crash`, `ride`, `rim`, `cowbell`, `shaker` (`.wav`).

## Controls
| Key | Action |
|---|---|
| `m` / `M` | Mode: Notes / Chords / Drums / Band / Custom / Song (next / previous) |
| `x` | Sign set: Basic (4) / Extended (8) |
| `g` | Gesture style: hand signs / pinch |
| `n` / `j` | Rhythm game: next song / start or stop |
| `,` `.` | Rhythm game timing offset −/+ 10 ms |
| `e` | Hand height: Off / Volume / Bend |
| `i` | Strike speed sets loudness on/off |
| `space` | Sustain on/off |
| `s` | Scale: Major, Minor, Pentatonic, Blues |
| `[` `]` | Octave down / up |
| `t` / `T` | Right hand: next / previous instrument |
| `y` / `Y` | Left hand: next / previous instrument |
| `r` | Record. First press starts, second sets loop length; then toggles overdub |
| `p` / `u` / `c` | Loop play/stop / undo last layer / clear |
| `z` / `w` | Loop metronome on/off / quantise Off, 1/4, 1/8, 1/16 |
| `-` `=` | Loop tempo −/+ 1 BPM |
| `a` | Add a song from a music or MIDI file |
| `F2` | Calibrate your hands |
| `F5` / `F6` | Record a hand session / replay the latest (or stop) |
| `F7` / `F8` | Record a MIDI file / export the loop as MIDI |
| `v` | Start / stop demo capture (saved to `demos/`) |
| `b` | Camera backdrop: Colour (chromesthesia) / Blur / Off |
| `d` | Debug view: live finger measurements, plus the tap fold and pump speed |
| `h` | Swap hands |
| `l` | Skeleton on the camera view on/off |
| `k` / `o` | Hand stage: background colour / view angle |
| `Tab` | Settings |
| `F11` | Full screen |
| `Esc` | Cancel calibration, or close the settings panel or menu (quits if nothing is open) |
| `q` | Quit |
| mouse | Click chips to change settings, click pads to play them |

## How it works
```
webcam ─► camera.py (newest frame) ─► MediaPipe landmarks ─► assign L/R by screen side
                                 session.py (record / replay) ◄──►│
                                                                  │
                                                     gestures.py (signs + height)
                                                                  │ events
                                                                  ▼
                       game.py (backing + judging) ───►  Router (gesture_music.py)
                                             ┌────────────────┼─────────────────┐
                                             ▼                ▼                 ▼
                                     sound_engine.py     midi_out.py        looper.py ──► replays events
                                     (real-time synth)   (DAW / synth)      (record)       back to Router
                                                         midi_file.py (F7 / F8: .mid files)
```
Every musical action is a small **event** tuple, such as `("note_on", id, note, velocity, hand, instrument)`, `("drum", "kick", velocity, hand)`, `("expr", hand, bend, volume)` or `("track", samples, start_time)` for a song's music. The synth, MIDI, looper and MIDI-file recorder all take the same events, and the game's backing track uses them too.

| File | Role |
|---|---|
| `gesture_music.py` | the `App`: state and one method per action, the per-frame loop, hand sides, modes and chords, Custom mapping, sustain, event router |
| `ui.py` | the pygame window: top bar, camera view with now-playing keyboard, hand stage, pads, game lanes, settings panel, mouse and keys |
| `settings.py` | loads and saves `settings.json`; key-mapping presets in `mappings/` |
| `calibration.py` | the calibration wizard: steps, sample collection, threshold fitting, per-sign scores |
| `handmodel.py` | a synthetic 3D hand for any sign: ghost hints, calibration pictures, the demo session and the tests |
| `session.py` | records and replays hand sessions (`sessions/*.gmsession`) |
| `midi_file.py` | writes performances and loops as standard MIDI files; reads MIDI files for the song importer |
| `audio_analysis.py` | tempo, beats, bar start, key, chords, melody, kick and snare from an audio file (NumPy only) |
| `songmaker.py` | turns an analysed file into song sheets; the Songs tab's import, preview and tap-tempo logic |
| `camera.py` | background thread that always delivers the newest camera frame |
| `background.py` | selfie segmentation + the camera backdrop (colour field or blur), run alongside hand tracking |
| `synesthesia.py` | the chromesthesia colour field: note colours, blooms, flowing gradient, drum pulses |
| `gestures.py` | sign sets from 3D finger joint angles and thumb position, with thresholds and 2-frame confirmation; tap and pump repeats; pinch detection; filtered hand height |
| `game.py` | song sheet parser, rhythm game timing/judging/scoring, backing track and metronome |
| `songs/` | your song sheets (see `songs/README.md`); music files in `songs/audio/` |
| `sound_engine.py` | real-time additive synth in a `sounddevice` callback; 10 instruments (partials, attack, release, vibrato, octave shift); per-hand volume and reverb send; song music playback |
| `drums.py` | synthesized 12-piece drum kit + WAV loader + General MIDI drum map |
| `midi_out.py` | event → MIDI (notes, pitch wheel, CC11, program change) via `mido` |
| `looper.py` | timestamped event recording, layered overdubs, metronome, count-in, quantise, playback on a 2 ms timer thread |
| `capture.py` | MP4 + WAV demo recorder, merged with ffmpeg when available |
| `tools/make_demo_session.py` | regenerates `sessions/demo.gmsession` from the synthetic hand |
| `tests/` | unit tests: signs, strike speed, calibration, looper quantise, MIDI files, sessions, presets, song import |

## Credits and licence
Gesture Music is built on **[Google MediaPipe](https://github.com/google-ai-edge/mediapipe)** (Apache 2.0): its Hand Landmarker tracks your hands and its Selfie Segmenter separates you from the backdrop. It also uses OpenCV, NumPy, pygame, sounddevice/PortAudio, soundfile/libsndfile and mido, and ideas from published research (the One Euro filter, Ellis's beat tracker, Krumhansl–Kessler key profiles, Freeverb, Scriabin's colours). [CREDITS.md](CREDITS.md) lists every library, its licence and the sources.

The project's own code is released under the [MIT License](LICENSE). © 2026 rayangmendrofa.
