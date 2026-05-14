"""
waveform_widget.py

A tkinter Canvas-based waveform viewer with draggable start/end handles.
Renders a downsampled peak waveform from a WAV/audio file.
Handles emit callbacks when the selection changes.

Usage:
    wf = WaveformWidget(parent, width=700, height=80)
    wf.load(filepath, initial_start=1.2, initial_end=3.8)
    wf.on_change = lambda s, e: print(s, e)  # start_sec, end_sec
"""

from __future__ import annotations
import os
import wave
import struct
import tkinter as tk
from typing import Optional, Callable, Tuple
import threading

# Colours
CLR_BG       = "#0f1a2e"
CLR_WAVE     = "#3a6ea8"
CLR_WAVE_HI  = "#5ab0f0"   # highlighted (selected) region wave
CLR_SEL      = "#ffffff18" # selection fill (semi-transparent via stipple)
CLR_HANDLE   = "#e94560"
CLR_HANDLE_H = "#ff7090"   # hovered handle
CLR_GRID     = "#1e2e40"
CLR_TEXT     = "#7a9ab8"

HANDLE_W  = 8   # handle half-width px
MIN_SPAN  = 0.01  # minimum selection in seconds


class WaveformWidget(tk.Canvas):
    def __init__(self, parent, width: int = 700, height: int = 80, **kwargs):
        super().__init__(
            parent,
            bg=CLR_BG, highlightthickness=0,
            **kwargs,
        )
        self._canvas_w = width
        self._canvas_h = height
        self.configure(width=width, height=height)
        self._peaks: list = []          # list of (min, max) normalised -1..1
        self._duration: float = 0.0
        self._filepath: str = ""

        self._sel_start: float = 0.0   # seconds
        self._sel_end:   float = 0.0

        self._drag: Optional[str] = None  # "start" | "end" | "body"
        self._drag_offset: float = 0.0

        self.on_change: Optional[Callable[[float, float], None]] = None

        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Motion>",          self._on_hover)
        self.bind("<Configure>",       self._on_resize)

        # Drawing deferred — <Configure> fires on first map

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, filepath: str, initial_start: float = 0.0,
             initial_end: Optional[float] = None):
        """Load audio file and render waveform in background thread."""
        self._filepath = filepath
        self._draw_loading()
        threading.Thread(
            target=self._load_worker,
            args=(filepath, initial_start, initial_end),
            daemon=True,
        ).start()

    def set_selection(self, start_sec: float, end_sec: float):
        """Programmatically set the selection handles."""
        self._sel_start = max(0.0, min(start_sec, self._duration))
        self._sel_end   = max(self._sel_start + MIN_SPAN,
                              min(end_sec, self._duration))
        self._redraw()

    def get_selection(self) -> Tuple[float, float]:
        return self._sel_start, self._sel_end

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_worker(self, filepath: str, initial_start: float,
                     initial_end: Optional[float]):
        try:
            peaks, duration = _compute_peaks(filepath, n_bins=self._canvas_w)
        except Exception as e:
            self.after(0, lambda msg=str(e): self._draw_error(msg))
            return
        self._peaks    = peaks
        self._duration = duration
        end = initial_end if initial_end is not None else duration
        self._sel_start = max(0.0, initial_start)
        self._sel_end   = min(end, duration)
        self.after(0, self._redraw)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_empty(self):
        try:
            self.delete("all")
            self.create_text(max(1, self._canvas_w // 2), max(1, self._canvas_h // 2),
                             text="No file loaded", fill=CLR_TEXT,
                             font=("Courier New", 9))
        except Exception:
            pass

    def _draw_loading(self):
        try:
            self.delete("all")
            w = self.winfo_width() or self._canvas_w
            h = self.winfo_height() or self._canvas_h
            self.create_rectangle(0, 0, w, h, fill=CLR_BG, outline="")
            self.create_text(max(1, w // 2), max(1, h // 2),
                             text="Loading waveform…", fill=CLR_TEXT,
                             font=("Courier New", 9))
        except Exception:
            pass

    def _draw_error(self, msg: str):
        try:
            self.delete("all")
            self.create_text(max(1, self._canvas_w // 2), max(1, self._canvas_h // 2),
                             text=f"Error: {msg[:60]}", fill="#e74c3c",
                             font=("Courier New", 9))
        except Exception:
            pass

    def _redraw(self, *_):
        try:
            self.delete("all")
        except Exception:
            return
        w, h = self._canvas_w, self._canvas_h
        mid  = h // 2

        # Background
        self.create_rectangle(0, 0, w, h, fill=CLR_BG, outline="")

        # Grid lines
        for i in range(0, w, max(1, w // 20)):
            self.create_line(i, 0, i, h, fill=CLR_GRID)
        self.create_line(0, mid, w, mid, fill=CLR_GRID)

        if not self._peaks or self._duration <= 0:
            return

        # Selection pixel range
        sx = self._sec_to_px(self._sel_start)
        ex = self._sec_to_px(self._sel_end)

        # Selection fill
        self.create_rectangle(sx, 0, ex, h,
                               fill="#1a3a5a", outline="", stipple="gray50")

        # Waveform bars
        n = len(self._peaks)
        for i, (lo, hi) in enumerate(self._peaks):
            x   = int(i * w / n)
            x2  = max(x + 1, int((i + 1) * w / n))
            y_hi = int(mid - hi * (mid - 2))
            y_lo = int(mid - lo * (mid - 2))
            y_lo = max(y_hi + 1, y_lo)
            in_sel = sx <= x <= ex
            colour = CLR_WAVE_HI if in_sel else CLR_WAVE
            self.create_rectangle(x, y_hi, x2, y_lo, fill=colour, outline="")

        # Time labels
        step = _nice_step(self._duration)
        t = 0.0
        while t <= self._duration:
            px = self._sec_to_px(t)
            self.create_line(px, h - 10, px, h, fill=CLR_TEXT)
            self.create_text(px + 2, h - 2, text=f"{t:.1f}s",
                             fill=CLR_TEXT, anchor="sw",
                             font=("Courier New", 7))
            t += step

        # Handles
        self._draw_handle(sx, "start")
        self._draw_handle(ex, "end")

        # Selection duration label
        dur = self._sel_end - self._sel_start
        mid_x = (sx + ex) // 2
        self.create_text(mid_x, 10, text=f"{dur:.3f}s",
                         fill="#ffffff", font=("Courier New", 8, "bold"))

    def _draw_handle(self, px: int, tag: str):
        h = self._canvas_h
        colour = CLR_HANDLE_H if self._drag == tag else CLR_HANDLE
        # Vertical line
        self.create_line(px, 0, px, h, fill=colour, width=2)
        # Triangle grip at top
        self.create_polygon(
            px - HANDLE_W, 0,
            px + HANDLE_W, 0,
            px, 14,
            fill=colour, outline="",
        )

    # ── Interaction ───────────────────────────────────────────────────────────

    def _on_press(self, event):
        sx = self._sec_to_px(self._sel_start)
        ex = self._sec_to_px(self._sel_end)
        if abs(event.x - sx) <= HANDLE_W + 2:
            self._drag = "start"
        elif abs(event.x - ex) <= HANDLE_W + 2:
            self._drag = "end"
        elif sx < event.x < ex:
            self._drag = "body"
            self._drag_offset = self._px_to_sec(event.x) - self._sel_start
        else:
            # Click outside: move nearest handle
            s_dist = abs(event.x - sx)
            e_dist = abs(event.x - ex)
            self._drag = "start" if s_dist < e_dist else "end"

    def _on_drag(self, event):
        if not self._drag or self._duration <= 0:
            return
        t = self._px_to_sec(event.x)
        if self._drag == "start":
            self._sel_start = max(0.0, min(t, self._sel_end - MIN_SPAN))
        elif self._drag == "end":
            self._sel_end = min(self._duration, max(t, self._sel_start + MIN_SPAN))
        elif self._drag == "body":
            span = self._sel_end - self._sel_start
            new_start = max(0.0, min(t - self._drag_offset, self._duration - span))
            self._sel_start = new_start
            self._sel_end   = new_start + span
        self._redraw()
        if self.on_change:
            self.on_change(self._sel_start, self._sel_end)

    def _on_release(self, event):
        self._drag = None
        self._redraw()

    def _on_hover(self, event):
        sx = self._sec_to_px(self._sel_start)
        ex = self._sec_to_px(self._sel_end)
        if abs(event.x - sx) <= HANDLE_W + 2 or abs(event.x - ex) <= HANDLE_W + 2:
            self.configure(cursor="sb_h_double_arrow")
        elif sx < event.x < ex:
            self.configure(cursor="fleur")
        else:
            self.configure(cursor="")

    def _on_resize(self, event):
        self._canvas_w = event.width
        self._canvas_h = event.height
        if self._peaks:
            self._redraw()
        else:
            self._draw_empty()

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _sec_to_px(self, t: float) -> int:
        if self._duration <= 0:
            return 0
        return int(t / self._duration * self._canvas_w)

    def _px_to_sec(self, px: int) -> float:
        if self._canvas_w <= 0:
            return 0.0
        return max(0.0, min(px / self._canvas_w * self._duration, self._duration))


# ── Audio peak computation ────────────────────────────────────────────────────

def _compute_peaks(filepath: str, n_bins: int = 700):
    """
    Read audio file, compute (min, max) amplitude peaks per bin.
    Returns (peaks, duration_seconds).
    Supports WAV natively; other formats via soundfile.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".wav":
        samples, rate, n_frames = _read_wav(filepath)
    else:
        import soundfile as sf
        data, rate = sf.read(filepath, dtype="float32", always_2d=False)
        if data.ndim == 2:
            data = data.mean(axis=1)
        samples = data.tolist()
        n_frames = len(samples)

    duration = n_frames / rate
    if not samples:
        return [], duration

    # Downsample to n_bins peaks
    bins = max(1, n_bins)
    step = max(1, n_frames // bins)
    peaks = []
    for i in range(bins):
        chunk = samples[i * step: (i + 1) * step]
        if not chunk:
            peaks.append((0.0, 0.0))
        else:
            peaks.append((min(chunk), max(chunk)))

    return peaks, duration


def _read_wav(filepath: str):
    """
    Read WAV file, return (normalised_float_samples, rate, n_frames).
    Handles 16-bit int, 24-bit int, 32-bit int, and 32-bit float WAV.
    Falls back to soundfile for any format the wave module can't handle.
    """
    import soundfile as sf
    import numpy as np
    try:
        data, rate = sf.read(filepath, dtype="float32", always_2d=True)
        # Mix to mono
        mono = data.mean(axis=1)
        return mono.tolist(), rate, len(mono)
    except Exception:
        pass
    # Hard fallback: wave module (integers only, no 32-bit float)
    with wave.open(filepath, "rb") as wf:
        rate     = wf.getframerate()
        sw       = wf.getsampwidth()
        nch      = wf.getnchannels()
        n_frames = wf.getnframes()
        raw      = wf.readframes(n_frames)
    fmt = {1: "b", 2: "h", 4: "i"}.get(sw, "h")
    total_samples = n_frames * nch
    expected_bytes = total_samples * sw
    unpacked = struct.unpack(f"<{total_samples}{fmt}", raw[:expected_bytes])
    if nch > 1:
        mono = [sum(unpacked[i:i+nch]) / nch for i in range(0, len(unpacked), nch)]
    else:
        mono = list(unpacked)
    max_val = float(2 ** (8 * sw - 1))
    return [s / max_val for s in mono], rate, n_frames


def _nice_step(duration: float) -> float:
    """Return a round time step for grid labels."""
    for step in [0.5, 1, 2, 5, 10, 30, 60]:
        if duration / step <= 20:
            return step
    return 60.0
