"""
pt_session_parser.py

Parses a Pro Tools session text export (.txt) to extract session metadata
and the marker list.

Pro Tools exports these files via File > Export > Session Info as Text.
Relevant sections:
  - Header block: SESSION NAME, SAMPLE RATE
  - "M A R K E R S  L I S T I N G" section

Each PTMarker carries the marker's sequential list index, timecode, absolute
sample position, derived time-in-seconds, the user-supplied NAME field, and
the track name.  Markers whose NAME field is a pure integer (e.g. "22") are
called "numeric markers" and are used to map spreadsheet line indices to
session-timeline positions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class PTMarker:
    marker_num: int     # # column — sequential list index
    timecode:   str     # LOCATION column (HH:MM:SS:FF)
    sample:     int     # TIME REFERENCE column (absolute samples from session start)
    time_sec:   float   # sample / session sample_rate
    name:       str     # NAME column — numeric ("22") or text ("FLUB")
    track:      str     # TRACK NAME column


@dataclass
class PTSession:
    session_name: str
    sample_rate:  float
    markers:      List[PTMarker] = field(default_factory=list)

    def markers_by_name(self) -> Dict[str, List[PTMarker]]:
        """Return {name: [PTMarker, ...]} for every distinct marker name."""
        out: Dict[str, List[PTMarker]] = {}
        for m in self.markers:
            out.setdefault(m.name, []).append(m)
        return out

    def numeric_markers(self) -> Dict[str, List[PTMarker]]:
        """Return only markers whose NAME is a pure integer string (e.g. "22")."""
        return {name: mks for name, mks in self.markers_by_name().items()
                if name.isdigit()}


def parse_pt_session(path: str) -> PTSession:
    """
    Parse a Pro Tools session text export and return a PTSession.
    Missing or malformed lines are silently skipped.
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()

    session_name = ""
    sample_rate  = 48000.0
    markers: List[PTMarker] = []
    in_markers   = False
    past_header  = False

    for raw in lines:
        line = raw.rstrip('\n')

        # ── Header fields ──────────────────────────────────────────────────
        if line.startswith("SESSION NAME:"):
            session_name = line.split("\t", 1)[-1].strip()
            continue
        if line.startswith("SAMPLE RATE:"):
            try:
                sample_rate = float(line.split("\t", 1)[-1].strip())
            except ValueError:
                pass
            continue

        # ── Markers section ────────────────────────────────────────────────
        if "M A R K E R S  L I S T I N G" in line:
            in_markers  = True
            past_header = False
            continue

        if not in_markers:
            continue

        # Skip the column-header line (starts with "#")
        if not past_header:
            if line.lstrip().startswith("#"):
                past_header = True
            continue

        if not line.strip():
            continue

        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 5:
            continue
        try:
            marker_num = int(parts[0])
        except ValueError:
            continue

        timecode = parts[1]
        try:
            sample = int(parts[2])
        except ValueError:
            sample = 0
        # parts[3] = UNITS (Samples / Feet+Frames / etc.) — not used
        name  = parts[4]
        track = parts[5] if len(parts) > 5 else ""

        markers.append(PTMarker(
            marker_num=marker_num,
            timecode=timecode,
            sample=sample,
            time_sec=sample / sample_rate if sample_rate > 0 else 0.0,
            name=name,
            track=track,
        ))

    return PTSession(
        session_name=session_name,
        sample_rate=sample_rate,
        markers=markers,
    )
