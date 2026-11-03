# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on Google MediaPipe Selfie Segmenter (Apache 2.0); OpenCV. Full credits: CREDITS.md

"""Camera backdrop: keep you (and your hands) sharp and change everything behind you.

Two looks:
  Colour  the room is replaced by the chromesthesia colour field (synesthesia.py), which follows
          the notes you play, with a soft rim of the strongest note's colour around you
  Blur    the room is softly blurred

MediaPipe's selfie segmenter gives a per-pixel "this is a person" confidence. The backdrop is
only for what's shown and captured; hand tracking always uses the sharp frame. To keep it
cheap, segmentation and the backdrop are computed on small copies of the frame.
"""

import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions, RunningMode

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
    "selfie_segmenter/float16/latest/selfie_segmenter.tflite"
)
MODEL_PATH = Path(__file__).parent / "selfie_segmenter.tflite"
WORK_SIZE = (320, 180)   # segment and blur at this size, then scale up
BLUR_KERNEL = 21         # at WORK_SIZE; about 85 px at 1280x720
MASK_SMOOTHING = 0.5     # blend with last frame's mask so edges don't flicker
ROOM_SHOW_THROUGH = 0.12 # Colour look: a hint of the blurred room keeps some depth
RIM_GLOW = 0.9           # Colour look: strength of the coloured outline


def ensure_model():
    if not MODEL_PATH.exists():
        print(f"Downloading background model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return str(MODEL_PATH)


class Background:
    def __init__(self):
        self.segmenter = ImageSegmenter.create_from_options(ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=ensure_model()),
            running_mode=RunningMode.VIDEO,
            output_confidence_masks=True,
        ))
        self.mask = None
        self.last_ts = 0

    def apply(self, frame, timestamp_ms, colour=None):
        """A copy of the BGR frame with the background blurred, or (colour = a Synesthesia) recoloured."""
        h, w = frame.shape[:2]
        small = cv2.resize(frame, WORK_SIZE, interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        ts = max(timestamp_ms, self.last_ts + 1)
        self.last_ts = ts
        result = self.segmenter.segment_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
        person = result.confidence_masks[0].numpy_view().astype(np.float32).reshape(WORK_SIZE[1], WORK_SIZE[0])

        # Soften and steady the edge, then scale up to full size
        person = cv2.GaussianBlur(person, (7, 7), 0)
        if self.mask is not None:
            person = MASK_SMOOTHING * self.mask + (1 - MASK_SMOOTHING) * person
        self.mask = person
        alpha = cv2.resize(person, (w, h), interpolation=cv2.INTER_LINEAR)

        soft = cv2.GaussianBlur(small, (BLUR_KERNEL, BLUR_KERNEL), 0)
        if colour is not None:
            field = cv2.resize(colour.render()[..., ::-1], WORK_SIZE, interpolation=cv2.INTER_CUBIC)
            back = field * (255 * (1 - ROOM_SHOW_THROUGH)) + soft * ROOM_SHOW_THROUGH
            # rim light: strongest just outside your outline, in the colour of the loudest note
            edge = cv2.GaussianBlur(np.clip(4 * person * (1 - person), 0, 1), (15, 15), 0)
            back += edge[..., None] * (RIM_GLOW * 255) * colour.accent[::-1]
            soft = np.clip(back, 0, 255).astype(np.uint8)
        back = cv2.resize(soft, (w, h), interpolation=cv2.INTER_LINEAR)
        # cv2.blendLinear does the per-pixel mix in C: ~2 ms vs ~28 ms with numpy floats
        return cv2.blendLinear(frame, back, alpha, 1.0 - alpha)

    def close(self):
        self.segmenter.close()
