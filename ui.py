# Gesture Music: a webcam instrument played with hand signs
# Copyright (c) 2026 rayangmendrofa. MIT License (see LICENSE).
# Built on pygame (LGPL 2.1) for the window; OpenCV for camera frames. Full credits: CREDITS.md

"""The window: camera view, hand stage, pads, rhythm-game lanes and the settings panel (pygame).

Layout, top to bottom:
  top bar      title and clickable chips (mode, signs, key, height, sustain, backdrop, song, settings)
  main area    camera view (left) | hand stage: your tracked hands redrawn on a plain background (right)
  game lanes   only while a rhythm-game song is playing
  pads         one strip per hand: instrument button and a pad per sign (click a pad to play it)
  footer       looper, messages, performance

The UI never imports gesture_music directly: it reads the mapping tables through the module
the App was defined in, so there is only ever one copy of them (gesture_music.py is usually
run as __main__, and importing it by name would create a second copy).
"""

import ctypes
import math
import os
import sys
import time
from collections import deque

import cv2
import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

import calibration  # noqa: E402
import handmodel  # noqa: E402
import settings as settings_store  # noqa: E402
from drums import DRUMS, LABELS  # noqa: E402
from game import GOOD_WINDOW  # noqa: E402
from gestures import (CURLED_MIN_CURL, EXPRESSION_MODES, EXTENDED_MAX_CURL, FINGER_NAMES,  # noqa: E402
                      PUMP_REARM_SPEED, PUMP_SPEED, SIGN_SETS, TAP_DIP, TAP_RETURN, THUMB_IN_MAX,
                      THUMB_OUT_MIN, sign_names)
from looper import QUANTISE  # noqa: E402
from session import SESSIONS_DIR, list_sessions  # noqa: E402
from songmaker import CHARTS, DIFFICULTIES  # noqa: E402
from sound_engine import INSTRUMENT_NAMES  # noqa: E402
from synesthesia import key_colours  # noqa: E402

# ---------------------------------------------------------------- look
BG = (13, 16, 22)
PANEL = (22, 26, 35)
PANEL_HI = (31, 36, 48)
PANEL_HOVER = (40, 46, 61)
LINE = (47, 54, 69)
TEXT = (234, 237, 243)
MUTED = (140, 149, 166)
DIM = (92, 100, 117)
ACCENT = (96, 165, 250)
GOOD = (110, 231, 160)
WARN = (250, 190, 90)
BAD = (248, 113, 113)
HAND = {"L": (86, 180, 255), "R": (255, 150, 70)}
HAND_NAME = {"L": "Left hand", "R": "Right hand"}
SLOT = [(255, 99, 99), (255, 159, 67), (255, 214, 72), (130, 220, 90),
        (72, 210, 230), (99, 140, 255), (186, 104, 255), (255, 105, 180)]
FEEDBACK = {"perfect": GOOD, "good": (120, 210, 255), "miss": DIM, "wrong": BAD}
STAGE_COLORS = [("Slate", (30, 36, 48)), ("Studio green", (24, 86, 60)), ("Night blue", (20, 36, 70)),
                ("Charcoal", (24, 24, 27)), ("Warm paper", (234, 229, 218))]
STAGE_VIEWS = [("Front", 0), ("Three-quarter", 35), ("Side", 80)]
INSTRUMENT_NOTES = {
    "Piano": "struck strings that fade", "Electric piano": "soft bell-like keys", "Organ": "steady, never fades",
    "Strings": "slow swell with vibrato", "Pluck": "short guitar-like notes", "Bass": "an octave lower",
    "Synth lead": "bright and buzzy", "Bell": "long metallic ring", "Marimba": "wooden, quick decay",
    "Flute": "soft and breathy",
}
CHORD_TYPES = ["", "m", "7", "maj7", "m7", "6", "m6", "sus2", "sus4", "dim", "aug", "add9"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WHITE_PCS = [0, 2, 4, 5, 7, 9, 11]
KEY_HELP = [
    ("m / M", "next / previous mode"), ("x", "Basic / Extended signs"), ("g", "signs / pinch"),
    ("s", "scale"), ("[  ]", "octave down / up"), ("t / T", "right-hand instrument"),
    ("y / Y", "left-hand instrument"), ("e", "hand height: off / volume / bend"),
    ("i", "strike speed sets loudness"), ("space", "sustain (taps the beat while listening to a song)"),
    ("r", "record / overdub loop"), ("p / u / c", "loop play-stop / undo / clear"),
    ("z / w", "metronome / quantise"), ("-  =", "loop tempo down / up"),
    ("n / j", "next song / play-stop song"), ("a", "add a song from a music file"),
    (",  .", "game timing offset"), ("F2", "calibrate your hands"), ("F5", "record a hand session"),
    ("F6", "replay the last session / stop"), ("F7", "record a MIDI file"), ("F8", "export the loop as MIDI"),
    ("b", "backdrop: colour / blur / off"), ("k / o", "stage colour / stage view"), ("l", "skeleton on camera"),
    ("d", "debug view"), ("h", "swap hands"), ("v", "record a demo video"), ("Tab", "settings"),
    ("F11", "fullscreen"), ("Esc", "close panel"), ("q", "quit"),
]
TABS = ["Instruments", "Key mapping", "Looper & MIDI", "Sessions", "Songs", "Calibrate", "Display", "Keys"]
BONES = [(0, 1, "t"), (1, 2, "t"), (2, 3, "t"), (3, 4, "t"),
         (5, 6, 0), (6, 7, 0), (7, 8, 0), (9, 10, 1), (10, 11, 1), (11, 12, 1),
         (13, 14, 2), (14, 15, 2), (15, 16, 2), (17, 18, 3), (18, 19, 3), (19, 20, 3),
         (0, 5, "p"), (5, 9, "p"), (9, 13, "p"), (13, 17, "p"), (0, 17, "p")]
PALM = [0, 1, 5, 9, 13, 17]
TIPS = [4, 8, 12, 16, 20]
GAME_PPS = 240        # pixels per second the notes scroll
TRAIL_SECONDS = 0.6


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _system_scale():
    """Windows display scaling (1.0 = 100%). The process is made DPI-aware so text stays sharp."""
    if sys.platform != "win32":
        return 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96)
    except Exception:
        return 1.0


class Hit:
    """A clickable area from the last frame: down/up callbacks, and drag while held (sliders)."""
    __slots__ = ("rect", "down", "up", "drag")

    def __init__(self, rect, down=None, up=None, drag=None):
        self.rect, self.down, self.up, self.drag = pygame.Rect(rect), down, up, drag


