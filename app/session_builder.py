"""
session_builder.py

Takes:
  - rows          from spreadsheet (index, output_name, line_text)
  - file_groups   {index → {4060: path, 4061: path, 416: path}}
  - transcriptions {index → (source_offset, length)}  ← from Whisper or manual

And builds the TrackDef / ItemDef structure for rpp_writer.build_rpp().
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from .rpp_writer import TrackDef, ItemDef, build_rpp

GAP_SECONDS = 1.0  # silence between consecutive lines on the timeline


def build_session(
    rows: List[Dict],
    file_groups: Dict[str, Dict],   # index → {4060/4061/416: path or None}
    cuts: Dict[str, Tuple[float, float]],  # index → (source_offset, length)
    output_path: str,
    project_name: str = "Session",
) -> str:
    """
    Assemble TrackDef objects and write the RPP file.
    Returns the path of the written file.
    """
    tracks = [
        TrackDef(name="4060"),
        TrackDef(name="4061"),
        TrackDef(name="416"),
    ]
    mic_keys = ["4060", "4061", "416"]

    timeline_pos = 0.0

    for row in rows:
        idx = row["index"]
        group = file_groups.get(idx, {})
        soffs, length = cuts.get(idx, (0.0, None))

        # Fall back: if no cut info, use the full file duration
        # (rpp_writer will still reference the file correctly with SOFFS=0)
        if length is None or length <= 0:
            # Try to get duration from first available file
            for mk in mic_keys:
                fp = group.get(mk)
                if fp:
                    dur = _audio_duration(fp)
                    if dur:
                        length = dur
                        break
            if not length:
                length = 5.0  # safe fallback

        for ti, mk in enumerate(mic_keys):
            src = group.get(mk)
            if not src:
                continue  # no file for this mic variant
            item = ItemDef(
                track_idx=ti,
                source_path=src,
                source_offset=soffs,
                length=length,
                timeline_pos=timeline_pos,
                output_name=row.get("output_name") or f"Line_{idx}",
                row_index=str(row.get("base_index") or "").strip() or "NO SELECT",
                note=row.get("line_text") or "",
            )
            tracks[ti].items.append(item)

        timeline_pos += length + GAP_SECONDS

    rpp_text = build_rpp(tracks, project_name=project_name)

    with open(output_path, "wb") as f:
        f.write(rpp_text.replace("\n", "\r\n").encode("utf-8"))

    return output_path


def _audio_duration(path: str) -> Optional[float]:
    """Quick duration read without loading full audio — uses wave or soundfile."""
    import os
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".wav":
            import wave
            with wave.open(path, "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        else:
            # Try soundfile as fallback
            import soundfile as sf
            info = sf.info(path)
            return info.duration
    except Exception:
        return None
