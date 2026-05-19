"""
aligner.py

Matches each spreadsheet line against all occurrences in a Whisper word-
timestamp transcript, grouping consecutive repetitions into takes.

Strategy:
  1. Fuzzy-match the full scripted line using a sliding window across the
     entire word list (independent of line order).
  2. Collect ALL windows whose match ratio exceeds a minimum threshold —
     each is a candidate take.
  3. Merge candidates that are close together in time (within MAX_TAKE_GAP
     seconds) into a single take cluster.
  4. The cluster with the highest average confidence wins.
  5. The single highest-ratio take within that cluster is the result.

  When an AAF is loaded, a post-alignment pass checks for overlapping clips
  on 'short' role tracks (editor selects).  A matching short clip overrides
  the whisper position with its precise source_in/source_out.

Confidence (1-5) is based on the BEST single take in the winning cluster:
  5 — ratio >= 0.92
  4 — ratio >= 0.80
  3 — ratio >= 0.65
  2 — ratio >= 0.45
  1 — ratio <  0.45
"""

from __future__ import annotations
import re
import difflib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# ── Tuning constants ──────────────────────────────────────────────────────────

# Base minimum ratio for a window to be a candidate take.
# For short lines (< 4 words) we use a higher threshold to avoid noise.
MIN_TAKE_RATIO_LONG  = 0.60   # lines >= 4 words
MIN_TAKE_RATIO_SHORT = 0.75   # lines < 4 words

# Two candidate windows closer than this (seconds gap) are merged into a cluster
MAX_TAKE_GAP = 5.0

# Window size variation relative to target word count
WINDOW_MIN_FACTOR = 0.65
WINDOW_MAX_FACTOR = 1.40


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TakeSpan:
    """A single matched take of a line."""
    word_start_i: int
    word_end_i:   int
    start_sec:    float
    end_sec:      float
    ratio:        float
    matched_text: str


@dataclass
class AlignmentResult:
    row_index:     str
    output_name:   str
    line_text:     str
    matched_text:  str
    takes:         List[TakeSpan] = field(default_factory=list)
    word_start_i:  int   = 0
    word_end_i:    int   = 0
    source_offset: float = 0.0
    length:        float = 0.0
    confidence:         int   = 1
    ratio:              float = 0.0
    needs_review:       bool  = True
    take_count:         int   = 1
    # Set post-alignment by the GUI once session-timeline positions are known.
    # Remain 0.0 when operating in folder mode (no AAF).
    session_time_start: float = 0.0
    session_time_end:   float = 0.0


# ── Text helpers ──────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words_to_str(words: List[Dict], start: int, end: int) -> str:
    return " ".join(w["word"] for w in words[start: end + 1])


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _confidence_from_ratio(r: float) -> int:
    if r >= 0.92: return 5
    if r >= 0.80: return 4
    if r >= 0.65: return 3
    if r >= 0.45: return 2
    return 1


# ── Core algorithm ────────────────────────────────────────────────────────────

def _find_all_takes(line_text: str, words: List[Dict]) -> List[TakeSpan]:
    """
    Slide a variable-width window across the full word list and collect every
    window whose fuzzy-match ratio against line_text exceeds MIN_TAKE_RATIO.
    Overlapping windows are de-duplicated keeping the highest-scoring one.
    """
    if not words:
        return []

    target    = _normalise(line_text)
    target_wc = max(1, len(target.split()))
    n         = len(words)
    min_wc    = max(1, int(target_wc * WINDOW_MIN_FACTOR))
    max_wc    = min(n, int(target_wc * WINDOW_MAX_FACTOR) + 1)
    threshold = MIN_TAKE_RATIO_SHORT if target_wc < 4 else MIN_TAKE_RATIO_LONG

    best_at_start: Dict[int, TakeSpan] = {}

    for wc in range(min_wc, max_wc + 1):
        for start in range(0, n - wc + 1):
            end       = start + wc - 1
            candidate = _normalise(_words_to_str(words, start, end))
            r         = _ratio(target, candidate)
            if r < threshold:
                continue
            prev = best_at_start.get(start)
            if prev is None or r > prev.ratio:
                best_at_start[start] = TakeSpan(
                    word_start_i=start,
                    word_end_i=end,
                    start_sec=words[start]["start"],
                    end_sec=words[end]["end"],
                    ratio=r,
                    matched_text=_words_to_str(words, start, end),
                )

    if not best_at_start:
        return []

    # Sort by start time, then de-overlap keeping higher-scoring window
    candidates = sorted(best_at_start.values(), key=lambda t: t.start_sec)
    deduped: List[TakeSpan] = []
    for span in candidates:
        if deduped and span.start_sec < deduped[-1].end_sec:
            if span.ratio > deduped[-1].ratio:
                deduped[-1] = span
        else:
            deduped.append(span)

    return deduped