class UI:
    def __init__(self, app, window=None):
        self.app = app
        self.core = sys.modules[type(app).__module__]  # mapping tables live in the App's module
        self.s = _system_scale()
        pygame.init()
        pygame.display.set_caption("Gesture Music")
        info = pygame.display.Info()
        if window:
            w, h = (int(v) for v in window.lower().split("x"))
        else:
            w = min(int(1600 * self.s), int(info.current_w * 0.94))
            h = min(int(920 * self.s), int(info.current_h * 0.88))
        self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.windowed_size, self.fullscreen = (w, h), False
        self.fonts, self.text_cache = {}, {}
        self.hits, self.pressed_hit = [], None
        self.settings_open, self.settings_tab = False, "Instruments"
        self.popup = None                     # instrument menu: {"hand": h, "anchor": rect}
        self.map_hand, self.map_slot, self.map_kind = "R", 0, "Note"
        self.map_octave, self.map_root, self.map_quality = 4, 0, ""
        self.trails = {"L": deque(maxlen=60), "R": deque(maxlen=60)}
        self.mouse = (0, 0)
        self.overlay = None
        self.text_input = None        # {"value", "label", "done"} while typing a name
        self.preset_sel = None        # selected key-mapping preset
        self.confirm_delete = None    # preset waiting for a second click to delete
        self.scroll, self.overflow, self.cache, self.drawer = {}, {}, {}, None

    # ---------------------------------------------------------------- basics

    def px(self, n):
        return int(round(n * self.s))

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            # Load Segoe UI regular/semibold by file: asking for "segoeui" by name picks the Light weight
            path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                                "seguisb.ttf" if bold else "segoeui.ttf")
            if os.path.exists(path):
                self.fonts[key] = pygame.font.Font(path, self.px(size))
            else:
                self.fonts[key] = pygame.font.SysFont("helveticaneue,arial,dejavusans", self.px(size), bold=bold)
        return self.fonts[key]

    def text(self, surf, s, pos, size=14, color=TEXT, bold=False, anchor="topleft", max_w=None):
        """Draw text (cached); shrinks to fit max_w, then adds an ellipsis if still too wide."""
        s = str(s)
        f = self.font(size, bold)
        if max_w and f.size(s)[0] > max_w:
            for smaller in (size - 1, size - 2, size - 3):
                if smaller >= 9 and self.font(smaller, bold).size(s)[0] <= max_w:
                    f, size = self.font(smaller, bold), smaller
                    break
            else:
                while s and f.size(s + "...")[0] > max_w:
                    s = s[:-1]
                s += "..."
        key = (s, size, bold, color)
        img = self.text_cache.get(key)
        if img is None:
            if len(self.text_cache) > 3000:
                self.text_cache.clear()
            img = self.text_cache[key] = f.render(s, True, color)
        r = img.get_rect(**{anchor: pos})
        surf.blit(img, r)
        return r

    def icon(self, kind, center, size, color):
        """Small vector icons. Drawn as shapes: Segoe UI lacks these symbols (they render as boxes)."""
        cx, cy = center
        s = size / 2
        if kind == "play":
            pygame.draw.polygon(self.screen, color, [(cx - s * 0.7, cy - s), (cx - s * 0.7, cy + s), (cx + s, cy)])
        elif kind == "stop":
            pygame.draw.rect(self.screen, color, (cx - s * 0.8, cy - s * 0.8, s * 1.6, s * 1.6), border_radius=2)
        elif kind == "next":
            pygame.draw.polygon(self.screen, color, [(cx - s, cy - s), (cx - s, cy + s), (cx + s * 0.5, cy)])
            pygame.draw.rect(self.screen, color, (cx + s * 0.55, cy - s, max(2, s * 0.35), s * 2))
        elif kind == "down":
            pygame.draw.polygon(self.screen, color, [(cx - s, cy - s * 0.5), (cx + s, cy - s * 0.5), (cx, cy + s * 0.6)])
        elif kind == "close":
            w = max(2, self.px(2))
            pygame.draw.line(self.screen, color, (cx - s, cy - s), (cx + s, cy + s), w)
            pygame.draw.line(self.screen, color, (cx - s, cy + s), (cx + s, cy - s), w)

    def button(self, rect, label, on_click, active=False, color=ACCENT, size=13, enabled=True, sub=None, icon=None):
        rect = pygame.Rect(rect)
        hover = enabled and rect.collidepoint(self.mouse)
        fill = mix(PANEL_HI, color, 0.85) if active else (PANEL_HOVER if hover else PANEL_HI)
        pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(7))
        if active:
            pygame.draw.rect(self.screen, color, rect, width=max(1, self.px(1)), border_radius=self.px(7))
        fg = BG if active else (TEXT if enabled else DIM)
        if icon:
            self.icon(icon, rect.center, self.px(12), fg)
        elif sub:
            self.text(self.screen, label, (rect.centerx, rect.centery - self.px(7)), size, fg, True, "center",
                      rect.w - self.px(10))
            self.text(self.screen, sub, (rect.centerx, rect.centery + self.px(9)), 10,
                      mix(fg, fill, 0.35), False, "center", rect.w - self.px(8))
        else:
            self.text(self.screen, label, rect.center, size, fg, active, "center", rect.w - self.px(10))
        if enabled and on_click:
            self.hits.append(Hit(rect, down=on_click))
        return rect

    def panel(self, rect, fill=PANEL, radius=10):
        pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(radius))

    def slot_color(self, hand, slot):
        return SLOT[slot] if self.app.nslots == 8 else SLOT[slot if hand == "R" else 4 + slot]

    def snapshot(self):
        """The current window as a BGR image, for demo captures."""
        rgb = pygame.surfarray.array3d(self.screen).transpose(1, 0, 2)
        return cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)

    def close(self):
        pygame.quit()

    # ---------------------------------------------------------------- input

    def handle_events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.screen = pygame.display.set_mode((max(e.w, 900), max(e.h, 600)), pygame.RESIZABLE)
            elif e.type == pygame.MOUSEMOTION:
                self.mouse = e.pos
                if self.pressed_hit and self.pressed_hit.drag and e.buttons[0]:
                    self.pressed_hit.drag()
            elif e.type == pygame.MOUSEWHEEL:
                if self.settings_open and self.drawer and self.drawer.collidepoint(self.mouse):
                    tab = self.settings_tab
                    self.scroll[tab] = max(0, self.scroll.get(tab, 0) - e.y * self.px(48))
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.mouse = e.pos
                self.on_click(e.pos)
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                if self.pressed_hit and self.pressed_hit.up:
                    self.pressed_hit.up()
                self.pressed_hit = None
            elif e.type == pygame.KEYDOWN:
                if not self.on_key(e):
                    return False
        return self.app.running

    def on_click(self, pos):
        for hit in reversed(self.hits):  # last drawn is on top
            if hit.rect.collidepoint(pos):
                self.pressed_hit = hit
                if hit.down:
                    hit.down()
                return
        self.popup = None  # clicked empty space: close the instrument menu

    def on_key(self, e):
        app = self.app
        if self.text_input:  # typing a name: keys go to the text box, not to shortcuts
            box = self.text_input
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.text_input = None
                if box["value"].strip():
                    box["done"](box["value"].strip())
            elif e.key == pygame.K_ESCAPE:
                self.text_input = None
            elif e.key == pygame.K_BACKSPACE:
                box["value"] = box["value"][:-1]
            elif e.unicode and e.unicode.isprintable() and len(box["value"]) < 40:
                box["value"] += e.unicode
            return True
        if e.key == pygame.K_ESCAPE:
            if app.calibrator:
                app.finish_calibration(save=False)
                return True
            if self.popup or self.settings_open:
                self.popup, self.settings_open = None, False
                return True
            return False
        if e.key == pygame.K_SPACE and app.importer.previewing:  # tap the beat while listening
            app.importer.tap(time.perf_counter())
            return True
        function_keys = {pygame.K_F2: lambda: app.start_calibration(), pygame.K_F5: app.toggle_session_recording,
                         pygame.K_F6: app.replay_latest, pygame.K_F7: app.toggle_midi_recording,
                         pygame.K_F8: app.export_loop}
        if e.key in function_keys:
            function_keys[e.key]()
            return True
        if e.key == pygame.K_TAB:
            self.settings_open = not self.settings_open
            return True
        if e.key == pygame.K_F11:
            self.toggle_fullscreen()
            return True
        if e.key == pygame.K_SPACE:
            app.toggle_sustain()
            return True
        actions = {
            "q": lambda: False, "m": lambda: app.cycle_mode(1), "M": lambda: app.cycle_mode(-1),
            "x": app.cycle_sign_set, "g": app.cycle_style, "s": app.cycle_scale,
            "[": lambda: app.octave(-1), "]": lambda: app.octave(1),
            "t": lambda: app.cycle_instrument("R", 1), "T": lambda: app.cycle_instrument("R", -1),
            "y": lambda: app.cycle_instrument("L", 1), "Y": lambda: app.cycle_instrument("L", -1),
            "e": app.cycle_expression, "r": lambda: app.loop_action("toggle_record"),
            "p": lambda: app.loop_action("toggle_play"), "u": lambda: app.loop_action("undo"),
            "c": lambda: app.loop_action("clear"), "n": app.next_song, "j": app.toggle_game,
            ",": lambda: app.adjust_offset(-10), ".": lambda: app.adjust_offset(10),
            "b": app.cycle_background, "k": lambda: app.cycle_stage_color(len(STAGE_COLORS)),
            "o": lambda: app.cycle_stage_view(len(STAGE_VIEWS)), "l": lambda: app.toggle("camera_skeleton"),
            "d": lambda: setattr(app, "show_debug", not app.show_debug), "h": app.toggle_swap,
            "v": lambda: setattr(app, "capture_toggle", True), "i": app.toggle_dynamics,
            "z": app.toggle_metronome, "w": app.cycle_quantise,
            "-": lambda: app.set_loop_bpm(app.looper.bpm - 1), "=": lambda: app.set_loop_bpm(app.looper.bpm + 1),
            "a": self.add_song,
        }
        action = actions.get(e.unicode)
        if action:
            return action() is not False
        return True

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        else:
            self.windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        self.fullscreen = not self.fullscreen

    # ---------------------------------------------------------------- frame

    def layout(self):
        W, H = self.screen.get_size()
        p = self.px(12)
        top = pygame.Rect(0, 0, W, self.px(58))
        footer = pygame.Rect(0, H - self.px(30), W, self.px(30))
        pads = pygame.Rect(p, footer.top - self.px(136), W - 2 * p, self.px(130))
        cal = self.app.calibrator
        wizard_on = cal is not None and not cal.done      # the wizard gets its own strip, hiding nothing
        game_on = self.app.game.state in ("playing", "results") and not wizard_on
        game_h = self.px(170) if game_on else self.px(176) if wizard_on else 0
        game = pygame.Rect(p, pads.top - game_h - self.px(8), W - 2 * p, game_h)
        bottom = (game.top if game_h else pads.top) - self.px(8)
        main = pygame.Rect(p, top.bottom + self.px(4), W - 2 * p, bottom - top.bottom - self.px(4))
        gap = self.px(10)
        cam = pygame.Rect(main.x, main.y, (main.w - gap) // 2, main.h)
        stage = pygame.Rect(cam.right + gap, main.y, main.w - cam.w - gap, main.h)
        return dict(W=W, H=H, top=top, footer=footer, pads=pads, game=game, game_on=game_on,
                    main=main, cam=cam, stage=stage)

    def draw(self):
        self.hits = []
        self.screen.fill(BG)
        L = self.layout()
        self.draw_top(L["top"])
        self.draw_camera(L["cam"])
        self.draw_stage(L["stage"])
        if L["game_on"]:
            self.draw_game(L["game"], L["main"])
        self.draw_pads(L["pads"])
        self.draw_footer(L["footer"])
        if self.app.calibrator:
            self.draw_calibration(L["game"], L["main"])
        if self.settings_open:
            self.draw_settings(L)
        if self.popup:
            self.draw_popup()
        pygame.display.flip()

    # ---------------------------------------------------------------- small widgets

    def open_tab(self, tab):
        self.settings_open, self.settings_tab = True, tab

    def add_song(self):
        """Pick a music/MIDI file, then show its analysis in Settings > Songs."""
        self.settings_open, self.settings_tab = True, "Songs"
        self.app.add_song()

    def slider(self, rect, value, on_change, color=ACCENT, label=None):
        """A horizontal 0..1 slider; drag to change, the setting is saved on release."""
        rect = pygame.Rect(rect)
        track = pygame.Rect(rect.x, rect.centery - self.px(3), rect.w, self.px(6))
        pygame.draw.rect(self.screen, LINE, track, border_radius=self.px(3))
        pygame.draw.rect(self.screen, color, (track.x, track.y, int(track.w * value), track.h), border_radius=self.px(3))
        pygame.draw.circle(self.screen, TEXT, (track.x + int(track.w * value), track.centery), self.px(8))
        if label:
            self.text(self.screen, label, (rect.right + self.px(10), rect.centery), 12, MUTED, False, "midleft")

        def set_from_mouse():
            on_change(max(0.0, min(1.0, (self.mouse[0] - track.x) / max(1, track.w))))
        self.hits.append(Hit(rect.inflate(0, self.px(10)), down=set_from_mouse, drag=set_from_mouse,
                             up=self.app.save))

    def ask_text(self, label, done, value="", owner=None):
        self.text_input = {"label": label, "value": value, "done": done, "owner": owner}

    def text_box(self, rect):
        """The active text input, drawn where the tab that asked for it wants it."""
        box = self.text_input
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.screen, (12, 14, 19), rect, border_radius=self.px(6))
        pygame.draw.rect(self.screen, ACCENT, rect, 1, border_radius=self.px(6))
        caret = "|" if int(time.time() * 2) % 2 else " "
        self.text(self.screen, box["value"] + caret, (rect.x + self.px(10), rect.centery), 13, TEXT, False, "midleft",
                  rect.w - self.px(20))
        self.text(self.screen, f"{box['label']}  (Enter to save, Esc to cancel)", (rect.x, rect.y - self.px(4)), 10,
                  MUTED, False, "bottomleft")
        self.hits.append(Hit(rect))

    # ---------------------------------------------------------------- top bar

    def draw_top(self, r):
        app = self.app
        pygame.draw.rect(self.screen, PANEL, r)
        pygame.draw.line(self.screen, LINE, r.bottomleft, r.bottomright)
        x = self.px(16)
        self.text(self.screen, "Gesture Music", (x, r.centery - self.px(9)), 18, TEXT, True, "midleft")
        self.text(self.screen, "hand-sign instrument", (x, r.centery + self.px(11)), 11, MUTED, False, "midleft")
        x += self.px(170)
        root_name = NOTE_NAMES[app.root % 12] + str(app.root // 12 - 1)
        chips = [
            ("Mode", app.mode, lambda: app.cycle_mode(1), None),
            ("Signs", app.effective_sign_set if app.style == "Signs" else "Pinch", app.cycle_sign_set, None),
            ("Key", f"{root_name} {app.scale}", app.cycle_scale, None),
            ("", "−", lambda: app.octave(-1), "small"),   # octave down / up, next to the key
            ("", "+", lambda: app.octave(1), "small"),
            ("Height", app.expression, app.cycle_expression, None),
            ("Sustain", "On" if app.sustain else "Off", app.toggle_sustain, "on" if app.sustain else None),
            ("Backdrop", app.background, app.cycle_background, "on" if app.background != "Off" else None),
        ]
        right_w = self.px(430)
        avail = r.w - x - right_w
        chip_w = max(self.px(78), min(self.px(124), (avail - self.px(8) * len(chips)) // max(1, len(chips) - 1)))
        for label, value, action, flag in chips:
            w = self.px(34) if flag == "small" else chip_w
            rect = pygame.Rect(x, r.y + self.px(9), w, r.h - self.px(18))
            hover = rect.collidepoint(self.mouse)
            fill = mix(PANEL_HI, GOOD, 0.25) if flag == "on" else (PANEL_HOVER if hover else PANEL_HI)
            pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(8))
            if flag == "small":
                self.text(self.screen, value, rect.center, 18, TEXT, True, "center")
                if label:
                    self.text(self.screen, label, (rect.x, r.y + self.px(1)), 9, MUTED)
            else:
                self.text(self.screen, label.upper(), (rect.x + self.px(10), rect.y + self.px(4)), 9, MUTED)
                self.text(self.screen, value, (rect.x + self.px(10), rect.bottom - self.px(4)), 14, TEXT, True,
                          "bottomleft", rect.w - self.px(16))
            self.hits.append(Hit(rect, down=action))
            x = rect.right + self.px(8)

        # right side: song and settings
        game = app.game
        x = r.right - right_w + self.px(8)
        song_rect = pygame.Rect(x, r.y + self.px(9), self.px(250), r.h - self.px(18))
        pygame.draw.rect(self.screen, PANEL_HI, song_rect, border_radius=self.px(8))
        self.text(self.screen, "RHYTHM GAME", (song_rect.x + self.px(10), song_rect.y + self.px(4)), 9, MUTED)
        self.text(self.screen, game.selected_title, (song_rect.x + self.px(10), song_rect.bottom - self.px(4)),
                  13, TEXT, True, "bottomleft", song_rect.w - self.px(90))
        playing = game.state == "playing"
        if not game.paths:  # no songs yet: the button adds one
            self.button((song_rect.right - self.px(80), song_rect.y + self.px(5), self.px(74), song_rect.h - self.px(10)),
                        "Add...", self.add_song, color=GOOD, size=12)
        else:
            self.button((song_rect.right - self.px(76), song_rect.y + self.px(5), self.px(34), song_rect.h - self.px(10)),
                        "", app.toggle_game, active=playing, color=GOOD, icon="stop" if playing else "play")
        if game.paths:
            self.button((song_rect.right - self.px(38), song_rect.y + self.px(5), self.px(32), song_rect.h - self.px(10)),
                        "", app.next_song, enabled=not playing, icon="next")
        self.button((r.right - self.px(160), r.y + self.px(10), self.px(146), r.h - self.px(20)),
                    "Settings  (Tab)", lambda: setattr(self, "settings_open", not self.settings_open),
                    active=self.settings_open, size=13)

    # ---------------------------------------------------------------- camera panel

    def draw_camera(self, r):
        app = self.app
        self.panel(r)
        self.text(self.screen, "CAMERA", (r.x + self.px(12), r.y + self.px(8)), 10, MUTED, True)
        inner = r.inflate(-self.px(16), -self.px(40)).move(0, self.px(12))
        fw, fh = app.frame_size
        scale = min(inner.w / fw, inner.h / fh)
        w, h = int(fw * scale), int(fh * scale)
        img = pygame.Rect(0, 0, w, h)
        kb = None
        if inner.h - h >= self.px(96):  # room below the picture: show the notes being played
            img.midtop = (inner.centerx, inner.y)
            kb = pygame.Rect(inner.x, img.bottom + self.px(10), inner.w,
                             min(self.px(150), inner.bottom - img.bottom - self.px(10)))
            self.now_playing(kb)
        else:
            img.center = inner.center
        if app.frame is None:  # replaying a session (landmarks only) or waiting for the camera
            pygame.draw.rect(self.screen, (17, 20, 27), img, border_radius=self.px(8))
            if not app.view_hands and not app.player:
                self.text(self.screen, "Waiting for the camera...", img.center, 16, MUTED, False, "center")
        else:
            small = cv2.resize(app.frame, (w, h), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self.screen.blit(pygame.image.frombuffer(rgb.tobytes(), (w, h), "RGB"), img)
        if app.player:  # a replay: landmarks only, shown over the colour field (or a plain panel)
            p = app.player
            label = pygame.Rect(img.x + self.px(8), img.y + self.px(8), self.px(330), self.px(44))
            pygame.draw.rect(self.screen, (0, 0, 0), label, border_radius=self.px(6))
            self.text(self.screen, f"Replaying {p.path.name}   {p.position:.1f} / {p.length:.1f} s",
                      (label.x + self.px(10), label.y + self.px(5)), 12, WARN, True, max_w=label.w - self.px(16))
            self.text(self.screen, "Press F6 to stop", (label.x + self.px(10), label.y + self.px(25)), 11, MUTED)

        # centre line: your left hand plays on the left half
        for y in range(img.y + self.px(6), img.bottom - self.px(6), self.px(14)):
            pygame.draw.line(self.screen, (200, 200, 200), (img.centerx, y), (img.centerx, y + self.px(6)), 1)
        self.text(self.screen, "LEFT", (img.centerx - self.px(8), img.bottom - self.px(6)), 10, HAND["L"], True,
                  "bottomright")
        self.text(self.screen, "RIGHT", (img.centerx + self.px(8), img.bottom - self.px(6)), 10, HAND["R"], True,
                  "bottomleft")

        def to_img(lm):
            return int(img.x + lm.x * w), int(img.y + lm.y * h)

        for v in app.view_hands:
            hand, lms, state = v["hand"], v["landmarks"], v["state"]
            pts = [to_img(lm) for lm in lms]
            if app.camera_skeleton:
                for a, b, _ in BONES:
                    pygame.draw.line(self.screen, HAND[hand], pts[a], pts[b], max(2, self.px(3)))
                for p in pts:
                    pygame.draw.circle(self.screen, (255, 255, 255), p, max(2, self.px(3)))
            wx, wy = pts[0]
            pygame.draw.circle(self.screen, HAND[hand], (wx, wy + self.px(20)), self.px(13))
            self.text(self.screen, hand, (wx, wy + self.px(20)), 14, BG, True, "center")
            for slot, (nx, ny) in v["points"].items():
                c = (int(img.x + nx * w), int(img.y + ny * h))
                color = self.slot_color(hand, slot)
                pygame.draw.circle(self.screen, color, c, self.px(16))
                self.text(self.screen, app.slot(hand, slot)[2], (c[0], c[1] - self.px(20)), 16, color, True,
                          "midbottom")
            kind, when = state.repeat_flash
            if kind and time.perf_counter() - when < 0.35:
                self.text(self.screen, kind, (wx + self.px(22), wy + self.px(20)), 16, GOOD, True, "midleft")
        if app.capture.active:
            pygame.draw.circle(self.screen, BAD, (r.right - self.px(18), r.y + self.px(14)), self.px(6))
            self.text(self.screen, "REC", (r.right - self.px(30), r.y + self.px(14)), 11, BAD, True, "midright")

    def now_playing(self, r):
        """A five-octave keyboard (C2-C7) lighting up every note sounding now, in the hand's colour."""
        app = self.app
        # summary line: what each hand plays, on which instrument
        x = r.x
        self.text(self.screen, "NOW PLAYING", (x, r.y), 10, MUTED, True)
        x += self.px(96)
        for hand in ("L", "R"):
            sounds = [app.slot(hand, s)[2] for (h, s) in sorted(app.active_pads()) if h == hand]
            inst = "drums" if app.hand_plays_drums(hand) else app.instruments[hand]
            label = f"{hand}  {' + '.join(sounds) if sounds else '-'}  ·  {inst}"
            rr = self.text(self.screen, label, (x, r.y - self.px(1)), 12, HAND[hand] if sounds else DIM, bool(sounds))
            x = rr.right + self.px(28)

        keys = pygame.Rect(r.x, r.y + self.px(22), r.w, r.h - self.px(22))
        low, high = 36, 96
        lit = {}
        for (hand, _), notes in list(app.notes_on.items()):
            for n in notes:
                lit[n] = hand
        whites = [m for m in range(low, high + 1) if m % 12 in WHITE_PCS]
        kw = keys.w / len(whites)
        pos = {}
        for i, m in enumerate(whites):
            rect = pygame.Rect(int(keys.x + i * kw), keys.y, max(1, int(kw) - 1), keys.h)
            pos[m] = rect
            fill = HAND[lit[m]] if m in lit else (232, 234, 238)
            pygame.draw.rect(self.screen, fill, rect, border_bottom_left_radius=self.px(4),
                             border_bottom_right_radius=self.px(4))
            if m % 12 == 0:
                self.text(self.screen, f"C{m // 12 - 1}", (rect.centerx, rect.bottom - self.px(3)), 10,
                          (70, 74, 84), m == 60, "midbottom")
        for m in range(low, high):
            if m % 12 in WHITE_PCS:
                continue
            left = pos[m - 1]
            rect = pygame.Rect(int(left.right - kw * 0.3), keys.y, int(kw * 0.6), int(keys.h * 0.6))
            pygame.draw.rect(self.screen, HAND[lit[m]] if m in lit else (28, 30, 36), rect,
                             border_bottom_left_radius=self.px(3), border_bottom_right_radius=self.px(3))

    # ---------------------------------------------------------------- hand stage

    def project(self, v, r, yaw):
        """Hand model on the stage: 3D world landmarks, turned by yaw, placed where the hand is."""
        lms, world = v["landmarks"], v["world"]
        margin = 0.09
        cx = r.x + (margin + lms[9].x * (1 - 2 * margin)) * r.w
        cy = r.y + (margin + lms[9].y * (1 - 2 * margin)) * r.h
        scale = r.h * 2.1  # pixels per metre: the hand is about 40% of the stage height
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        o = world[9]
        pts, depth = [], []
        for p in world:
            dx, dy, dz = p.x - o.x, p.y - o.y, p.z - o.z
            x = dx * c + dz * s
            z = -dx * s + dz * c
            pts.append((cx + x * scale, cy + dy * scale))
            depth.append(z)
        return pts, depth

    def finger_color(self, v, finger, base, bg):
        """Bright = up, dim = down, amber = half-bent (keeps its last state)."""
        state = self.app.hands[v["hand"]]
        if self.app.style == "Pinch":
            if finger != "t" and finger in state.active:
                return self.slot_color(v["hand"], finger)
            return base
        if finger == "t":
            up = state.thumb_out
        else:
            curl = state.curls[finger]
            if EXTENDED_MAX_CURL <= curl <= CURLED_MIN_CURL:
                return WARN
            up = state.extended[finger]
        return base if up else mix(base, bg, 0.6)

    def draw_stage(self, r):
        app = self.app
        name, bg = STAGE_COLORS[app.stage_color % len(STAGE_COLORS)]
        view_name, yaw = STAGE_VIEWS[app.stage_view % len(STAGE_VIEWS)]
        light = sum(bg) > 450
        ink = (40, 44, 52) if light else TEXT
        soft = mix(bg, ink, 0.45)
        pygame.draw.rect(self.screen, bg, r, border_radius=self.px(10))
        grid = mix(bg, ink, 0.06)
        step = self.px(48)
        for gx in range(r.x + step, r.right, step):
            pygame.draw.line(self.screen, grid, (gx, r.y + self.px(36)), (gx, r.bottom - self.px(6)))
        for gy in range(r.y + self.px(36), r.bottom, step):
            pygame.draw.line(self.screen, grid, (r.x + self.px(6), gy), (r.right - self.px(6), gy))
        pygame.draw.line(self.screen, mix(bg, ink, 0.18), (r.centerx, r.y + self.px(40)),
                         (r.centerx, r.bottom - self.px(10)), 1)

        # header controls
        self.text(self.screen, "HAND STAGE", (r.x + self.px(12), r.y + self.px(8)), 10, soft, True)
        bx = r.right - self.px(8)
        for label, action in [(f"Trails: {'on' if app.trails else 'off'}", lambda: app.toggle("trails")),
                              (f"Colour: {name}", lambda: app.cycle_stage_color(len(STAGE_COLORS))),
                              (f"View: {view_name}", lambda: app.cycle_stage_view(len(STAGE_VIEWS)))]:
            w = self.font(11).size(label)[0] + self.px(18)
            rect = pygame.Rect(bx - w, r.y + self.px(6), w, self.px(22))
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, mix(bg, ink, 0.2 if hover else 0.1), rect, border_radius=self.px(6))
            self.text(self.screen, label, rect.center, 11, ink, False, "center")
            self.hits.append(Hit(rect, down=action))
            bx = rect.x - self.px(6)

        if self.overlay is None or self.overlay.get_size() != r.size:
            self.overlay = pygame.Surface(r.size, pygame.SRCALPHA)
        self.overlay.fill((0, 0, 0, 0))
        area = r.inflate(-self.px(8), -self.px(44)).move(0, self.px(18))
        if app.show_debug:  # keep the hands above the measurement panel
            area.h -= self.debug_height() + self.px(8)
        if getattr(self, "stage_area", None) != area.size:  # resized: old trail points no longer line up
            self.stage_area = area.size
            for t in self.trails.values():
                t.clear()
        max_jump = area.w * 0.15  # longer than this between frames is a tracking jump, not motion
        now = time.perf_counter()
        seen, real = set(), {}
        for v in app.view_hands:
            hand, state = v["hand"], v["state"]
            seen.add(hand)
            pts, depth = self.project(v, area, yaw)
            real[hand] = pts
            color = HAND[hand]

            if app.trails:  # recent motion of the palm and fingertips
                self.trails[hand].append((now, [pts[i] for i in [9] + TIPS]))
                hist = [t for t in self.trails[hand] if now - t[0] < TRAIL_SECONDS]
                for k in range(6):
                    for (t0, a), (_, b) in zip(hist, hist[1:]):
                        alpha = int(150 * (1 - (now - t0) / TRAIL_SECONDS)) if k == 0 else \
                            int(70 * (1 - (now - t0) / TRAIL_SECONDS))
                        pa = (a[k][0] - r.x, a[k][1] - r.y)
                        pb = (b[k][0] - r.x, b[k][1] - r.y)
                        if math.dist(pa, pb) > max_jump:
                            continue
                        pygame.draw.line(self.overlay, (*color, max(alpha, 0)), pa, pb,
                                         self.px(4) if k == 0 else self.px(2))

            palm = [(pts[i][0] - r.x, pts[i][1] - r.y) for i in PALM]
            pygame.draw.polygon(self.overlay, (*color, 60), palm)
            pygame.draw.polygon(self.overlay, (*color, 140), palm, max(1, self.px(2)))

            # bones, far ones first; nearer ones are thicker
            width = max(self.px(5), int(area.h * 0.024))
            for a, b, finger in sorted(BONES, key=lambda bn: -(depth[bn[0]] + depth[bn[1]])):
                z = (depth[a] + depth[b]) / 2
                k = max(0.75, min(1.35, 1 - z * 7))
                base = mix(color, (255, 255, 255), 0.15)
                col = mix(color, bg, 0.35) if finger == "p" else self.finger_color(v, finger, base, bg)
                wdt = int(width * k * (0.7 if finger == "p" else 1))
                pygame.draw.line(self.screen, col, pts[a], pts[b], wdt)
                for idx in (a, b):
                    pygame.draw.circle(self.screen, col, pts[idx], wdt // 2)
            for i in TIPS:
                k = max(0.75, min(1.35, 1 - depth[i] * 7))
                pygame.draw.circle(self.screen, (255, 255, 255), pts[i], int(width * 0.45 * k))

            # active sign: glow on the raised fingertips, in the pad's colour
            for slot in state.active:
                glow = self.slot_color(hand, slot)
                tips = TIPS[1:]
                if app.style == "Signs":
                    _, pattern, thumb = SIGN_SETS[app.effective_sign_set][slot]
                    tips = [TIPS[f + 1] for f in range(4) if pattern[f]] + ([4] if thumb else [])
                else:
                    tips = [4, TIPS[slot + 1]]
                for i in tips:
                    pygame.draw.circle(self.overlay, (*glow, 90), (pts[i][0] - r.x, pts[i][1] - r.y),
                                       int(width * 1.3))

            kind, when = state.repeat_flash
            if kind and now - when < 0.35:  # TAP / PUMP: a ring around the palm
                grow = (now - when) / 0.35
                pygame.draw.circle(self.overlay, (*GOOD, int(200 * (1 - grow))),
                                   (pts[9][0] - r.x, pts[9][1] - r.y), int(width * (3 + 3 * grow)), self.px(3))

            # label card under the wrist
            sound = ""
            if state.active:
                slot = sorted(state.active)[0]
                sound = app.slot(hand, slot)[2]
            label = state.label or ("pinch" if app.style == "Pinch" else "")
            extra = ""
            if app.expression == "Bend":
                extra = f"bend {v['bend']:+.1f}"
            elif app.expression == "Volume":
                extra = f"vol {int(v['volume'] * 100)}%"
            card_text = "  →  ".join(t for t in (label, sound) if t) + (f"   {extra}" if extra else "")
            wx, wy = pts[0]
            cw = self.font(14, True).size(card_text)[0] + self.px(44)
            card = pygame.Rect(0, 0, cw, self.px(30))
            card.midtop = (int(wx), int(max(wy, pts[17][1], pts[1][1]) + self.px(22)))
            card.clamp_ip(area)
            pygame.draw.rect(self.screen, mix(bg, ink, 0.12), card, border_radius=self.px(15))
            pygame.draw.circle(self.screen, color, (card.x + self.px(15), card.centery), self.px(10))
            self.text(self.screen, hand, (card.x + self.px(15), card.centery), 12, BG, True, "center")
            accent = self.slot_color(hand, sorted(state.active)[0]) if state.active else ink
            self.text(self.screen, card_text, (card.x + self.px(32), card.centery), 14, accent, True, "midleft")

        ghost_labels = self.draw_ghosts(r, area, yaw, real) if app.game.state == "playing" else []
        self.screen.blit(self.overlay, r.topleft)
        for text, pos, color in ghost_labels:
            self.text(self.screen, text, pos, 14, color, True, "midtop")
        for hand in ("L", "R"):
            if hand not in seen:
                self.trails[hand].clear()
                half = pygame.Rect(r.x, r.y, r.w // 2, r.h) if hand == "L" else \
                    pygame.Rect(r.centerx, r.y, r.w - r.w // 2, r.h)
                self.text(self.screen, f"{HAND_NAME[hand]} not in view", half.center, 14, soft, False, "center")
        if app.show_debug:
            self.draw_debug(r, bg, ink)

    def pose_points(self, pose, center, scale, yaw):
        """Project a synthetic hand pose (hand-length units, from handmodel) around a centre point."""
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        o = pose[9]
        pts = []
        for x, y, z in pose:
            dx, dy, dz = x - o[0], y - o[1], z - o[2]
            pts.append((center[0] + (dx * c + dz * s) * scale, center[1] + dy * scale))
        return pts

    def draw_ghosts(self, r, area, yaw, real, lead=3.0):
        """In-game sign hints: a see-through hand showing each hand's next sign, over your own hand.

        A ring fills up as the note gets closer; the ghost turns green once you're making that sign.
        Returns labels to draw on top after the overlay is blitted.
        """
        app, game = self.app, self.app.game
        t = time.perf_counter() - game.start_time
        labels = []
        scale = area.h * 2.1 * 0.09   # hand lengths -> pixels, same size as the real hands
        for hand in ("L", "R"):
            upcoming = [n for n in game.notes if n.hand == hand and not n.result and n.time > t - GOOD_WINDOW]
            if not upcoming:
                continue
            note = min(upcoming, key=lambda n: n.time)
            due = note.time - t
            if due > lead:
                continue
            _, pattern, thumb = SIGN_SETS[app.effective_sign_set][note.slot]
            pose = handmodel.pose(pattern, thumb)
            if hand == "L":
                pose[:, 0] *= -1
            if hand in real:
                center = real[hand][9]
            else:
                half = area.x + area.w * (0.27 if hand == "L" else 0.73)
                center = (half, area.y + area.h * 0.55)
            pts = self.pose_points(pose, center, scale, yaw)
            ready = app.hands[hand].sign == note.slot and app.hands[hand].wrist is not None
            color = GOOD if ready else self.slot_color(hand, note.slot)
            width = max(self.px(5), int(area.h * 0.022))
            local = [(x - r.x, y - r.y) for x, y in pts]
            pygame.draw.polygon(self.overlay, (*color, 40), [local[i] for i in PALM])
            for a, b, _ in BONES:
                pygame.draw.line(self.overlay, (*color, 120), local[a], local[b], width)
            for i in TIPS:
                pygame.draw.circle(self.overlay, (*color, 160), local[i], int(width * 0.7))
            # countdown ring around the palm: full when the note is due
            radius = int(width * 6)
            ring = pygame.Rect(0, 0, 2 * radius, 2 * radius)
            ring.center = local[9]
            fraction = max(0.0, min(1.0, 1 - due / lead))
            pygame.draw.circle(self.overlay, (*color, 50), ring.center, radius, self.px(3))
            if fraction > 0:
                pygame.draw.arc(self.overlay, (*color, 220), ring, math.pi / 2 - 2 * math.pi * fraction, math.pi / 2,
                                self.px(4))
            when = "now" if abs(due) < 0.12 else f"in {due:.1f} s"
            labels.append((f"Next: {note.sign} → {note.label}  ({when})",
                           (int(center[0]), int(min(pts[t_][1] for t_ in TIPS) - radius * 0.2 - self.px(28))), color))
        return labels

    def debug_height(self):
        rows = 7 if self.app.style == "Signs" else 4
        return self.px(34) + rows * self.px(24)

    def draw_debug(self, r, bg, ink):
        app = self.app
        h = self.debug_height()
        box = pygame.Rect(r.x + self.px(10), r.bottom - h - self.px(8), r.w - self.px(20), h)
        pygame.draw.rect(self.screen, mix(bg, (0, 0, 0), 0.45), box, border_radius=self.px(8))
        col_w = box.w // 2
        for c, hand in enumerate(("L", "R")):
            state = app.hands[hand]
            x0, y0 = box.x + c * col_w + self.px(10), box.y + self.px(8)
            self.text(self.screen, f"{HAND_NAME[hand]}: " + ((state.label or "seen") if state.wrist else "not seen"),
                      (x0, y0), 11, HAND[hand], True)
            rows = []
            if app.style == "Signs":
                for f in range(4):
                    v = state.curls[f]
                    fill = WARN if EXTENDED_MAX_CURL <= v <= CURLED_MIN_CURL else (GOOD if state.extended[f] else MUTED)
                    rows.append((FINGER_NAMES[f], v, 200, f"{v:.0f}°", fill, (EXTENDED_MAX_CURL, CURLED_MIN_CURL)))
                rows.append(("thumb", state.thumb_ratio, 1.6, f"{state.thumb_ratio:.2f}",
                             GOOD if state.thumb_out else MUTED, (THUMB_IN_MAX, THUMB_OUT_MIN)))
                rows.append(("tap", state.tap_dip, 90, f"{state.tap_dip:.0f}°", WARN if state.tap_armed else MUTED,
                             (TAP_RETURN, TAP_DIP)))
                rows.append(("pump", max(state.pump_speed, 0), 6, f"{state.pump_speed:+.1f}/s", MUTED,
                             (PUMP_REARM_SPEED, PUMP_SPEED)))
            else:
                from gestures import PRESS_RATIO, RELEASE_RATIO
                for f in range(4):
                    v = state.ratios[f]
                    rows.append((FINGER_NAMES[f], v, 1.2, f"{v:.2f}", GOOD if f in state.active else MUTED,
                                 (PRESS_RATIO, RELEASE_RATIO)))
            bar_w = col_w - self.px(150)
            for i, (name, value, top, label, fill, marks) in enumerate(rows):
                y = y0 + self.px(22) + i * self.px(24)
                self.text(self.screen, name, (x0, y), 11, TEXT)
                bar = pygame.Rect(x0 + self.px(52), y + self.px(3), bar_w, self.px(12))
                pygame.draw.rect(self.screen, (50, 55, 66), bar, border_radius=self.px(3))
                filled = bar.copy()
                filled.w = int(bar.w * min(value, top) / top)
                pygame.draw.rect(self.screen, fill, filled, border_radius=self.px(3))
                for m in marks:
                    mx = bar.x + int(bar.w * m / top)
                    pygame.draw.line(self.screen, TEXT, (mx, bar.y - self.px(3)), (mx, bar.bottom + self.px(3)), 2)
                self.text(self.screen, label, (bar.right + self.px(8), y), 11, TEXT)

    # ---------------------------------------------------------------- pads

    def draw_pads(self, r):
        app = self.app
        n = app.nslots
        names = sign_names(app.effective_sign_set) if app.style == "Signs" else [f"pinch {f}" for f in FINGER_NAMES]
        active = app.active_pads()
        gap = self.px(10)
        for side, hand in enumerate(("L", "R")):
            strip = pygame.Rect(r.x + side * (r.w + gap) // 2, r.y, (r.w - gap) // 2, r.h)
            self.panel(strip)
            # header: hand badge + instrument
            pygame.draw.circle(self.screen, HAND[hand], (strip.x + self.px(20), strip.y + self.px(19)), self.px(10))
            self.text(self.screen, hand, (strip.x + self.px(20), strip.y + self.px(19)), 12, BG, True, "center")
            self.text(self.screen, HAND_NAME[hand].upper(), (strip.x + self.px(36), strip.y + self.px(19)), 11,
                      HAND[hand], True, "midleft")
            inst_rect = pygame.Rect(strip.right - self.px(214), strip.y + self.px(7), self.px(204), self.px(26))
            if app.hand_plays_drums(hand):
                pygame.draw.rect(self.screen, PANEL_HI, inst_rect, border_radius=self.px(6))
                self.text(self.screen, "Drum kit (this mode)", inst_rect.center, 12, MUTED, False, "center")
            else:
                hover = inst_rect.collidepoint(self.mouse) or (self.popup and self.popup["hand"] == hand)
                pygame.draw.rect(self.screen, PANEL_HOVER if hover else PANEL_HI, inst_rect, border_radius=self.px(6))
                self.text(self.screen, "Instrument", (inst_rect.x + self.px(10), inst_rect.centery), 10, MUTED,
                          False, "midleft")
                self.text(self.screen, app.instruments[hand], (inst_rect.right - self.px(26), inst_rect.centery),
                          13, TEXT, True, "midright")
                self.icon("down", (inst_rect.right - self.px(14), inst_rect.centery), self.px(9), MUTED)
                self.hits.append(Hit(inst_rect, down=lambda h=hand, rc=inst_rect: self.open_popup(h, rc)))

            pad_area = pygame.Rect(strip.x + self.px(8), strip.y + self.px(40), strip.w - self.px(16),
                                   strip.h - self.px(48))
            pw = (pad_area.w - self.px(6) * (n - 1)) / n
            for slot in range(n):
                rect = pygame.Rect(int(pad_area.x + slot * (pw + self.px(6))), pad_area.y, int(pw), pad_area.h)
                color = self.slot_color(hand, slot)
                on = (hand, slot) in active
                hover = rect.collidepoint(self.mouse)
                kind, _, label = app.slot(hand, slot)
                fill = color if on else (PANEL_HOVER if hover else PANEL_HI)
                pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(8))
                if not on:
                    pygame.draw.rect(self.screen, color, (rect.x, rect.y, rect.w, self.px(4)),
                                     border_top_left_radius=self.px(8), border_top_right_radius=self.px(8))
                fg = BG if on else (TEXT if kind != "none" else DIM)
                self.text(self.screen, label, (rect.x + self.px(8), rect.y + self.px(10)), 17 if n == 4 else 14,
                          fg, True, max_w=rect.w - self.px(12))
                self.text(self.screen, names[slot], (rect.x + self.px(8), rect.bottom - self.px(6)), 10,
                          mix(fg, fill, 0.3), False, "bottomleft", rect.w - self.px(40) if app.style == "Signs" else
                          rect.w - self.px(10))
                if app.style == "Signs":
                    icon = pygame.Rect(rect.right - self.px(30), rect.bottom - self.px(30), self.px(24), self.px(24))
                    _, pattern, thumb = SIGN_SETS[app.effective_sign_set][slot]
                    self.sign_icon(icon, pattern, thumb, mix(fg, fill, 0.15), mix(fg, fill, 0.6))
                if on and (hand, slot) in app.velocity_on:  # how hard it was struck
                    vel = app.velocity_on[(hand, slot)]
                    bar = pygame.Rect(rect.x + self.px(8), rect.bottom - self.px(26), int((rect.w - self.px(46)) * vel),
                                      self.px(4))
                    pygame.draw.rect(self.screen, mix(BG, color, 0.3), bar, border_radius=self.px(2))
                self.hits.append(Hit(rect, down=lambda h=hand, s=slot: app.pad_down(h, s),
                                     up=lambda h=hand, s=slot: app.pad_up(h, s)))

    def sign_icon(self, r, pattern, thumb, on, off):
        """Tiny picture of a sign: four finger bars (tall = up) and the thumb."""
        bw = max(2, r.w // 7)
        base = r.bottom - self.px(2)
        for f in range(4):
            x = r.x + self.px(7) + f * (bw + self.px(2))
            h = r.h - self.px(4) - abs(f - 1.5) * self.px(2) if pattern[f] else r.h * 0.3
            pygame.draw.rect(self.screen, on if pattern[f] else off, (x, base - h, bw, h), border_radius=bw // 2)
        tx = r.x + self.px(3)
        if thumb:
            pygame.draw.line(self.screen, on, (tx + self.px(3), base - self.px(3)), (r.x, base - r.h * 0.6), bw)
        elif thumb is False:
            pygame.draw.line(self.screen, off, (tx + self.px(3), base - self.px(3)), (tx + self.px(6), base - r.h * 0.35), bw)

    def open_popup(self, hand, rect):
        self.popup = None if (self.popup and self.popup["hand"] == hand) else {"hand": hand, "anchor": pygame.Rect(rect)}

    def draw_popup(self):
        hand, anchor = self.popup["hand"], self.popup["anchor"]
        row = self.px(30)
        menu = pygame.Rect(0, 0, self.px(260), row * len(INSTRUMENT_NAMES) + self.px(12))
        menu.bottomright = (anchor.right, anchor.y - self.px(4))
        menu.clamp_ip(self.screen.get_rect())
        pygame.draw.rect(self.screen, (0, 0, 0), menu.move(self.px(3), self.px(4)), border_radius=self.px(10))
        pygame.draw.rect(self.screen, PANEL_HI, menu, border_radius=self.px(10))
        pygame.draw.rect(self.screen, LINE, menu, 1, border_radius=self.px(10))
        self.hits.append(Hit(menu))  # swallow clicks between rows
        for i, name in enumerate(INSTRUMENT_NAMES):
            rect = pygame.Rect(menu.x + self.px(6), menu.y + self.px(6) + i * row, menu.w - self.px(12), row)
            chosen = self.app.instruments[hand] == name
            if chosen or rect.collidepoint(self.mouse):
                pygame.draw.rect(self.screen, mix(PANEL_HI, HAND[hand], 0.35 if chosen else 0.15), rect,
                                 border_radius=self.px(6))
            self.text(self.screen, name, (rect.x + self.px(10), rect.centery), 13, TEXT, chosen, "midleft")
            self.text(self.screen, INSTRUMENT_NOTES[name], (rect.right - self.px(8), rect.centery), 10, MUTED,
                      False, "midright")

            def choose(n=name):
                self.app.set_instrument(hand, n)
                self.popup = None
            self.hits.append(Hit(rect, down=choose))

    # ---------------------------------------------------------------- footer

    def draw_footer(self, r):
        app = self.app
        pygame.draw.rect(self.screen, PANEL, r)
        looper = app.looper
        state = {"empty": "Loop: press r to record", "countin": "Count-in...", "recording": "Recording loop",
                 "playing": "Loop playing", "overdub": "Overdubbing", "stopped": "Loop stopped"}[looper.state]
        if looper.layers:
            state += f" · {len(looper.layers)} layer{'s' if len(looper.layers) > 1 else ''}"
        x = self.px(14)
        if looper.recording or looper.state == "countin":
            pygame.draw.circle(self.screen, BAD, (x + self.px(5), r.centery), self.px(5))
            x += self.px(16)
        lr = self.text(self.screen, state, (x, r.centery), 12, BAD if looper.recording else MUTED, False, "midleft")
        x = lr.right + self.px(10)
        pos = looper.position()
        if pos is not None:
            bar = pygame.Rect(x, r.centery - self.px(3), self.px(110), self.px(6))
            pygame.draw.rect(self.screen, LINE, bar, border_radius=self.px(3))
            pygame.draw.rect(self.screen, GOOD, (bar.x, bar.y, int(bar.w * pos), bar.h), border_radius=self.px(3))
            x = bar.right + self.px(10)
        # quick looper controls: tempo, metronome, quantise (click to change)
        for label, action, on in [(f"{looper.bpm:g} BPM", lambda: self.open_tab("Looper & MIDI"), False),
                                  ("Click", app.toggle_metronome, looper.metronome),
                                  (f"Quantise {looper.quantise}", app.cycle_quantise, looper.quantise != "Off")]:
            w = self.font(11).size(label)[0] + self.px(16)
            rect = pygame.Rect(x, r.y + self.px(4), w, r.h - self.px(8))
            pygame.draw.rect(self.screen, mix(PANEL_HI, GOOD, 0.3) if on else (PANEL_HOVER if rect.collidepoint(self.mouse)
                                                                              else PANEL_HI), rect, border_radius=self.px(5))
            self.text(self.screen, label, rect.center, 11, TEXT, False, "center")
            self.hits.append(Hit(rect, down=action))
            x = rect.right + self.px(6)
        # recording indicators
        for active, label in [(app.session_recorder.active, "REC hands"), (app.router.performance is not None, "REC MIDI")]:
            if active:
                pygame.draw.circle(self.screen, BAD, (x + self.px(10), r.centery), self.px(5))
                x = self.text(self.screen, label, (x + self.px(20), r.centery), 11, BAD, True, "midleft").right + self.px(8)
        if time.time() < app.message_until:
            self.text(self.screen, app.message, (r.centerx, r.centery), 13, TEXT, True, "center", r.w // 2)
        fps = app.camera.fps if app.camera else 0
        perf = f"camera {fps:.0f} fps · tracking {app.track_ms:.0f} ms · frame→sound {max(0, app.latency_ms):.0f} ms"
        if app.midi:
            perf = f"MIDI: {app.midi.name} · " + perf
        low = 0 < fps < 24
        if low:
            perf = "Low light is slowing the camera · " + perf
        self.text(self.screen, perf, (r.right - self.px(14), r.centery), 11, WARN if low else DIM, False, "midright")

    # ---------------------------------------------------------------- rhythm game

    def draw_game(self, r, main):
        game, app = self.app.game, self.app
        self.panel(r)
        if game.state == "results":
            self.draw_results(r, main)
            return
        song, now = game.song, time.perf_counter()
        t = now - game.start_time
        lanes = [hd for hd in ("R", "L") if any(n.hand == hd for n in game.notes)]
        head = self.px(26)
        sheet_h = self.px(26)
        lane_h = min(self.px(56), (r.h - head - sheet_h - self.px(8)) // max(1, len(lanes)))
        hit_x = r.x + self.px(170)
        pps = self.px(GAME_PPS)
        top = r.y + head

        self.text(self.screen, song.title, (r.x + self.px(12), r.y + self.px(5)), 13, TEXT, True)
        hud = (f"score {game.score}   combo {game.combo}   accuracy {game.accuracy:.0f}%   "
               f"timing offset {game.offset * 1000:+.0f} ms")
        self.text(self.screen, hud, (r.right - self.px(12), r.y + self.px(5)), 12, MUTED, False, "topright")

        clip = self.screen.get_clip()
        lanes_rect = pygame.Rect(r.x + self.px(8), top, r.w - self.px(16), lane_h * len(lanes))
        self.screen.set_clip(lanes_rect)
        first = max(0, math.floor((t - (hit_x - r.x) / pps) / song.beat))
        last = math.ceil((t + (r.right - hit_x) / pps) / song.beat)
        for b in range(first, last + 1):
            x = int(hit_x + (b * song.beat - t) * pps)
            bar = b % song.beats_per_bar == 0
            pygame.draw.line(self.screen, LINE if bar else PANEL_HI, (x, top), (x, top + lane_h * len(lanes)),
                             2 if bar else 1)
            if bar:
                self.text(self.screen, str(b // song.beats_per_bar + 1), (x + self.px(4), top), 10, DIM)
        for li, hand in enumerate(lanes):
            ly = top + li * lane_h
            for n in game.notes:
                if n.hand != hand:
                    continue
                x0 = int(hit_x + (n.time - t) * pps)
                x1 = x0 + max(int(n.length * pps) - self.px(4), self.px(56))
                if x1 < r.x or x0 > r.right:
                    continue
                color = self.slot_color(hand, n.slot)
                if n.result == "miss":
                    color = DIM
                elif n.result:
                    color = mix(color, PANEL, 0.6)
                box = pygame.Rect(x0, ly + self.px(5), x1 - x0, lane_h - self.px(10))
                pygame.draw.rect(self.screen, color, box, border_radius=self.px(6))
                tx = min(max(x0, r.x + self.px(52)), x1 - self.px(50)) + self.px(6)
                self.text(self.screen, n.label, (tx, box.y + self.px(3)), 14, BG, True)
                self.text(self.screen, n.sign, (tx, box.bottom - self.px(3)), 10, BG, False, "bottomleft")
        self.screen.set_clip(clip)
        for li, hand in enumerate(lanes):  # lane labels and feedback, on top
            ly = top + li * lane_h
            pygame.draw.rect(self.screen, PANEL, (r.x + self.px(8), ly, self.px(40), lane_h))
            self.text(self.screen, hand, (r.x + self.px(28), ly + lane_h // 2), 18, HAND[hand], True, "center")
            fb = game.feedback.get(hand)
            if fb and now - fb[1] < 0.7:
                self.text(self.screen, fb[0], (hit_x - self.px(10), ly + lane_h // 2), 13, FEEDBACK.get(fb[2], TEXT),
                          True, "midright")
        pygame.draw.line(self.screen, TEXT, (hit_x, top - self.px(2)), (hit_x, top + lane_h * len(lanes) + self.px(2)),
                         self.px(3))

        # the sheet: this bar and the next ones
        bar_len = song.beat * song.beats_per_bar
        cur = max(0, math.floor(t / bar_len)) if t >= 0 else 0
        x, y = r.x + self.px(12), r.bottom - self.px(8)
        for b in range(cur, min(cur + 6, len(game.bar_texts))):
            label = f"{b + 1}  {game.bar_texts[b]}"
            rr = self.text(self.screen, label, (x, y), 12, TEXT if (b == cur and t >= 0) else DIM,
                           b == cur and t >= 0, "bottomleft")
            x = rr.right + self.px(26)
            if x > r.right - self.px(160):
                break
        if t < 0:  # count-in over the main panels
            self.text(self.screen, str(math.ceil(-t / song.beat)), main.center, 110, TEXT, True, "center")

    def draw_results(self, r, main):
        game, app = self.app.game, self.app
        card = pygame.Rect(0, 0, self.px(520), self.px(300))
        card.center = main.center
        pygame.draw.rect(self.screen, (0, 0, 0), card.move(self.px(4), self.px(6)), border_radius=self.px(14))
        pygame.draw.rect(self.screen, PANEL_HI, card, border_radius=self.px(14))
        x = card.x + self.px(28)
        self.text(self.screen, game.song.title, (x, card.y + self.px(22)), 20, TEXT, True)
        self.text(self.screen, game.grade, (card.right - self.px(30), card.y + self.px(18)), 54, GOOD, True, "topright")
        best = "New best score!" if game.new_best else f"Best {game.scores.get(game.song.title, 0)}"
        lines = [(f"Accuracy {game.accuracy:.1f}%", 16, TEXT), (f"Score {game.score}   ·   {best}", 14, TEXT),
                 (f"Perfect {game.counts['perfect']}   Good {game.counts['good']}   Miss {game.counts['miss']}", 13, MUTED),
                 (f"Longest combo {game.max_combo}", 13, MUTED)]
        y = card.y + self.px(70)
        for text, size, color in lines:
            self.text(self.screen, text, (x, y), size, color, size >= 16)
            y += self.px(30)
        self.button((x, card.bottom - self.px(56), self.px(150), self.px(36)), "Play again (j)", app.toggle_game,
                    size=13)
        self.button((x + self.px(162), card.bottom - self.px(56), self.px(150), self.px(36)), "Next song (n)",
                    app.next_song, size=13)
        self.text(self.screen, "Song list and sheets: songs/ folder", (r.x + self.px(12), r.centery), 12, DIM, False,
                  "midleft")

    # ---------------------------------------------------------------- settings drawer

    def draw_settings(self, L):
        top, footer = L["top"], L["footer"]
        W = L["W"]
        w = min(self.px(780), int(W * 0.62))
        d = pygame.Rect(W - w - self.px(12), top.bottom + self.px(4), w, footer.top - top.bottom - self.px(10))
        self.drawer = d
        pygame.draw.rect(self.screen, (0, 0, 0), d.move(-self.px(4), self.px(6)), border_radius=self.px(14))
        pygame.draw.rect(self.screen, PANEL, d, border_radius=self.px(14))
        pygame.draw.rect(self.screen, LINE, d, 1, border_radius=self.px(14))
        self.hits.append(Hit(d))  # clicks inside the panel don't fall through
        self.text(self.screen, "Settings", (d.x + self.px(20), d.y + self.px(16)), 20, TEXT, True)
        self.button((d.right - self.px(48), d.y + self.px(12), self.px(34), self.px(30)), "",
                    lambda: setattr(self, "settings_open", False), icon="close")
        # tabs down the left side
        side_w = self.px(138)
        row = min(self.px(38), (d.h - self.px(70)) // len(TABS))
        for i, tab in enumerate(TABS):
            self.button((d.x + self.px(14), d.y + self.px(58) + i * row, side_w, row - self.px(6)), tab,
                        lambda t=tab: setattr(self, "settings_tab", t), active=self.settings_tab == tab, size=12)
        body = pygame.Rect(d.x + side_w + self.px(32), d.y + self.px(58), d.w - side_w - self.px(52),
                           d.h - self.px(72))
        name = self.settings_tab.lower().replace(" & ", "_").replace(" ", "_")

        # the tab draws into a scrolled copy of the body, clipped; hits outside the body are dropped
        scroll = min(self.scroll.get(self.settings_tab, 0), self.overflow.get(self.settings_tab, 0))
        first_hit = len(self.hits)
        clip = self.screen.get_clip()
        self.screen.set_clip(body)
        end = getattr(self, "tab_" + name)(body.move(0, -scroll))
        self.screen.set_clip(clip)
        kept = []
        for hit in self.hits[first_hit:]:
            hit.rect = hit.rect.clip(body)
            if hit.rect.w and hit.rect.h:
                kept.append(hit)
        self.hits[first_hit:] = kept
        overflow = max(0, (end or 0) + scroll - body.bottom + self.px(12))
        self.overflow[self.settings_tab] = overflow
        self.scroll[self.settings_tab] = min(scroll, overflow)
        if overflow:  # scrollbar
            track = pygame.Rect(d.right - self.px(10), body.y, self.px(4), body.h)
            pygame.draw.rect(self.screen, PANEL_HI, track, border_radius=self.px(2))
            thumb_h = max(self.px(30), int(body.h * body.h / (body.h + overflow)))
            thumb_y = body.y + int((body.h - thumb_h) * scroll / overflow)
            pygame.draw.rect(self.screen, MUTED, (track.x, thumb_y, track.w, thumb_h), border_radius=self.px(2))

    def heading(self, label, x, y, w=None):
        self.text(self.screen, label, (x, y), 13, TEXT, True)
        return y + self.px(24)

    def note(self, label, x, y, w, color=MUTED, size=12):
        """Wrapped paragraph; returns the y below it."""
        words, line = label.split(), ""
        f = self.font(size)
        for word in words:
            trial = f"{line} {word}".strip()
            if f.size(trial)[0] > w and line:
                self.text(self.screen, line, (x, y), size, color)
                y += self.px(size + 6)
                line = word
            else:
                line = trial
        if line:
            self.text(self.screen, line, (x, y), size, color)
            y += self.px(size + 6)
        return y

    def row_buttons(self, x, y, items, h=30, gap=6, size=12, max_x=None):
        """A row of buttons sized to their labels: items = (label, action, active[, color]). Wraps at max_x."""
        x0 = x
        for item in items:
            label, action, active = item[:3]
            color = item[3] if len(item) > 3 else ACCENT
            w = self.font(size, True).size(label)[0] + self.px(24)
            if max_x and x + w > max_x and x > x0:
                x, y = x0, y + self.px(h + gap)
            self.button((x, y, w, self.px(h)), label, action, active=active, color=color, size=size,
                        enabled=action is not None)
            x += w + self.px(gap)
        return y + self.px(h + gap + 4)

    def cached(self, key, seconds, make):
        """Cache a slow value (directory listings, song sheets) for a short time."""
        now = time.time()
        hit = self.cache.get(key)
        if hit is None or now - hit[0] > seconds:
            hit = self.cache[key] = (now, make())
        return hit[1]

    def open_folder(self, path):
        path.mkdir(exist_ok=True)
        try:
            os.startfile(path)
        except (AttributeError, OSError) as e:  # not Windows
            self.app.notify(f"Folder: {path}  ({e})", 5)

    def tab_instruments(self, b):
        app = self.app
        self.text(self.screen, "Each hand has its own instrument, volume and reverb. Choosing an instrument plays a "
                  "preview note.", (b.x, b.y), 12, MUTED, max_w=b.w)
        col_w = (b.w - self.px(16)) // 2
        for c, hand in enumerate(("L", "R")):
            x = b.x + c * (col_w + self.px(16))
            y = b.y + self.px(30)
            pygame.draw.circle(self.screen, HAND[hand], (x + self.px(10), y + self.px(10)), self.px(9))
            self.text(self.screen, HAND_NAME[hand], (x + self.px(26), y + self.px(10)), 14, HAND[hand], True, "midleft")
            if app.hand_plays_drums(hand):
                self.text(self.screen, "plays the drum kit in this mode", (x + self.px(26), y + self.px(28)), 11, MUTED)
            # mixer: volume and reverb send for this hand
            y += self.px(44)
            self.text(self.screen, "Volume", (x, y), 11, MUTED)
            self.slider((x + self.px(64), y - self.px(2), col_w - self.px(120), self.px(20)), app.engine.hand_gain[hand],
                        lambda v, h=hand: app.set_mix(h, volume=v), HAND[hand], f"{app.engine.hand_gain[hand] * 100:.0f}%")
            y += self.px(30)
            self.text(self.screen, "Reverb", (x, y), 11, MUTED)
            self.slider((x + self.px(64), y - self.px(2), col_w - self.px(120), self.px(20)), app.engine.hand_send[hand],
                        lambda v, h=hand: app.set_mix(h, reverb=v), HAND[hand], f"{app.engine.hand_send[hand] * 100:.0f}%")
            y += self.px(30)
            row_h = max(self.px(38), min(self.px(44), (b.bottom - y - self.px(50)) // len(INSTRUMENT_NAMES)))
            for i, name in enumerate(INSTRUMENT_NAMES):
                rect = (x, y + i * row_h, col_w, row_h - self.px(5))
                self.button(rect, name, lambda h=hand, n=name: app.set_instrument(h, n),
                            active=app.instruments[hand] == name, color=HAND[hand], size=13,
                            sub=INSTRUMENT_NOTES[name])
        # dynamics
        y += len(INSTRUMENT_NAMES) * row_h + self.px(6)
        self.toggle_row((b.x, y, b.w, self.px(34)), "Strike speed sets loudness (a quick, snappy sign plays louder)  [i]",
                        app.dynamics, app.toggle_dynamics)
        return y + self.px(40)

    def toggle_row(self, rect, label, on, action):
        rect = pygame.Rect(rect)
        hover = rect.collidepoint(self.mouse)
        pygame.draw.rect(self.screen, PANEL_HOVER if hover else PANEL_HI, rect, border_radius=self.px(7))
        self.text(self.screen, label, (rect.x + self.px(12), rect.centery), 12, TEXT, False, "midleft",
                  rect.w - self.px(80))
        sw_rect = pygame.Rect(rect.right - self.px(54), rect.centery - self.px(10), self.px(42), self.px(20))
        pygame.draw.rect(self.screen, GOOD if on else LINE, sw_rect, border_radius=self.px(10))
        knob_x = sw_rect.right - self.px(10) if on else sw_rect.x + self.px(10)
        pygame.draw.circle(self.screen, TEXT, (knob_x, sw_rect.centery), self.px(8))
        self.hits.append(Hit(rect, down=action))

    def tab_key_mapping(self, b):
        app = self.app
        core = self.core
        y = b.y
        self.text(self.screen, "Custom mode plays the sound you give each sign. Pick a hand and a sign, "
                  "then choose a note, chord or drum.", (b.x, y), 12, MUTED, max_w=b.w)
        y += self.px(24)
        if app.mode != "Custom":
            self.button((b.x, y, self.px(230), self.px(28)), "Switch to Custom mode", lambda: app.set_mode("Custom"),
                        size=12)
            self.text(self.screen, f"(now: {app.mode})", (b.x + self.px(240), y + self.px(14)), 11, MUTED, False,
                      "midleft")
        else:
            self.text(self.screen, "Custom mode is on: your mapping is playing.", (b.x, y + self.px(14)), 12, GOOD,
                      True, "midleft")
        y += self.px(38)
        for i, hand in enumerate(("L", "R")):
            self.button((b.x + i * self.px(134), y, self.px(126), self.px(30)), HAND_NAME[hand],
                        lambda h=hand: setattr(self, "map_hand", h), active=self.map_hand == hand, color=HAND[hand],
                        size=13)
        y += self.px(40)

        # the 8 signs and what each plays
        hand = self.map_hand
        names = sign_names("Extended")
        col_w = (b.w - self.px(10)) // 2
        row_h = self.px(40)
        for s in range(8):
            rect = pygame.Rect(b.x + (s // 4) * (col_w + self.px(10)), y + (s % 4) * row_h, col_w, row_h - self.px(6))
            chosen = self.map_slot == s
            usable = s < 4 or app.effective_sign_set == "Extended"
            hover = rect.collidepoint(self.mouse)
            fill = mix(PANEL_HI, HAND[hand], 0.3) if chosen else (PANEL_HOVER if hover else PANEL_HI)
            pygame.draw.rect(self.screen, fill, rect, border_radius=self.px(7))
            _, pattern, thumb = SIGN_SETS["Extended"][s]
            self.sign_icon(pygame.Rect(rect.x + self.px(6), rect.y + self.px(4), self.px(26), rect.h - self.px(8)),
                           pattern, thumb, TEXT if usable else DIM, DIM)
            self.text(self.screen, names[s], (rect.x + self.px(40), rect.centery), 12, TEXT if usable else DIM,
                      chosen, "midleft")
            sound = core.pad_sound(core.CUSTOM_PADS[hand][s])[2]
            self.text(self.screen, sound, (rect.right - self.px(10), rect.centery), 14, SLOT[s] if sound != "-" else DIM,
                      True, "midright", col_w // 2)
            self.hits.append(Hit(rect, down=lambda i=s: setattr(self, "map_slot", i)))
        y += 4 * row_h + self.px(2)
        if app.effective_sign_set != "Extended":
            self.text(self.screen, "Signs 5-8 need the Extended sign set (press x).", (b.x, y), 11, WARN)
        y += self.px(22)

        # picker
        for i, kind in enumerate(["Note", "Chord", "Drum", "Empty"]):
            self.button((b.x + i * self.px(92), y, self.px(84), self.px(28)), kind,
                        lambda k=kind: setattr(self, "map_kind", k), active=self.map_kind == kind, size=12)
        y += self.px(38)
        assign = lambda pad: app.set_custom_pad(hand, self.map_slot, pad)  # noqa: E731
        if self.map_kind == "Note":
            self.text(self.screen, f"Octave {self.map_octave}–{self.map_octave + 1}", (b.x, y + self.px(12)), 12, TEXT,
                      True, "midleft")
            self.button((b.x + self.px(110), y, self.px(30), self.px(24)), "−",
                        lambda: setattr(self, "map_octave", max(1, self.map_octave - 1)), size=14)
            self.button((b.x + self.px(144), y, self.px(30), self.px(24)), "+",
                        lambda: setattr(self, "map_octave", min(6, self.map_octave + 1)), size=14)
            y += self.px(32)
            self.keyboard(pygame.Rect(b.x, y, b.w, self.px(96)), lambda m: assign({"kind": "note", "midi": m}))
            y += self.px(106)
        elif self.map_kind == "Chord":
            bw = (b.w - self.px(5) * 11) // 12
            for i, name in enumerate(NOTE_NAMES):
                def pick_root(i=i):
                    self.map_root = i
                    assign({"kind": "chord", "name": NOTE_NAMES[i] + self.map_quality})
                self.button((b.x + i * (bw + self.px(5)), y, bw, self.px(30)), name, pick_root,
                            active=self.map_root == i, size=12)
            y += self.px(38)
            for i, q in enumerate(CHORD_TYPES):
                def pick_quality(q=q):
                    self.map_quality = q
                    assign({"kind": "chord", "name": NOTE_NAMES[self.map_root] + q})
                self.button((b.x + i * (bw + self.px(5)), y, bw, self.px(30)), q or "maj", pick_quality,
                            active=self.map_quality == q, size=11)
            y += self.px(40)
            self.text(self.screen, f"Assigns {NOTE_NAMES[self.map_root]}{self.map_quality}: choose a root, then a type.",
                      (b.x, y), 11, MUTED)
            y += self.px(30)
        elif self.map_kind == "Drum":
            bw = (b.w - self.px(6) * 3) // 4
            for i, drum in enumerate(DRUMS):
                self.button((b.x + (i % 4) * (bw + self.px(6)), y + (i // 4) * self.px(36), bw, self.px(30)),
                            LABELS[drum], lambda dr=drum: assign({"kind": "drum", "name": dr}), size=12)
            y += self.px(116)
        else:
            self.button((b.x, y, self.px(200), self.px(30)), "Clear this sign", lambda: assign(None), size=12)
            y += self.px(44)

        # start from a layout
        self.text(self.screen, "Start from a built-in layout (fills all 16 signs):", (b.x, y), 11, MUTED)
        y += self.px(20)
        y = self.row_buttons(b.x, y, [(m, lambda m=m: app.copy_mode_to_custom(m), False)
                                      for m in ["Notes", "Chords", "Drums", "Band"]] +
                             [("Reset to keyboard", app.reset_custom, False)], max_x=b.right)
        y += self.px(8)
        pygame.draw.line(self.screen, LINE, (b.x, y), (b.right, y))
        y += self.px(12)
        return self.presets(b, y)

    def presets(self, b, y):
        """Named key mappings saved in mappings/: save, load, import, export, delete."""
        app = self.app
        y = self.heading("Saved mappings", b.x, y)
        y = self.note("A preset stores all 16 signs. Presets are JSON files in the mappings/ folder, so you can "
                      "share them or keep backups.", b.x, y, b.w)
        y += self.px(4)
        typing = self.text_input and self.text_input.get("owner") == "preset"
        if typing:
            y += self.px(16)
            self.text_box((b.x, y, min(b.w, self.px(360)), self.px(32)))
            y += self.px(44)
        else:
            def save_as():
                def done(name):
                    app.save_preset(name)
                    self.preset_sel = name
                    self.cache.pop("presets", None)
                self.ask_text("Name for this mapping", done, self.preset_sel or "", owner="preset")
            y = self.row_buttons(b.x, y, [("Save current as...", save_as, False, GOOD),
                                          ("Import...", lambda: (app.import_preset(), self.cache.pop("presets", None)),
                                           False),
                                          ("Open folder", lambda: self.open_folder(settings_store.MAPPINGS_DIR), False)],
                                 max_x=b.right)
        names = self.cached("presets", 1.0, settings_store.list_presets)
        if not names:
            self.text(self.screen, "No saved mappings yet.", (b.x, y), 12, DIM)
            return y + self.px(24)
        if self.preset_sel not in names:
            self.preset_sel = None
        y = self.row_buttons(b.x, y, [(n, lambda n=n: setattr(self, "preset_sel", n), self.preset_sel == n)
                                      for n in names], h=28, max_x=b.right)
        if self.preset_sel:
            name = self.preset_sel
            confirming = self.confirm_delete == name

            def delete():
                if self.confirm_delete == name:
                    app.delete_preset(name)
                    self.confirm_delete = self.preset_sel = None
                    self.cache.pop("presets", None)
                else:
                    self.confirm_delete = name
            y = self.row_buttons(b.x, y, [(f"Load '{name}'", lambda: app.load_preset(name), False, GOOD),
                                          ("Export...", lambda: app.export_preset(name), False),
                                          ("Click again to delete" if confirming else "Delete", delete, confirming,
                                           BAD)], max_x=b.right)
        return y

    def keyboard(self, r, on_note):
        """Two-octave piano keyboard starting at map_octave; click a key to assign that note."""
        whites = [(o, pc) for o in (0, 1) for pc in WHITE_PCS] + [(2, 0)]
        kw = r.w / len(whites)
        current = self.core.CUSTOM_PADS[self.map_hand][self.map_slot]
        chosen = current["midi"] if current and current.get("kind") == "note" else None
        for i, (o, pc) in enumerate(whites):
            midi = 12 * (self.map_octave + o + 1) + pc
            rect = pygame.Rect(int(r.x + i * kw), r.y, int(kw) - self.px(2), r.h)
            fill = mix((240, 240, 240), HAND[self.map_hand], 0.6) if midi == chosen else \
                ((220, 225, 235) if rect.collidepoint(self.mouse) else (245, 245, 245))
            pygame.draw.rect(self.screen, fill, rect, border_bottom_left_radius=self.px(5),
                             border_bottom_right_radius=self.px(5))
            if pc == 0:
                self.text(self.screen, f"C{self.map_octave + o}", (rect.centerx, rect.bottom - self.px(4)), 10,
                          (60, 60, 70), False, "midbottom")
            self.hits.append(Hit(rect, down=lambda m=midi: on_note(m)))
        for i, (o, pc) in enumerate(whites[:-1]):
            if pc in (4, 11):
                continue
            midi = 12 * (self.map_octave + o + 1) + pc + 1
            rect = pygame.Rect(int(r.x + (i + 1) * kw - kw * 0.3), r.y, int(kw * 0.6), int(r.h * 0.6))
            fill = HAND[self.map_hand] if midi == chosen else ((70, 75, 90) if rect.collidepoint(self.mouse) else (30, 32, 38))
            pygame.draw.rect(self.screen, fill, rect, border_bottom_left_radius=self.px(4),
                             border_bottom_right_radius=self.px(4))
            self.hits.append(Hit(rect, down=lambda m=midi: on_note(m)))

    def tab_looper_midi(self, b):
        app, looper = self.app, self.app.looper
        y = b.y
        y = self.heading("Loop", b.x, y)
        status = {"empty": "Empty: press Record (r) and play", "countin": "Count-in: recording starts on the next bar",
                  "recording": "Recording the first take", "playing": "Playing", "overdub": "Overdubbing",
                  "stopped": "Stopped"}[looper.state]
        if looper.length:
            status += f"  ·  {looper.length:.1f} s ({looper.length / looper.bar:.1f} bars)  ·  {len(looper.layers)} layer" \
                      + ("s" if len(looper.layers) != 1 else "")
        self.text(self.screen, status, (b.x, y), 12, BAD if looper.recording else MUTED)
        y += self.px(24)
        rec_label = "Stop recording (r)" if looper.recording else ("Overdub (r)" if looper.layers else "Record (r)")
        y = self.row_buttons(b.x, y, [(rec_label, lambda: app.loop_action("toggle_record"), looper.recording, BAD),
                                      ("Stop (p)" if looper.state in ("playing", "overdub") else "Play (p)",
                                       lambda: app.loop_action("toggle_play"), looper.state == "playing", GOOD),
                                      ("Undo layer (u)", lambda: app.loop_action("undo"), False),
                                      ("Clear (c)", lambda: app.loop_action("clear"), False)], max_x=b.right)
        y += self.px(6)
        y = self.heading("Tempo", b.x, y)
        self.text(self.screen, f"{looper.bpm:g} BPM", (b.x, y + self.px(15)), 20, TEXT, True, "midleft")
        y = self.row_buttons(b.x + self.px(120), y, [
            ("−10", lambda: app.set_loop_bpm(looper.bpm - 10), False), ("−1", lambda: app.set_loop_bpm(looper.bpm - 1), False),
            ("+1", lambda: app.set_loop_bpm(looper.bpm + 1), False), ("+10", lambda: app.set_loop_bpm(looper.bpm + 10), False)],
            max_x=b.right)
        y = self.note("The tempo sets the metronome, the count-in, the quantise grid and the MIDI file tempo. "
                      "With the metronome or quantise on, the first take is rounded to whole bars.", b.x, y, b.w)
        y += self.px(6)
        for label, on, action in [("Metronome click while looping  [z]", looper.metronome, app.toggle_metronome),
                                  ("Count in one bar before the first take", looper.count_in, app.toggle_count_in)]:
            self.toggle_row((b.x, y, b.w, self.px(34)), label, on, action)
            y += self.px(40)
        self.text(self.screen, "Quantise new takes to  [w]", (b.x, y + self.px(15)), 12, TEXT, False, "midleft")

        def set_q(q):
            looper.quantise = q
            app.save()
        y = self.row_buttons(b.x + self.px(190), y, [(q, lambda q=q: set_q(q), looper.quantise == q) for q in QUANTISE],
                             max_x=b.right)
        y = self.note("Quantise moves each note's start to the nearest grid step and keeps its length; "
                      "Off keeps your exact timing.", b.x, y, b.w)
        y += self.px(6)
        pygame.draw.line(self.screen, LINE, (b.x, y), (b.right, y))
        y += self.px(12)

        y = self.heading("MIDI files", b.x, y)
        recording = app.router.performance is not None
        n = len(app.router.performance) if recording else 0
        rec_label = f"Stop and save ({n} event{'s' if n != 1 else ''})  [F7]" if recording \
            else "Record what I play  [F7]"
        y = self.row_buttons(b.x, y, [(rec_label, app.toggle_midi_recording, recording, BAD),
                                      ("Export the loop  [F8]", app.export_loop if looper.layers else None, False),
                                      ("Open recordings folder", lambda: self.open_folder(self.recordings_dir()), False)],
                             max_x=b.right)
        y = self.note("Files are standard MIDI (type 1, one track per hand, drums on channel 10, instrument program "
                      "changes included) at the loop tempo, so they open in any DAW or notation app.", b.x, y, b.w)
        return y

    @staticmethod
    def recordings_dir():
        from midi_file import RECORDINGS_DIR
        return RECORDINGS_DIR

    def tab_sessions(self, b):
        app = self.app
        y = b.y
        y = self.note("A session records only your tracked hand positions (21 points per hand, 30 times a second), "
                      "never camera images. Replay one to test settings, debug a sign, or demo the app without a "
                      "camera (also: python gesture_music.py --replay FILE, or --demo).", b.x, y, b.w)
        y += self.px(6)
        rec = app.session_recorder
        rec_label = f"Stop and save ({rec.frames / 30:.0f} s)  [F5]" if rec.active else "Record my hands  [F5]"
        demo = SESSIONS_DIR / "demo.gmsession"
        items = [(rec_label, app.toggle_session_recording if not app.player else None, rec.active, BAD)]
        if app.player:
            items.append(("Stop replay  [F6]", app.stop_replay, True, WARN))
        elif demo.exists():
            items.append(("Play the demo", lambda: app.start_replay(demo), False))
        items.append(("Open folder", lambda: self.open_folder(SESSIONS_DIR), False))
        y = self.row_buttons(b.x, y, items, max_x=b.right)
        if app.player:
            p = app.player
            self.text(self.screen, f"Replaying {p.path.name}: {p.position:.1f} / {p.length:.1f} s (loops)", (b.x, y),
                      12, WARN, True)
            y += self.px(26)
        y += self.px(4)
        y = self.heading("Recorded sessions", b.x, y)
        sessions = self.cached("sessions", 1.0, lambda: [(p, p.stat().st_size, p.stat().st_mtime)
                                                         for p in list_sessions()])
        if not sessions:
            self.text(self.screen, "None yet: press F5, play for a while, then press F5 again.", (b.x, y), 12, DIM)
            return y + self.px(24)
        for path, size, mtime in sessions[:40]:
            rect = pygame.Rect(b.x, y, b.w, self.px(36))
            playing = app.player is not None and app.player.path == path
            pygame.draw.rect(self.screen, mix(PANEL_HI, WARN, 0.2) if playing else PANEL_HI, rect,
                             border_radius=self.px(7))
            self.text(self.screen, path.stem, (rect.x + self.px(12), rect.centery), 13, TEXT, True, "midleft",
                      rect.w - self.px(300))
            info = f"{time.strftime('%d %b %H:%M', time.localtime(mtime))}  ·  {size / 1024:.0f} KB"
            self.text(self.screen, info, (rect.right - self.px(100), rect.centery), 11, MUTED, False, "midright")
            self.button((rect.right - self.px(90), rect.y + self.px(4), self.px(84), rect.h - self.px(8)),
                        "Stop" if playing else "Replay", app.stop_replay if playing else
                        (lambda p=path: app.start_replay(p)), active=playing, color=WARN, size=12)
            y += self.px(42)
        return y

    def tab_songs(self, b):
        app, imp = self.app, self.app.importer
        y = b.y
        if imp.state == "idle":
            y = self.note("Add your own music for the rhythm game. Gesture Music listens to the file and finds the "
                          "tempo, where bar 1 starts, the key, the chords and the main melody, then writes a song "
                          "sheet you can play along to. The music plays with the game.", b.x, y, b.w)
            y += self.px(6)
            y = self.row_buttons(b.x, y, [("Add a music file...  [a]", self.add_song, True, GOOD)], h=36, size=13)
            y = self.note("Audio: MP3, WAV, FLAC, OGG, AIFF.  MIDI: .mid files give "
                          "exact notes and get a synthesized backing.", b.x, y, b.w, DIM, 11)
        elif imp.state == "analysing":
            spin = "|/-\\"[int(time.time() * 8) % 4]
            self.text(self.screen, f"{spin}  Analysing...  {imp.message}", (b.x, y), 14, WARN, True)
            y += self.px(30)
            y = self.note("This takes a few seconds for a typical song.", b.x, y, b.w)
        elif imp.state == "error":
            y = self.note(imp.message, b.x, y, b.w, BAD, 13)
            y = self.row_buttons(b.x, y + self.px(4), [("Choose another file...", self.add_song, False),
                                                       ("Cancel", lambda: setattr(imp, "state", "idle"), False)])
        else:
            y = self.song_draft(b, y)
        y += self.px(10)
        pygame.draw.line(self.screen, LINE, (b.x, y), (b.right, y))
        y += self.px(12)

        # songs already in songs/
        game = app.game
        y = self.heading(f"Your songs ({len(game.paths)})", b.x, y)
        if not game.paths:
            self.text(self.screen, "No songs yet.", (b.x, y), 12, DIM)
            y += self.px(24)
        titles = self.cached(("titles", tuple(game.paths)), 5.0, lambda: [self.song_title(p) for p in game.paths])
        for i, (path, title) in enumerate(zip(game.paths, titles)):
            rect = pygame.Rect(b.x, y, b.w, self.px(34))
            chosen = i == game.index
            pygame.draw.rect(self.screen, mix(PANEL_HI, GOOD, 0.18) if chosen else PANEL_HI, rect,
                             border_radius=self.px(7))
            self.text(self.screen, title, (rect.x + self.px(12), rect.centery), 13, TEXT, chosen, "midleft",
                      rect.w - self.px(220))
            self.text(self.screen, path.name, (rect.right - self.px(100), rect.centery), 10, DIM, False, "midright",
                      self.px(110))
            playing = chosen and game.state == "playing"
            self.button((rect.right - self.px(90), rect.y + self.px(4), self.px(84), rect.h - self.px(8)),
                        "Stop" if playing else "Play", lambda i=i: app.select_song(i, play=True),
                        active=playing, color=GOOD, size=12)
            y += self.px(40)
        y = self.row_buttons(b.x, y + self.px(4), [("Open songs folder", lambda: self.open_folder(self.songs_dir()),
                                                    False)])
        return self.note("Sheets are plain text (songs/README.md explains the format); edit them to fix any "
                         "note the analysis got wrong. Your own music files are copied to songs/audio/.",
                         b.x, y, b.w, DIM, 11)

    @staticmethod
    def songs_dir():
        from game import SONGS_DIR
        return SONGS_DIR

    @staticmethod
    def song_title(path):
        from game import load_song
        try:
            return load_song(path).title
        except (ValueError, OSError):
            return path.stem + "  (can't read this sheet)"

    def song_draft(self, b, y):
        """The analysis of a newly added file, with everything you can correct before creating the song."""
        imp = self.app.importer
        d = imp.draft
        typing = self.text_input and self.text_input.get("owner") == "title"
        if typing:
            y += self.px(16)
            self.text_box((b.x, y, min(b.w, self.px(380)), self.px(32)))
            y += self.px(44)
        else:
            r = self.text(self.screen, d.title, (b.x, y), 18, TEXT, True, max_w=b.w - self.px(110))
            self.button((r.right + self.px(10), y, self.px(80), self.px(26)), "Rename",
                        lambda: self.ask_text("Song title", lambda t: setattr(d, "title", t), d.title, owner="title"),
                        size=11)
            y += self.px(34)
        source = f"{d.source.name}  ·  {d.duration // 60:.0f}:{d.duration % 60:02.0f}  ·  key {d.key_name}"
        if d.kind == "audio":
            source += f"  ·  beat confidence {d.confidence * 100:.0f}%"
        self.text(self.screen, source, (b.x, y), 11, MUTED, max_w=b.w)
        y += self.px(24)
        if d.kind == "audio" and d.confidence < 0.4:
            y = self.note("The beat is not very clear in this recording: listen and check the tempo and bar start "
                          "below, or tap along to set them.", b.x, y, b.w, WARN, 11)

        # tempo
        self.text(self.screen, "Tempo", (b.x, y + self.px(15)), 12, MUTED, False, "midleft")
        self.text(self.screen, f"{d.bpm:.1f} BPM", (b.x + self.px(70), y + self.px(15)), 16, TEXT, True, "midleft")
        y = self.row_buttons(b.x + self.px(170), y, [
            ("÷2", lambda: imp.set_bpm(d.bpm / 2), False), ("−1", lambda: imp.set_bpm(d.bpm - 1), False),
            ("−0.1", lambda: imp.set_bpm(d.bpm - 0.1), False), ("+0.1", lambda: imp.set_bpm(d.bpm + 0.1), False),
            ("+1", lambda: imp.set_bpm(d.bpm + 1), False), ("×2", lambda: imp.set_bpm(d.bpm * 2), False)],
            h=28, max_x=b.right)
        # bar start
        self.text(self.screen, "Bar 1", (b.x, y + self.px(15)), 12, MUTED, False, "midleft")
        self.text(self.screen, f"{d.first_beat:.2f} s", (b.x + self.px(70), y + self.px(15)), 16, TEXT, True, "midleft")
        y = self.row_buttons(b.x + self.px(170), y, [
            ("−1 beat", lambda: imp.shift_start(-d.beat), False), ("−0.01 s", lambda: imp.shift_start(-0.01), False),
            ("+0.01 s", lambda: imp.shift_start(0.01), False), ("+1 beat", lambda: imp.shift_start(d.beat), False)],
            h=28, max_x=b.right)
        # listening
        listen = "Stop listening" if imp.previewing else "Listen with clicks (20 s)"
        y = self.row_buttons(b.x, y + self.px(2), [(listen, imp.preview, imp.previewing, WARN)], h=32)
        hint = imp.message or ("While listening, the rim clicks should land on the beats with the loud one on bar 1. "
                               "Tap Space on each beat (start on a bar's first beat): 4 or more taps set the tempo "
                               "and bar start for you.")
        y = self.note(hint, b.x, y, b.w, GOOD if imp.message else MUTED, 11)
        y += self.px(6)

        # chart
        self.text(self.screen, "Play the", (b.x, y + self.px(14)), 12, MUTED, False, "midleft")
        y = self.row_buttons(b.x + self.px(70), y, [(c, lambda c=c: setattr(imp, "chart", c), imp.chart == c)
                                                    for c in CHARTS], h=28)
        self.text(self.screen, "Difficulty", (b.x, y + self.px(14)), 12, MUTED, False, "midleft")
        y = self.row_buttons(b.x + self.px(70), y, [(c, lambda c=c: setattr(imp, "difficulty", c), imp.difficulty == c)
                                                    for c in DIFFICULTIES], h=28)
        y = self.note({"Melody": "the tune, note by note: low notes on the left hand, high on the right",
                       "Chords": "the chord changes, held on the right hand (left for extra chords)",
                       "Rhythm": "the beat: kick and snare on the left hand, hi-hat on the right"}[imp.chart],
                      b.x, y, b.w, MUTED, 11)
        # preview of the sheet
        key = ("sheet", id(d), round(d.bpm, 2), round(d.first_beat, 3), imp.chart, imp.difficulty)
        sheet = self.cached(key, 60.0, lambda: self.sheet_preview(d, imp.chart, imp.difficulty))
        box = pygame.Rect(b.x, y + self.px(4), b.w, self.px(18) * len(sheet) + self.px(14))
        pygame.draw.rect(self.screen, (12, 14, 19), box, border_radius=self.px(7))
        for i, line in enumerate(sheet):
            self.text(self.screen, line, (box.x + self.px(10), box.y + self.px(7) + i * self.px(18)), 11,
                      TEXT if i < 2 else MUTED, False, max_w=box.w - self.px(20))
        y = box.bottom + self.px(10)
        y = self.row_buttons(b.x, y, [("Create song", self.app.create_song, True, GOOD),
                                      ("Cancel", self.cancel_import, False)], h=34, size=13)
        return y

    def cancel_import(self):
        self.app.importer.stop_preview()
        self.app.importer.state, self.app.importer.draft = "idle", None

    @staticmethod
    def sheet_preview(d, chart, difficulty):
        """The pads and the first bars of the sheet that would be written."""
        from songmaker import make_sheet
        try:
            lines = make_sheet(d, chart, difficulty).splitlines()
        except Exception as e:  # analysis gave nothing usable for this chart
            return [f"Can't make this chart: {e}"]
        pads = [ln for ln in lines if ln.startswith(("right:", "left:"))]
        bars = [ln for ln in lines if ln.startswith(("play", "backing")) or ln.startswith("|")]
        return (pads or ["(no sounds found)"]) + bars[:4] + ([f"... {len(bars) - 4} more lines"] if len(bars) > 4 else [])

    def tab_calibrate(self, b):
        app = self.app
        y = b.y
        y = self.note("Calibration fits the finger thresholds to your hands, your camera and your lighting: hold "
                      "each sign for 2 seconds and the app measures how bent each finger is when it should be up and "
                      "when it should be down, then puts the thresholds in the gap between them. It is the biggest "
                      "single improvement to how reliably signs are read.", b.x, y, b.w)
        y += self.px(6)
        for hand in ("L", "R"):
            cal = app.calibration.get(hand)
            rect = pygame.Rect(b.x, y, b.w, self.px(52))
            pygame.draw.rect(self.screen, PANEL_HI, rect, border_radius=self.px(8))
            pygame.draw.circle(self.screen, HAND[hand], (rect.x + self.px(18), rect.y + self.px(17)), self.px(8))
            self.text(self.screen, HAND_NAME[hand], (rect.x + self.px(34), rect.y + self.px(17)), 13, HAND[hand], True,
                      "midleft")
            if cal:
                self.text(self.screen, "Calibrated", (rect.right - self.px(12), rect.y + self.px(17)), 12, GOOD, True,
                          "midright")
                detail = "   ".join(f"{FINGER_NAMES[f]} up <{cal['ext_max'][f]:.0f}° down >{cal['curl_min'][f]:.0f}°"
                                    for f in range(4))
            else:
                self.text(self.screen, "Default thresholds", (rect.right - self.px(12), rect.y + self.px(17)), 12,
                          MUTED, False, "midright")
                detail = f"every finger: up below {EXTENDED_MAX_CURL:.0f}°, down above {CURLED_MIN_CURL:.0f}°"
            self.text(self.screen, detail, (rect.x + self.px(12), rect.bottom - self.px(8)), 10, MUTED, False,
                      "bottomleft", rect.w - self.px(24))
            y += self.px(58)
        y += self.px(4)
        basic = len(calibration.steps_for("Basic"))
        extended = len(calibration.steps_for("Extended"))
        per = calibration.GET_READY + calibration.HOLD
        y = self.row_buttons(b.x, y, [
            (f"Calibrate Basic signs ({basic} steps, {basic * per:.0f} s)  [F2]",
             lambda: self.start_calibration("Basic"), True, GOOD),
            (f"Calibrate Extended signs ({extended} steps, {extended * per:.0f} s)",
             lambda: self.start_calibration("Extended"), False, GOOD)], h=34, max_x=b.right)
        if app.calibration:
            y = self.row_buttons(b.x, y, [("Reset to defaults", app.reset_calibration, False)])
        y += self.px(4)
        y = self.heading("Tips", b.x, y)
        for tip in ["Calibrate both hands at once: keep them on their own side of the centre line.",
                    "Use your normal playing position and lighting.",
                    "Move a little while holding each sign (turn, tilt) so the fit covers how you really play.",
                    "Extended calibration also fits the thumb (thumbs up, call me).",
                    "Can't make a sign? Press Skip; that sign keeps the default thresholds.",
                    "Watch the score per sign afterwards: under 90% means that sign may be misread."]:
            y = self.note("•  " + tip, b.x, y, b.w, MUTED, 11)
        return y

    def start_calibration(self, sign_set):
        self.settings_open = False
        self.app.start_calibration(sign_set)

    # ---------------------------------------------------------------- calibration wizard

    def draw_calibration(self, strip, main):
        """The wizard in its own strip above the pads; the results as a card over the main area."""
        cal = self.app.calibrator
        if cal.done:
            self.draw_calibration_results(main, cal)
            return
        now = time.perf_counter()
        app = self.app
        name, pattern, thumb = cal.step
        card = strip
        pygame.draw.rect(self.screen, PANEL_HI, card, border_radius=self.px(10))
        pygame.draw.rect(self.screen, mix(PANEL_HI, ACCENT, 0.5), card, 1, border_radius=self.px(10))
        self.hits.append(Hit(card))

        # ghost of the sign to make
        pic = pygame.Rect(card.x + self.px(14), card.y + self.px(14), self.px(150), card.h - self.px(28))
        pygame.draw.rect(self.screen, PANEL, pic, border_radius=self.px(10))
        holding = cal.phase == "hold"
        color = GOOD if holding else ACCENT
        pts = self.pose_points(handmodel.pose(pattern, thumb), (0, 0), 1.0, 0)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]   # fit the hand into the picture
        k = min((pic.w - self.px(24)) / (max(xs) - min(xs)), (pic.h - self.px(24)) / (max(ys) - min(ys)))
        ox = pic.centerx - k * (max(xs) + min(xs)) / 2
        oy = pic.centery - k * (max(ys) + min(ys)) / 2
        pts = [(ox + k * x_, oy + k * y_) for x_, y_ in pts]
        for a, b_, _ in BONES:
            pygame.draw.line(self.screen, color, pts[a], pts[b_], self.px(5))
        for i in TIPS:
            pygame.draw.circle(self.screen, TEXT, pts[i], self.px(4))

        x = pic.right + self.px(20)
        self.text(self.screen, f"CALIBRATING {cal.sign_set.upper()} SIGNS  ·  STEP {cal.index + 1} OF {len(cal.steps)}",
                  (x, card.y + self.px(16)), 10, MUTED, True)
        self.text(self.screen, f"Make this sign with both hands: {name}", (x, card.y + self.px(34)), 18, TEXT, True,
                  max_w=card.right - x - self.px(16))
        phase = "Hold it steady (move it a little)..." if holding else "Get ready..."
        self.text(self.screen, phase, (x, card.y + self.px(64)), 13, color, True)
        bar = pygame.Rect(x, card.y + self.px(88), card.right - x - self.px(20), self.px(8))
        pygame.draw.rect(self.screen, LINE, bar, border_radius=self.px(4))
        pygame.draw.rect(self.screen, color, (bar.x, bar.y, int(bar.w * max(0.0, cal.progress(now))), bar.h),
                         border_radius=self.px(4))
        # each hand: frames collected and a live check of every finger against the sign
        col_w = (card.right - x - self.px(20)) // 2
        for c, hand in enumerate(("L", "R")):
            hx, hy = x + c * col_w, card.y + self.px(108)
            state = app.hands[hand]
            seen = state.wrist is not None
            self.text(self.screen, HAND_NAME[hand], (hx, hy), 12, HAND[hand] if seen else DIM, True)
            frames = cal.frames(hand)
            self.text(self.screen, f"{frames} frames" if holding else ("in view" if seen else "not in view"),
                      (hx + self.px(90), hy), 11, MUTED if seen else BAD)
            for f in range(4):
                dx = hx + f * self.px(52)
                right = seen and bool(state.extended[f]) == bool(pattern[f])
                pygame.draw.circle(self.screen, (GOOD if right else WARN) if seen else LINE,
                                   (dx + self.px(6), hy + self.px(30)), self.px(5))
                self.text(self.screen, FINGER_NAMES[f], (dx + self.px(15), hy + self.px(30)), 10, MUTED, False,
                          "midleft")
        bx = card.right - self.px(14)
        for label, action in [("Cancel (Esc)", lambda: app.finish_calibration(save=False)),
                              ("Skip this sign", lambda: cal.skip(time.perf_counter()))]:
            w = self.font(11, True).size(label)[0] + self.px(22)
            self.button((bx - w, card.y + self.px(10), w, self.px(26)), label, action, size=11)
            bx -= w + self.px(6)

    def draw_calibration_results(self, main, cal):
        app = self.app
        card = pygame.Rect(0, 0, min(main.w - self.px(40), self.px(980)), min(main.h - self.px(20), self.px(470)))
        card.center = main.center
        pygame.draw.rect(self.screen, (0, 0, 0), card.move(self.px(4), self.px(6)), border_radius=self.px(14))
        pygame.draw.rect(self.screen, PANEL_HI, card, border_radius=self.px(14))
        self.hits.append(Hit(card))
        x = card.x + self.px(24)
        self.text(self.screen, "Calibration results", (x, card.y + self.px(18)), 20, TEXT, True)
        result = cal.result or {}
        if not result:
            self.note("Neither hand was seen for long enough. Make sure both hands are in view and well lit, then try "
                      "again.", x, card.y + self.px(60), card.w - self.px(48), WARN, 13)
        col_w = (card.w - self.px(48) - self.px(20)) // 2
        for c, hand in enumerate(("L", "R")):
            cx, y = x + c * (col_w + self.px(20)), card.y + self.px(58)
            res = result.get(hand)
            if res is None:
                if result:
                    self.text(self.screen, f"{HAND_NAME[hand]}: not seen enough, keeps its current thresholds",
                              (cx, y), 12, DIM, max_w=col_w)
                continue
            self.text(self.screen, HAND_NAME[hand], (cx, y), 14, HAND[hand], True)
            y += self.px(26)
            for f in res["fingers"]:   # up and down ranges on one axis with the new thresholds
                self.text(self.screen, f["name"], (cx, y), 11, TEXT)
                axis = pygame.Rect(cx + self.px(54), y + self.px(5), col_w - self.px(150), self.px(8))
                pygame.draw.rect(self.screen, (50, 55, 66), axis, border_radius=self.px(4))

                def ax(v):
                    return axis.x + int(axis.w * max(0, min(260, v)) / 260)
                if f["up"]:
                    pygame.draw.rect(self.screen, GOOD, (ax(f["up"][0]), axis.y, max(2, ax(f["up"][1]) - ax(f["up"][0])),
                                                         axis.h), border_radius=self.px(3))
                if f["down"]:
                    pygame.draw.rect(self.screen, MUTED, (ax(f["down"][0]), axis.y,
                                                          max(2, ax(f["down"][1]) - ax(f["down"][0])), axis.h),
                                     border_radius=self.px(3))
                for v in (f["ext_max"], f["curl_min"]):
                    pygame.draw.line(self.screen, TEXT, (ax(v), axis.y - self.px(4)), (ax(v), axis.bottom + self.px(4)), 2)
                verdict = f"{f['ext_max']:.0f}° / {f['curl_min']:.0f}°" if f["ok"] else f["why"]
                self.text(self.screen, verdict, (axis.right + self.px(10), y), 10, TEXT if f["ok"] else WARN,
                          max_w=self.px(90))
                y += self.px(22)
            if res["thumb"]:
                t = res["thresholds"]
                self.text(self.screen, f"thumb: out above {t['thumb_out_min']:.2f}, in below {t['thumb_in_max']:.2f}"
                          + ("" if res["thumb"]["ok"] else f"  ({res['thumb']['why']})"), (cx, y), 11,
                          TEXT if res["thumb"]["ok"] else WARN)
                y += self.px(22)
            self.text(self.screen, "green = finger up, grey = finger down, lines = new thresholds", (cx, y), 10, DIM)
            y += self.px(24)
            self.text(self.screen, "Signs read correctly with the new thresholds:", (cx, y), 11, MUTED)
            y += self.px(20)
            sx = cx
            for name, score in res["steps"]:
                label = f"{name} {'-' if score is None else f'{score * 100:.0f}%'}"
                w = self.font(10, True).size(label)[0] + self.px(14)
                if sx + w > cx + col_w:
                    sx, y = cx, y + self.px(26)
                color = DIM if score is None else (GOOD if score >= 0.9 else WARN if score >= 0.7 else BAD)
                rect = pygame.Rect(sx, y, w, self.px(22))
                pygame.draw.rect(self.screen, mix(PANEL_HI, color, 0.3), rect, border_radius=self.px(5))
                self.text(self.screen, label, rect.center, 10, TEXT, True, "center")
                sx += w + self.px(5)
        by = card.bottom - self.px(50)
        self.row_buttons(x, by, [("Save", lambda: app.finish_calibration(True), True, GOOD) if result else
                                 ("Save", None, False),
                                 ("Try again", lambda: app.start_calibration(cal.sign_set), False),
                                 ("Discard", lambda: app.finish_calibration(False), False)], h=34, size=13)

    def tab_display(self, b):
        app = self.app
        y = self.heading("Camera backdrop  [b]", b.x, b.y)
        y = self.row_buttons(b.x, y, [("Colour (chromesthesia)", lambda: app.cycle_background("Colour"),
                                       app.background == "Colour", GOOD),
                                      ("Blur", lambda: app.cycle_background("Blur"), app.background == "Blur"),
                                      ("Off", lambda: app.cycle_background("Off"), app.background == "Off")])
        y = self.note("Colour replaces the room behind you with a flowing gradient that takes on the colours of the "
                      "notes you play, using Scriabin's colours in circle-of-fifths order (below). Each note "
                      "blooms around you at its place on that colour wheel; louder notes bloom bigger, higher notes "
                      "are paler, the whole room drifts toward the harmony, and drums pulse and flash.",
                      b.x, y, b.w, MUTED, 11)
        sw = (b.w - self.px(4) * 11) // 12
        for i, (name, rgb) in enumerate(key_colours()):   # the colour key, in circle-of-fifths order
            rect = pygame.Rect(b.x + i * (sw + self.px(4)), y + self.px(2), sw, self.px(34))
            pygame.draw.rect(self.screen, rgb, rect, border_radius=self.px(6))
            self.text(self.screen, name, rect.center, 12, BG if sum(rgb) > 380 else TEXT, True, "center")
        y += self.px(50)
        self.text(self.screen, "Hand stage background", (b.x, y), 13, TEXT, True)
        y += self.px(26)
        sw = (b.w - self.px(8) * 4) // 5
        for i, (name, color) in enumerate(STAGE_COLORS):
            rect = pygame.Rect(b.x + i * (sw + self.px(8)), y, sw, self.px(54))
            pygame.draw.rect(self.screen, color, rect, border_radius=self.px(8))
            if app.stage_color == i:
                pygame.draw.rect(self.screen, ACCENT, rect, self.px(3), border_radius=self.px(8))
            ink = (40, 44, 52) if sum(color) > 450 else TEXT
            self.text(self.screen, name, (rect.centerx, rect.bottom - self.px(6)), 11, ink, False, "midbottom",
                      rect.w - self.px(6))

            def pick(i=i):
                app.stage_color = i
                app.save()
            self.hits.append(Hit(rect, down=pick))
        y += self.px(70)
        self.text(self.screen, "Hand stage view", (b.x, y), 13, TEXT, True)
        y += self.px(26)
        for i, (name, angle) in enumerate(STAGE_VIEWS):
            def pick_view(i=i):
                app.stage_view = i
                app.save()
            self.button((b.x + i * self.px(150), y, self.px(140), self.px(32)), f"{name} ({angle}°)", pick_view,
                        active=app.stage_view == i, size=12)
        y += self.px(50)
        self.text(self.screen, "Show", (b.x, y), 13, TEXT, True)
        y += self.px(26)
        toggles = [("Motion trails on the stage", app.trails, lambda: app.toggle("trails")),
                   ("Skeleton on the camera view", app.camera_skeleton, lambda: app.toggle("camera_skeleton")),
                   ("Debug: live finger measurements", app.show_debug,
                    lambda: setattr(app, "show_debug", not app.show_debug))]
        for label, on, action in toggles:
            rect = pygame.Rect(b.x, y, b.w, self.px(34))
            hover = rect.collidepoint(self.mouse)
            pygame.draw.rect(self.screen, PANEL_HOVER if hover else PANEL_HI, rect, border_radius=self.px(7))
            self.text(self.screen, label, (rect.x + self.px(12), rect.centery), 13, TEXT, False, "midleft")
            sw_rect = pygame.Rect(rect.right - self.px(54), rect.centery - self.px(10), self.px(42), self.px(20))
            pygame.draw.rect(self.screen, GOOD if on else LINE, sw_rect, border_radius=self.px(10))
            knob_x = sw_rect.right - self.px(10) if on else sw_rect.x + self.px(10)
            pygame.draw.circle(self.screen, TEXT, (knob_x, sw_rect.centery), self.px(8))
            self.hits.append(Hit(rect, down=action))
            y += self.px(40)
        y += self.px(8)
        self.button((b.x, y, self.px(220), self.px(32)), "Full screen (F11)", self.toggle_fullscreen,
                    active=self.fullscreen, size=12)
        return y + self.px(40)

    def tab_keys(self, b):
        col_w = (b.w - self.px(16)) // 2
        per_col = math.ceil(len(KEY_HELP) / 2)
        row = min(self.px(28), (b.h - self.px(30)) // per_col)
        for i, (key, desc) in enumerate(KEY_HELP):
            x = b.x + (i // per_col) * (col_w + self.px(16))
            y = b.y + (i % per_col) * row
            kr = pygame.Rect(x, y, self.px(66), row - self.px(6))
            pygame.draw.rect(self.screen, PANEL_HI, kr, border_radius=self.px(5))
            self.text(self.screen, key, kr.center, 12, TEXT, True, "center")
            self.text(self.screen, desc, (kr.right + self.px(10), kr.centery), 12, MUTED, False, "midleft",
                      col_w - self.px(80))
        self.text(self.screen, "Click any pad to play it. Click the chips at the top to change settings.",
                  (b.x, b.bottom - self.px(4)), 11, DIM, False, "bottomleft")
