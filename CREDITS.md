# Credits

Gesture Music stands on open-source work and published research. Thank you to everyone below.

## Hand tracking and segmentation: Google MediaPipe

The heart of the project is **[MediaPipe](https://github.com/google-ai-edge/mediapipe)** by Google (Apache License 2.0).

- **Hand Landmarker** (`hand_landmarker.task`): finds both hands and 21 landmarks per hand, in image and 3D world coordinates, every frame. Every sign, tap, pump, strike speed, calibration reading and hand-stage model starts from these landmarks.
- **Selfie Segmenter** (`selfie_segmenter.tflite`): separates you from the room for the chromesthesia colour backdrop and the blur.

Both model files are downloaded from Google's model storage on first run and are not included in this repository. Their licences and model cards are on the MediaPipe pages: [Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker) and [Image Segmenter](https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter).

## Libraries

| Library | Used for | Licence |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | hand landmarks, person segmentation | Apache 2.0 |
| [OpenCV](https://github.com/opencv/opencv-python) | webcam capture, image processing, video files | Apache 2.0 |
| [NumPy](https://github.com/numpy/numpy) | synthesis, reverb, music analysis, colour field, statistics | BSD-3-Clause |
| [pygame](https://github.com/pygame/pygame) | the window, drawing, input; PortMidi for MIDI output | LGPL 2.1 |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) / [PortAudio](https://github.com/PortAudio/portaudio) | real-time audio output | MIT |
| [python-soundfile](https://github.com/bastibe/python-soundfile) / [libsndfile](https://github.com/libsndfile/libsndfile) | reading music files | BSD-3-Clause / LGPL 2.1 |
| [mido](https://github.com/mido/mido) | MIDI messages and Standard MIDI Files | MIT |
| tkinter (Python standard library) | open / save dialogs | PSF |
| [FFmpeg](https://ffmpeg.org) (optional, not bundled) | merging demo-capture audio and video | LGPL / GPL |
| [python-docx](https://github.com/python-openxml/python-docx), [reportlab](https://www.reportlab.com/opensource/), [pypdf](https://github.com/py-pdf/pypdf) (docs only) | building the handbook PDFs | MIT / BSD / BSD-3-Clause |

## Ideas and research

- **One Euro filter:** G. Casiez, N. Roussel and D. Vogel, "1€ Filter: A Simple Speed-based Low-pass Filter for Noisy Input in Interactive Systems", CHI 2012. Smooths the hand height.
- **Beat tracking by dynamic programming:** D. P. W. Ellis, "Beat Tracking by Dynamic Programming", Journal of New Music Research 36(1), 2007. Used in the song importer.
- **Key profiles:** C. L. Krumhansl and E. J. Kessler, "Tracing the dynamic changes in perceived tonal organization in a spatial representation of musical keys", Psychological Review 89(4), 1982. Used to detect a song's key.
- **Spectral flux onset detection, chroma features and template chord recognition** with Viterbi smoothing: standard music-information-retrieval techniques, implemented from their textbook descriptions.
- **Freeverb:** the public-domain reverb design by Jezar at Dreampoint (comb and all-pass filters). The reverb here follows its structure.
- **Chromesthesia colours:** after Alexander Scriabin's colour scheme for the *clavier à lumières* in *Prometheus: The Poem of Fire* (1910), in circle-of-fifths order. Background reading: [Chromesthesia](https://en.wikipedia.org/wiki/Chromesthesia).
- **General MIDI:** the standard program and drum-note numbers used for MIDI output and files.

## This project

Gesture Music's own code (everything in this repository except the third-party components above) is released under the MIT License; see [LICENSE](LICENSE). Song sheets you create from your own music, and the music files themselves, stay on your computer and are not part of the repository.