def _cluster_takes(takes: List[TakeSpan]) -> List[List[TakeSpan]]:
    """
    Group takes within MAX_TAKE_GAP seconds of each other into clusters.
    Each cluster = all takes of one scripted line.
    """
    if not takes:
        return []
    clusters: List[List[TakeSpan]] = [[takes[0]]]
    for take in takes[1:]:
        gap = take.start_sec - clusters[-1][-1].end_sec
        if gap <= MAX_TAKE_GAP:
            clusters[-1].append(take)
        else:
            clusters.append([take])
    return clusters


def _score_cluster(cluster: List[TakeSpan]) -> float:
    return sum(t.ratio for t in cluster) / len(cluster)


def _best_single_fallback(
    line_text: str,
    words: List[Dict],
) -> Tuple[List[TakeSpan], float]:
    """Unconstrained best-window search used when nothing exceeds MIN_TAKE_RATIO."""
    target    = _normalise(line_text)
    target_wc = max(1, len(target.split()))
    n         = len(words)
    min_wc    = max(1, int(target_wc * 0.5))
    max_wc    = min(n, int(target_wc * 1.6) + 2)

    best_r, best_start, best_end = -1.0, 0, min(target_wc - 1, n - 1)

    for wc in range(min_wc, max_wc + 1):
        for start in range(0, n - wc + 1):
            end = start + wc - 1
            r   = _ratio(target, _normalise(_words_to_str(words, start, end)))
            if r > best_r:
                best_r, best_start, best_end = r, start, end

    span = TakeSpan(
        word_start_i=best_start,
        word_end_i=best_end,
        start_sec=words[best_start]["start"],
        end_sec=words[best_end]["end"],
        ratio=best_r,
        matched_text=_words_to_str(words, best_start, best_end),
    )
    return [span], best_r


def align_line_multitake(
    line_text: str,
    words: List[Dict],
    pad_start: float = 0.05,
    pad_end:   float = 0.10,
) -> Tuple[List[TakeSpan], float]:
    """
    Find the single best take of line_text in words.
    Returns ([best_take], best_take_ratio).
    """
    candidates = _find_all_takes(line_text, words)

    if not candidates:
        return _best_single_fallback(line_text, words)

    clusters   = _cluster_takes(candidates)
    best_cluster = max(clusters, key=_score_cluster)
    best_take  = max(best_cluster, key=lambda t: t.ratio)

    return [best_take], best_take.ratio


# ── Public API ────────────────────────────────────────────────────────────────

def align_all(
    rows: List[Dict],
    group_word_map: Dict[str, List[Dict]],
    row_to_group: Dict[str, str],
    pad_start: float = 0.05,
    pad_end:   float = 0.10,
) -> List[AlignmentResult]:
    results: List[AlignmentResult] = []

    for row in rows:
        ridx  = row["index"]
        gidx  = row_to_group.get(ridx)
        words = group_word_map.get(gidx, []) if gidx else []

        if not words:
            results.append(AlignmentResult(
                row_index=ridx,
                output_name=row.get("output_name", ridx),
                line_text=row["line_text"],
                matched_text="",
                takes=[],
                source_offset=0.0, length=0.0,
                confidence=1, ratio=0.0,
                needs_review=True, take_count=0,
            ))
            continue

        takes, best_ratio = align_line_multitake(
            row["line_text"], words, pad_start, pad_end,
        )

        first   = takes[0]
        last    = takes[-1]
        t_start = max(0.0, first.start_sec - pad_start)
        t_end   = last.end_sec + pad_end
        length  = max(0.01, t_end - t_start)
        conf    = _confidence_from_ratio(best_ratio)

        results.append(AlignmentResult(
            row_index=ridx,
            output_name=row.get("output_name", ridx),
            line_text=row["line_text"],
            matched_text=first.matched_text,
            takes=takes,
            word_start_i=first.word_start_i,
            word_end_i=last.word_end_i,
            source_offset=t_start,
            length=length,
            confidence=conf,
            ratio=best_ratio,
            needs_review=(conf <= 2),
            take_count=len(takes),
        ))

    return results
