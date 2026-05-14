"""
transcriber.py

Wraps OpenAI Whisper for word-level transcription.
Only one file per group needs to be transcribed; the resulting
word timestamps are shared across all three takes.

Word timestamps are returned as:
  [{"word": "Hello", "start": 0.34, "end": 0.71}, ...]

The caller decides which words define the cut boundaries.
"""

from __future__ import annotations
import threading
from typing import Callable, Dict, List, Optional, Tuple
import os

# Lazy-import whisper so the GUI loads even if whisper isn't installed yet
_whisper = None

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]


def _get_whisper():
    global _whisper
    if _whisper is None:
        import whisper
        _whisper = whisper
    return _whisper


def available_models() -> List[str]:
    return WHISPER_MODELS


def transcribe(
    audio_path: str,
    model_name: str = "base",
    language: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[Dict]]:
    """
    Transcribe a single audio file with word-level timestamps.

    Returns:
        full_text   – complete transcript string
        words       – list of {"word", "start", "end"} dicts

    Raises RuntimeError on failure.
    """
    if not os.path.isfile(audio_path):
        raise RuntimeError(f"Audio file not found: {audio_path}")

    whisper = _get_whisper()

    if progress_cb:
        progress_cb(f"Loading Whisper model '{model_name}'…")

    model = whisper.load_model(model_name)

    if progress_cb:
        progress_cb(f"Transcribing: {os.path.basename(audio_path)}")

    kwargs = dict(word_timestamps=True)
    if language:
        kwargs["language"] = language

    result = model.transcribe(audio_path, **kwargs)

    # Flatten word-level segments
    words: List[Dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            word_text = w.get("word", "").strip()
            if word_text:
                words.append({
                    "word":  word_text,
                    "start": float(w.get("start", 0)),
                    "end":   float(w.get("end", 0)),
                })

    full_text = result.get("text", "").strip()
    return full_text, words


def find_cut_boundaries(
    words: List[Dict],
    pad_start: float = 0.05,
    pad_end: float = 0.05,
) -> Tuple[float, float]:
    """
    Given the word list for a line, return (source_offset, length).
    pad_start / pad_end add a small buffer around the first and last word.
    """
    if not words:
        return 0.0, 0.0
    start = max(0.0, words[0]["start"] - pad_start)
    end   = words[-1]["end"] + pad_end
    length = end - start
    return start, length


class TranscriptionWorker(threading.Thread):
    """
    Background thread that transcribes one file and calls back with results.
    Designed to be driven by the GUI without blocking the UI thread.
    """

    def __init__(
        self,
        audio_path: str,
        model_name: str,
        row_index: str,
        on_progress: Callable[[str], None],
        on_complete: Callable[[str, str, List[Dict]], None],  # (row_index, text, words)
        on_error:    Callable[[str, str], None],              # (row_index, error_msg)
        language: Optional[str] = None,
    ):
        super().__init__(daemon=True)
        self.audio_path  = audio_path
        self.model_name  = model_name
        self.row_index   = row_index
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error    = on_error
        self.language    = language

    def run(self):
        try:
            text, words = transcribe(
                self.audio_path,
                model_name=self.model_name,
                language=self.language,
                progress_cb=self.on_progress,
            )
            self.on_complete(self.row_index, text, words)
        except Exception as e:
            self.on_error(self.row_index, str(e))
