"""
file_grouper.py

Groups audio files by index using the naming convention:
    BASENAME_VARIANT_INDEX[.TAKE].ext

Where:
  VARIANT  = 4060 | 4061 | 416
  INDEX    = digits (e.g. 01, 003, 42)
  .TAKE    = optional take suffix (e.g. .1, .2) -- ignored for grouping
  ext      = wav | aiff | flac | mp3

Examples that all match:
  250722_TNM_Rickey_Cross_4060_01.1.wav
  250722_TNM_Rickey_Cross_4060_01.wav
  MySession_416_003.wav

The INDEX is what gets matched against the spreadsheet index column.
"""

from __future__ import annotations
import os
import re
from typing import Dict, List, Tuple

MIC_VARIANTS = ["4060", "4061", "416"]

# BASENAME_VARIANT_INDEX[.TAKE].ext  --  .TAKE is optional
_PATTERN = re.compile(
    r"^(.+)_(4060|4061|416)_([0-9]+)(?:\.[0-9]+)?\.(wav|aiff|flac|mp3)$",
    re.IGNORECASE,
)


def scan_folder(folder: str) -> Tuple[List[Dict], List[str]]:
    """
    Scan a folder for audio files matching the naming convention.
    Returns (groups, unmatched_files).
    """
    if not os.path.isdir(folder):
        return [], []

    grouped: Dict[Tuple[str, str], Dict] = {}
    unmatched: List[str] = []

    for fname in sorted(os.listdir(folder)):
        fpath = os.path.join(folder, fname)
        if not os.path.isfile(fpath):
            continue

        m = _PATTERN.match(fname)
        if not m:
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".wav", ".aiff", ".flac", ".mp3"):
                unmatched.append(fpath)
            continue

        base, variant, index = m.group(1), m.group(2), m.group(3)
        key = (base.lower(), index.lower())
        if key not in grouped:
            grouped[key] = {
                "base":  base,
                "index": index,
                "4060":  None,
                "4061":  None,
                "416":   None,
            }
        grouped[key][variant] = fpath

    groups = sorted(grouped.values(), key=lambda g: _sort_key(g["index"]))
    return groups, unmatched


def _sort_key(index: str):
    """Sort numerically if index is all digits, else lexicographically."""
    if index.isdigit():
        return (0, int(index), "")
    return (1, 0, index.lower())


def groups_to_display(groups: List[Dict]) -> List[Dict]:
    """Return a simplified list for the grouping review table."""
    out = []
    for g in groups:
        out.append({
            "index":     g["index"],
            "base":      g.get("base", ""),
            "4060":      os.path.basename(g["4060"]) if g["4060"] else "---",
            "4061":      os.path.basename(g["4061"]) if g["4061"] else "---",
            "416":       os.path.basename(g["416"])  if g["416"]  else "---",
            "4060_path": g["4060"],
            "4061_path": g["4061"],
            "416_path":  g["416"],
        })
    return out
