"""
rpp_writer.py
Generates a REAPER .RPP project file compatible with REAPER 7.64/win64.

Each spreadsheet line becomes:
  - A named REGION spanning the item (name = output_name)
  - A MARKER at the region start (name = row index/order value)
  - Items on all 3 mic tracks with a <NOTES> block containing the line text
  - Item NAME is left blank (" ") — identification is via region/marker
"""

from __future__ import annotations
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ItemDef:
    """One audio item (clip) on the timeline."""
    track_idx: int
    source_path: str
    source_offset: float    # seconds into source file (SOFFS at item level)
    length: float           # item length in seconds
    timeline_pos: float     # position on timeline in seconds
    # Metadata written as region/marker/note (not as item name)
    output_name: str = ""   # → region name
    row_index: str = ""     # → marker name at region start
    note: str = ""          # → <NOTES> block inside item
    color: int = 0


@dataclass
class TrackDef:
    """One REAPER track."""
    name: str
    items: List[ItemDef] = field(default_factory=list)
    color: int = 0


# Track colours as 0x00RRGGBB
TRACK_COLORS = [
    0x00CC4400,   # warm amber  – 4060
    0x000044CC,   # deep blue   – 4061
    0x0000AA44,   # teal green  – 416
]


def _fmt(val: float) -> str:
    """Format a float without trailing zeros, up to 14 significant figures."""
    return f"{val:.14g}"


def _guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _reaper_color(rgb_int: int) -> int:
    """Convert 0x00RRGGBB → REAPER colour int (flag bit | BBGGRR)."""
    r = (rgb_int >> 16) & 0xFF
    g = (rgb_int >> 8)  & 0xFF
    b =  rgb_int        & 0xFF
    return (1 << 24) | (b << 16) | (g << 8) | r


