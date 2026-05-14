"""
audio_player.py

Lightweight audio snippet player using pygame.
Handles init lazily so the app starts even if pygame has issues.

Usage:
    player = AudioPlayer()
    player.play(filepath, start_sec=1.2, duration_sec=3.5)
    player.stop()
"""

from __future__ import annotations
import os
import threading
import tempfile
import wave
import struct
from typing import Optional

_pygame = None
_mixer_ready = False


def _init_pygame():
    global _pygame, _mixer_ready
    if _pygame is not None:
        return _mixer_ready
    try:
        import pygame
        _pygame = pygame
        pygame.mixer.pre_init(frequency=48000, size=-16, channels=2, buffer=2048)
        pygame.mixer.init()
        _mixer_ready = True
    except Exception as e:
        print(f"[AudioPlayer] pygame init failed: {e}")
        _mixer_ready = False
    return _mixer_ready


def _extract_wav_snippet(src_path: str, start_sec: float, duration_sec: float) -> Optional[str]:
    """
    Extract a snippet from any audio file into a 16-bit PCM WAV temp file.
    Uses soundfile for all formats (handles 32-bit float WAV, FLAC, AIFF, etc).
    """
    try:
        import soundfile as sf
        data, rate = sf.read(src_path, dtype="float32", always_2d=True)
        start_f = max(0, int(start_sec * rate))
        end_f   = min(len(data), start_f + max(1, int(duration_sec * rate)))
        snippet = data[start_f:end_f]
        if len(snippet) == 0:
            print("[AudioPlayer] snippet is empty (check start/end times)")
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        sf.write(tmp.name, snippet, rate, subtype="PCM_16")
        return tmp.name
    except Exception as e:
        print(f"[AudioPlayer] extract failed: {e}")
        return None


class AudioPlayer:
    def __init__(self):
        self._lock = threading.Lock()
        self._current_tmp: Optional[str] = None
        self._play_thread: Optional[threading.Thread] = None

    def play(self, filepath: str, start_sec: float, duration_sec: float,
             on_done: Optional[callable] = None):
        """Play a snippet in a background thread. Stops any current playback first."""
        self.stop()
        self._play_thread = threading.Thread(
            target=self._play_worker,
            args=(filepath, start_sec, duration_sec, on_done),
            daemon=True,
        )
        self._play_thread.start()

    def _play_worker(self, filepath: str, start_sec: float, duration_sec: float,
                     on_done: Optional[callable]):
        if not _init_pygame():
            print("[AudioPlayer] mixer not available")
            return

        tmp_path = _extract_wav_snippet(filepath, start_sec, duration_sec)
        if not tmp_path:
            return

        with self._lock:
            self._current_tmp = tmp_path

        try:
            _pygame.mixer.music.load(tmp_path)
            _pygame.mixer.music.play()
            # Wait for playback to finish or stop() to be called
            clock = _pygame.time.Clock()
            while _pygame.mixer.music.get_busy():
                clock.tick(20)
        except Exception as e:
            print(f"[AudioPlayer] playback error: {e}")
        finally:
            try:
                _pygame.mixer.music.stop()
                _pygame.mixer.music.unload()
            except Exception:
                pass
            self._cleanup_tmp()
            if on_done:
                on_done()

    def stop(self):
        """Stop any current playback."""
        if not _mixer_ready or _pygame is None:
            return
        try:
            _pygame.mixer.music.stop()
        except Exception:
            pass
        self._cleanup_tmp()

    def _cleanup_tmp(self):
        with self._lock:
            if self._current_tmp and os.path.exists(self._current_tmp):
                try:
                    os.unlink(self._current_tmp)
                except Exception:
                    pass
            self._current_tmp = None

    def is_playing(self) -> bool:
        if not _mixer_ready or _pygame is None:
            return False
        try:
            return _pygame.mixer.music.get_busy()
        except Exception:
            return False
