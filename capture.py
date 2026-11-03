# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on OpenCV for video; FFmpeg (when installed) to merge audio. Full credits: CREDITS.md

"""Demo capture: saves the camera view (MP4) and exactly what you heard (WAV).

If ffmpeg is installed, the two are merged into one shareable video.
"""

import shutil
import subprocess
import time
import wave
from pathlib import Path

import cv2
import numpy as np

from sound_engine import SAMPLE_RATE

FPS = 30
OUT_DIR = Path(__file__).parent / "demos"


class DemoCapture:
    def __init__(self, engine):
        self.engine = engine
        self.writer = None

    @property
    def active(self):
        return self.writer is not None

    def start(self, frame):
        OUT_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.video_path = OUT_DIR / f"demo-{stamp}-video.mp4"
        self.audio_path = OUT_DIR / f"demo-{stamp}-audio.wav"
        self.final_path = OUT_DIR / f"demo-{stamp}.mp4"
        h, w = frame.shape[:2]
        self.size = (w - w % 2, h - h % 2)  # most video players want even dimensions
        self.writer = cv2.VideoWriter(str(self.video_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, self.size)
        self.engine.capture = []
        self.started = time.perf_counter()
        self.frames = 0

    def add_frame(self, frame):
        if (frame.shape[1], frame.shape[0]) != self.size:  # the window was resized mid-recording
            frame = cv2.resize(frame, self.size)
        # Camera FPS varies, so repeat frames as needed to stay in sync with real time
        due = int((time.perf_counter() - self.started) * FPS) + 1
        while self.frames < due:
            self.writer.write(frame)
            self.frames += 1

    def stop(self):
        blocks, self.engine.capture = self.engine.capture or [], None
        self.writer.release()
        self.writer = None

        audio = np.concatenate(blocks) if blocks else np.zeros(1, np.float32)
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(self.audio_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(self.video_path),
                            "-i", str(self.audio_path), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", str(self.final_path)], check=False)
            if self.final_path.exists():
                return f"Saved {self.final_path}"
        return f"Saved {self.video_path.name} + {self.audio_path.name} (install ffmpeg to auto-merge)"