def _quote(s: str) -> str:
    """Always wrap in double-quotes (REAPER accepts this for all token values)."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _marker_name(s: str) -> str:
    """Quote marker/region name only if it contains spaces or is empty."""
    if not s or " " in s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def build_rpp(
    tracks: List[TrackDef],
    project_name: str = "Session",
    bpm: float = 120.0,
    sample_rate: int = 48000,
) -> str:
    """Return the full RPP text for a REAPER 7.64/win64 project."""
    ts = int(time.time())
    lines: List[str] = []

    def w(indent: int, text: str):
        lines.append("  " * indent + text)

    # ── Project header ────────────────────────────────────────────────────────
    w(0, f'<REAPER_PROJECT 0.1 "7.64/win64" {ts} 0')
    w(1, "RIPPLE 0 0")
    w(1, "GROUPOVERRIDE 0 0 0 0")
    w(1, "AUTOXFADE 129")
    w(1, "ENVATTACH 1")
    w(1, "POOLEDENVATTACH 0")
    w(1, "TCPUIFLAGS 0")
    w(1, "MIXERUIFLAGS 11 48")
    w(1, "PEAKGAIN 1")
    w(1, "FEEDBACK 0")
    w(1, "PANLAW 1")
    w(1, "PROJOFFS 0 0 0")
    w(1, "MAXPROJLEN 0 600")
    w(1, "GRID 3199 8 0.125 8 1 0 0 0")
    w(1, "TIMEMODE 5 5 -1 30 0 0 -1 0")
    w(1, "VIDEO_CONFIG 0 0 256")
    w(1, "PANMODE 3")
    w(1, "CURSOR 0")
    w(1, "ZOOM 100 0 0")
    w(1, "VZOOMEX 6 0")
    w(1, "USE_REC_CFG 0")
    w(1, "RECMODE 1")
    w(1, "SMPTESYNC 0 30 100 40 1000 300 0 0 1 0 0")
    w(1, "LOOP 0")
    w(1, "LOOPGRAN 0 4")
    w(1, "TIMELOCKMODE 0")
    w(1, "TEMPOENVLOCKMODE 1")
    w(1, "ITEMMIX 0")
    w(1, "DEFPITCHMODE 589824 0")
    w(1, "TAKELANE 1")
    w(1, f"SAMPLERATE {sample_rate} 1 0")
    w(1, "LOCK 1")
    w(1, "GLOBAL_AUTO -1")
    w(1, f"TEMPO {_fmt(bpm)} 4 4 0")
    w(1, "PLAYRATE 1 0 0.25 4")
    w(1, "SELECTION 0 0")
    w(1, "SELECTION2 0 0")
    w(1, "MASTERAUTOMODE 0")
    w(1, "MASTERTRACKHEIGHT 0 0")
    w(1, "MASTERPEAKCOL 16576")
    w(1, "MASTERMUTESOLO 0")
    w(1, "MASTER_NCH 2 2")
    w(1, "MASTER_VOLUME 1 0 -1 -1 1")
    w(1, "MASTER_FX 1")
    w(1, "MASTER_SEL 0")

    # ── Markers and regions ───────────────────────────────────────────────────
    _write_markers_and_regions(w, tracks)

    # ── Tracks ────────────────────────────────────────────────────────────────
    for ti, track in enumerate(tracks):
        tc = _reaper_color(TRACK_COLORS[ti % len(TRACK_COLORS)])
        track_guid = _guid()
        w(1, f"<TRACK {track_guid}")
        w(2, f"NAME {_quote(track.name)}")
        w(2, f"PEAKCOL {tc}")
        w(2, "BEAT -1")
        w(2, "AUTOMODE 0")
        w(2, "VOLPAN 1 0 -1 -1 1")
        w(2, "MUTESOLO 0 0 0")
        w(2, "IPHASE 0")
        w(2, "PLAYOFFS 0 1")
        w(2, "ISBUS 0 0")
        w(2, "BUSCOMP 0 0 0 0 0")
        w(2, "SHOWINMIX 1 0.6667 0.5 1 0.5 0 0 0 0")
        w(2, "FIXEDLANES 9 0 0 0 0")
        w(2, "LANEREC -1 -1 -1 0")
        w(2, "SEL 0")
        w(2, "REC 0 0 0 0 0 0 0 0")
        w(2, "VU 2")
        w(2, "TRACKHEIGHT 80 0 0 0 0 0 0")
        w(2, "INQ 0 0 0 0.5 100 0 0 100")
        w(2, "NCHAN 2")
        w(2, "FX 1")
        w(2, f"TRACKID {track_guid}")
        w(2, "PERF 0")
        w(2, "MIDIOUT -1")
        w(2, "MAINSEND 1 0")

        for item in track.items:
            _write_item(w, item)

        w(1, ">")  # end TRACK

    w(0, ">")  # end REAPER_PROJECT
    return "\n".join(lines) + "\n"


def _write_markers_and_regions(w, tracks: List[TrackDef]):
    """
    Write MARKER lines for regions (output_name) and plain markers (row_index).

    Verified format from a real hand-crafted RPP:

      Region start:  MARKER id pos  name  1 0 1 R {guid} 0 1
      Region end:    MARKER id end  ""    1                     (5 fields only)
      Plain marker:  MARKER id pos  name  0 0 1 R {guid} 0 2

    Names are unquoted unless they contain spaces.
    """
    source_items = next((t.items for t in tracks if t.items), [])
    if not source_items:
        return

    n = len(source_items)
    for i, item in enumerate(source_items):
        pos      = item.timeline_pos
        end      = item.timeline_pos + item.length
        rgn_id   = i + 1
        mkr_id   = n + i + 1
        rgn_name = _marker_name(item.output_name or "")
        mkr_name = _marker_name(item.row_index or "")
        rgn_guid = _guid()

        # Region start — color=1, last field=1
        w(1, f"MARKER {rgn_id} {_fmt(pos)} {rgn_name} 1 0 1 R {rgn_guid} 0 1")
        # Region end — short form: id, pos, empty name, color=1
        w(1, f'MARKER {rgn_id} {_fmt(end)} "" 1')
        # Plain marker at region start — color=0, last field=2
        if mkr_name:
            mkr_guid = _guid()
            w(1, f"MARKER {mkr_id} {_fmt(pos)} {mkr_name} 0 0 1 R {mkr_guid} 0 2")


def _write_item(w, item: ItemDef):
    """
    Write a <ITEM> block matching REAPER 7.64 structure.

    - NAME is blank (" ") — identity comes from the enclosing region
    - <NOTES> block (before NAME) carries the line_text
    - SOFFS at item level (not inside <TAKE>)
    """
    w(2, "<ITEM")
    w(3, f"POSITION {_fmt(item.timeline_pos)}")
    w(3, "SNAPOFFS 0")
    w(3, f"LENGTH {_fmt(item.length)}")
    w(3, "LOOP 0")
    w(3, "ALLTAKES 0")
    w(3, "FADEIN 5 0 0 5 0 0 0")
    w(3, "FADEOUT 5 0 0 5 0 0 0")
    w(3, "MUTE 0 0")
    w(3, "SEL 0")
    w(3, f"IGUID {_guid()}")
    w(3, f"IID {abs(hash(item.source_path + str(item.timeline_pos))) % 100000}")
    # <NOTES> block — each line prefixed with "| "
    if item.note:
        w(3, "<NOTES")
        for line in item.note.splitlines():
            w(4, f"| {line}")
        w(3, ">")
    w(3, 'NAME " "')
    w(3, "VOLPAN 1 0 1 -1")
    w(3, f"SOFFS {_fmt(item.source_offset)}")
    w(3, "PLAYRATE 1 0 0 -1 0 0.0025")
    w(3, "CHANMODE 0")
    w(3, f"GUID {_guid()}")
    # Source block
    ext = os.path.splitext(item.source_path)[1].upper().lstrip(".")
    src_type = "MP3" if ext == "MP3" else "WAVE"
    w(3, f"<SOURCE {src_type}")
    w(4, f"FILE {_quote(item.source_path)}")
    w(3, ">")  # end SOURCE
    w(2, ">")  # end ITEM
