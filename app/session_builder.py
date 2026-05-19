"""
session_builder.py

Takes:
  - rows          from spreadsheet (index, output_name, line_text)
  - file_groups   {index → {4060: path, 4061: path, 416: path}}
  - transcriptions {index → (source_offset, length)}  ← from Whisper or manual

And builds the TrackDef / ItemDef structure for rpp_writer.build_rpp().

For AAF-based sessions, use build_session_aaf() which places all clips
(long-take cuts and short pre-edited clips) using session-timeline positions.
"""

from __future__ import annotations
import os
import shutil
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from .rpp_writer import TrackDef, ItemDef, build_rpp

if TYPE_CHECKING:
    from .aaf_parser import AAFSession, AAFClip
    from .aligner import AlignmentResult

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

    _remap_and_copy(tracks, output_path)
    rpp_text = build_rpp(tracks, project_name=project_name)
    with open(output_path, "wb") as f:
        f.write(rpp_text.replace("\n", "\r\n").encode("utf-8"))
    return output_path


def _audio_duration(path: str) -> Optional[float]:
    """Quick duration read without loading full audio — uses wave or soundfile."""
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


def _build_media_path_map(source_files) -> Dict[str, str]:
    """
    Build original_path → relative "Media/<filename>" mapping.
    Same-basename collisions are resolved by appending _2, _3, etc.
    """
    used: Dict[str, int] = {}
    mapping: Dict[str, str] = {}
    for src in source_files:
        if not src or src in mapping:
            continue
        name, ext = os.path.splitext(os.path.basename(src))
        key = (name + ext).lower()
        if key not in used:
            used[key] = 0
            dest_name = name + ext
        else:
            used[key] += 1
            dest_name = f"{name}_{used[key]}{ext}"
        mapping[src] = os.path.join("Media", dest_name)
    return mapping


def _copy_media(path_map: Dict[str, str], output_dir: str) -> None:
    """Copy all mapped source files into <output_dir>/Media/."""
    os.makedirs(os.path.join(output_dir, "Media"), exist_ok=True)
    for src, rel_dest in path_map.items():
        if not os.path.isfile(src):
            continue
        dest = os.path.join(output_dir, rel_dest)
        if not os.path.isfile(dest):
            shutil.copy2(src, dest)


def _remap_and_copy(tracks: List[TrackDef], output_path: str) -> None:
    """Rewrite item source paths to Media/ and copy the files there."""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    all_sources = sorted({item.source_path for t in tracks for item in t.items if item.source_path})
    path_map = _build_media_path_map(all_sources)
    for track in tracks:
        for item in track.items:
            if item.source_path in path_map:
                item.source_path = path_map[item.source_path]
    _copy_media(path_map, output_dir)


# ── AAF-based session builder ─────────────────────────────────────────────────

def build_session_aaf(
    rows: List[Dict],
    alignments: Dict[str, "AlignmentResult"],
    aaf_session: "AAFSession",
    track_roles: Dict[str, str],          # track_name → "4060"|"4061"|"416"|"short"|"ignore"
    output_path: str,
    project_name: str = "Session",
    gap_seconds: float = GAP_SECONDS,
    skipped_rows: Optional[Set[str]] = None,
) -> str:
    """
    Build a REAPER .RPP from AAF session data.

    Long-take clips (roles 4060/4061/416) are trimmed to the exact aligned
    line boundaries (source_offset / length from AlignmentResult).

    Short clips are placed with their original relative offset from the line's
    session_time_start so that relative timing is preserved in REAPER.
    """
    if skipped_rows is None:
        skipped_rows = set()

    # Build role → clips index; short tracks kept separate to preserve their names
    role_clips: Dict[str, List["AAFClip"]] = {"4060": [], "4061": [], "416": []}
    short_tracks: List[Tuple[str, List["AAFClip"]]] = []  # (original_name, clips)
    for track in aaf_session.tracks:
        role = track_roles.get(track.name, "unknown")
        if role in role_clips:
            role_clips[role].extend(track.clips)
        elif role == "short":
            short_tracks.append((track.name, list(track.clips)))

    # Create output tracks: always 4060/4061/416; one TrackDef per short track
    tracks = [
        TrackDef(name="4060"),
        TrackDef(name="4061"),
        TrackDef(name="416"),
    ]
    short_track_defs: List[TrackDef] = []
    for track_name, _ in short_tracks:
        td = TrackDef(name=track_name)
        tracks.append(td)
        short_track_defs.append(td)

    rpp_pos = 0.0

    for row in rows:
        idx = row["index"]
        if idx in skipped_rows:
            continue
        ar = alignments.get(idx)
        if ar is None:
            continue

        anchor   = ar.session_time_start
        line_end = ar.session_time_end
        line_dur = max(0.01, line_end - anchor)
        out_name = row.get("output_name") or f"Line_{idx}"
        row_idx  = str(row.get("base_index") or "").strip() or "NO SELECT"
        note     = row.get("line_text") or ""

        # Long-take clips — one per mic role, trimmed to line boundaries
        for ti, role in enumerate(("4060", "4061", "416")):
            clip = _find_take_clip(role_clips[role], anchor, line_end)
            if clip and clip.source_file:
                tracks[ti].items.append(ItemDef(
                    track_idx    = ti,
                    source_path  = clip.source_file,
                    source_offset= ar.source_offset,
                    length       = ar.length,
                    timeline_pos = rpp_pos,
                    output_name  = out_name,
                    row_index    = row_idx,
                    note         = note,
                    clip_name    = clip.clip_name,
                ))

        # Short clips — one track per original Pro Tools track, relative timing preserved
        for short_td, (_, short_clips) in zip(short_track_defs, short_tracks):
            ti = tracks.index(short_td)
            for clip in _find_overlapping_clips(short_clips, anchor, line_end):
                if not clip.source_file:
                    continue
                rel_offset = clip.timeline_pos - anchor
                clip_len   = clip.source_out - clip.source_in
                short_td.items.append(ItemDef(
                    track_idx    = ti,
                    source_path  = clip.source_file,
                    source_offset= clip.source_in,
                    length       = clip_len,
                    timeline_pos = rpp_pos + rel_offset,
                    output_name  = out_name,
                    row_index    = row_idx,
                    note         = note,
                    clip_name    = clip.clip_name,
                ))

        rpp_pos += line_dur + gap_seconds

    _remap_and_copy(tracks, output_path)
    rpp_text = build_rpp(tracks, project_name=project_name)
    with open(output_path, "wb") as f:
        f.write(rpp_text.replace("\n", "\r\n").encode("utf-8"))
    return output_path


def _find_take_clip(clips: List["AAFClip"], anchor: float, line_end: float) -> Optional["AAFClip"]:
    """
    Return the first clip whose session window [timeline_pos, timeline_pos+duration]
    contains the anchor point. Prefers clips where source_in <= ar.source_offset.
    """
    for clip in clips:
        clip_end = clip.timeline_pos + clip.duration
        if clip.timeline_pos <= anchor < clip_end:
            return clip
    # Fallback: nearest clip by start distance
    if not clips:
        return None
    return min(clips, key=lambda c: abs(c.timeline_pos - anchor))


def _find_overlapping_clips(clips: List["AAFClip"], anchor: float,
                             line_end: float) -> List["AAFClip"]:
    """Return all clips whose session window overlaps [anchor, line_end]."""
    result = []
    for clip in clips:
        clip_end = clip.timeline_pos + clip.duration
        if clip.timeline_pos < line_end and clip_end > anchor:
            result.append(clip)
    return result
