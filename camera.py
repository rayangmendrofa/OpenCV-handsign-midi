# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on OpenCV (Apache 2.0) for webcam capture. Full credits: CREDITS.md

"""Threaded webcam reader that always hands out the newest frame.

Reading the camera on the main thread means every cv2.read() can return a frame that
sat in the driver's buffer while we were busy tracking hands, which adds a frame or
two of delay. Here a background thread keeps draining the camera, and the main loop
only ever sees the latest frame plus the time it arrived.
"""

import threading
import time

import cv2


class Camera:
    def __init__(self, index, width=1280, height=720):
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # DirectShow: 0.75 = automatic exposure
        if not self.cap.isOpened():
            raise SystemExit(f"Could not open camera {index}. Try --camera 1")

        self.cond = threading.Condition()
        self.frame, self.stamp, self.seq = None, 0.0, 0
        self.fps = 0.0
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        last = None
        while self.running:
            ok, frame = self.cap.read()
            now = time.perf_counter()
            if not ok:
                time.sleep(0.01)
                continue
            if last is not None:
                inst = 1.0 / max(now - last, 1e-3)
                self.fps = inst if self.fps == 0 else self.fps + 0.1 * (inst - self.fps)
            last = now
            with self.cond:
                self.frame, self.stamp = frame, now
                self.seq += 1
                self.cond.notify_all()

    def read(self, after_seq, timeout=2.0):
        """Wait for a frame newer than after_seq. Returns (seq, frame, arrival_time) or None."""
        with self.cond:
            if not self.cond.wait_for(lambda: self.seq > after_seq, timeout):
                return None
            return self.seq, self.frame, self.stamp

    def release(self):
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()
