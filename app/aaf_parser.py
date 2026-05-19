"""
aaf_parser.py

Parses an AAF (Advanced Authoring Format) file exported from Pro Tools and
extracts track/clip information with session-timeline positions.

Package name on PyPI: pyaaf2
Import name:          aaf2

Each AAFClip carries:
  - timeline_pos  : absolute position in the session (seconds from session start)
  - source_in/out : in/out points in the source audio file (seconds)
  - source_file   : resolved absolute path to the media file

AAFTrack carries a suggested_role derived from the track name:
  "4060" | "4061" | "416" | "short" | "unknown"
"""

from __future__ import annotations
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import List


@dataclass
class AAFClip:
    clip_id:      str    # unique: f"{track_name}__{index}"
    track_name:   str
    source_file:  str    # resolved absolute path; "" if unresolvable
    source_in:    float  # file-local in-point (seconds)
    source_out:   float  # file-local out-point (seconds)
    timeline_pos: float  # session-timeline position (seconds)
    clip_name:    str = ""  # MasterMob name from AAF (Pro Tools clip/region name)

    @property
    def duration(self) -> float:
        return max(0.0, self.source_out - self.source_in)


@dataclass
class AAFTrack:
    name:           str
    clips:          List[AAFClip] = field(default_factory=list)
    suggested_role: str = "unknown"


@dataclass
class AAFSession:
    tracks:        List[AAFTrack]
    source_path:   str
    missing_media: List[str] = field(default_factory=list)


# ── Public entry point ────────────────────────────────────────────────────────

def parse_aaf(path: str) -> AAFSession:
    """
    Open an AAF file and return an AAFSession describing all audio tracks/clips.

    Raises RuntimeError on AAF structural errors; missing media is collected in
    AAFSession.missing_media rather than raised.
    """
    import aaf2
    import aaf2.mobs
    import aaf2.mobslots
    import aaf2.components

    tracks: List[AAFTrack] = []
    missing: List[str] = []
    aaf_dir = os.path.dirname(os.path.abspath(path))

    with aaf2.open(path, 'r') as f:
        comp_mob = None
        for mob in f.content.mobs:
            if isinstance(mob, aaf2.mobs.CompositionMob):
                comp_mob = mob
                break

        if comp_mob is None:
            raise RuntimeError("No CompositionMob found in AAF — is this a Pro Tools session export?")

        for slot in comp_mob.slots:
            if not isinstance(slot, aaf2.mobslots.TimelineMobSlot):
                continue
            # Only process audio slots
            try:
                mk = slot.media_kind
            except Exception:
                mk = ""
            if mk not in ("Sound", "sound", "SoundWithTimecode"):
                continue

            track_name = _slot_name(slot)
            edit_rate  = float(slot.edit_rate)
            try:
                origin = int(slot.origin)
            except Exception:
                origin = 0

            clips: List[AAFClip] = []
            seq_offset = 0  # running position in edit units

            segment = slot.segment
            components = _iter_components(segment)

            for comp in components:
                comp_len = _component_length(comp)
                source_clip = _unwrap_source_clip(comp, aaf2)
                if source_clip is not None:
                    timeline_pos = (seq_offset - origin) / edit_rate
                    source_in    = _component_start(source_clip) / edit_rate
                    source_out   = source_in + comp_len / edit_rate

                    src_file, unresolved = _resolve_source_file(source_clip, aaf_dir, f)
                    if unresolved and unresolved not in missing:
                        missing.append(unresolved)

                    clip = AAFClip(
                        clip_id      = f"{track_name}__{len(clips)}",
                        track_name   = track_name,
                        source_file  = src_file,
                        source_in    = source_in,
                        source_out   = source_out,
                        timeline_pos = timeline_pos,
                        clip_name    = _get_clip_name(source_clip),
                    )
                    clips.append(clip)

                seq_offset += comp_len

            if clips:
                tracks.append(AAFTrack(
                    name           = track_name,
                    clips          = clips,
                    suggested_role = _suggest_role(track_name),
                ))

    return AAFSession(tracks=tracks, source_path=path, missing_media=missing)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _suggest_role(name: str) -> str:
    n = name.lower()
    if "4060" in n:
        return "4060"
    if "4061" in n:
        return "4061"
    if "416" in n:
        return "416"
    for kw in ("short", "edit", "cut", "clip"):
        if kw in n:
            return "short"
    return "unknown"


def _slot_name(slot) -> str:
    """Extract slot/track name safely."""
    try:
        return str(slot.name) or f"Track_{slot.index}"
    except Exception:
        try:
            return f"Track_{slot.index}"
        except Exception:
            return "Track"


def _iter_components(segment):
    """
    Yield the direct child components of a Sequence (or yield the segment
    itself if it is a bare SourceClip rather than a Sequence).
    """
    try:
        # Sequence has a .components iterator
        return list(segment.components)
    except AttributeError:
        return [segment]


def _unwrap_source_clip(comp, aaf2_module):
    """Return the SourceClip inside comp, or None.

    Pro Tools wraps every clip in an OperationGroup (gain/automation);
    the real SourceClip lives in OperationGroup.segments[0].
    """
    try:
        if isinstance(comp, aaf2_module.components.SourceClip):
            return comp
        if type(comp).__name__ == "OperationGroup":
            for s in comp.segments:
                if isinstance(s, aaf2_module.components.SourceClip):
                    return s
    except Exception:
        pass
    return None


def _component_length(comp) -> int:
    """Return length in edit units (int)."""
    try:
        return int(comp.length)
    except Exception:
        return 0


def _component_start(comp) -> int:
    """Return the SourceClip's in-point in edit units."""
    try:
        return int(comp.start)
    except Exception:
        return 0


def _get_clip_name(source_clip) -> str:
    """Return the MasterMob name for a SourceClip — the Pro Tools clip/region name."""
    try:
        mob = source_clip.mob
        if mob is not None:
            name = str(mob.name or "").strip()
            if name:
                return name
    except Exception:
        pass
    return ""


def _resolve_source_file(source_clip, aaf_dir: str, aaf_file) -> tuple[str, str]:
    """
    Walk SourceClip → MasterMob → SourceMob → FileDescriptor → locator URL.

    Returns (resolved_path, unresolved_hint).
    resolved_path is "" if we could not find the file.
    unresolved_hint is the raw URI/path string when resolution failed, else "".
    """
    try:
        master_mob = source_clip.mob
        if master_mob is None:
            return "", ""

        # Walk master mob slots to find the SourceClip referencing the SourceMob
        source_mob = None
        for ms in master_mob.slots:
            try:
                seg = ms.segment
                inner_clips = _iter_components(seg)
                for ic in inner_clips:
                    if type(ic).__name__ == "SourceClip":
                        candidate = ic.mob
                        if candidate is not None and type(candidate).__name__ == "SourceMob":
                            source_mob = candidate
                            break
            except Exception:
                continue
            if source_mob is not None:
                break

        if source_mob is None:
            return "", ""

        desc = source_mob.descriptor
        locators = list(desc.locator) if desc.locator else []

        for loc in locators:
            try:
                uri = str(loc["URLString"].value)
                path = _uri_to_path(uri)
                if os.path.isfile(path):
                    return path, ""
                # Try just the basename relative to the AAF directory
                basename  = os.path.basename(path)
                candidate = os.path.join(aaf_dir, basename)
                if os.path.isfile(candidate):
                    return candidate, ""
                # Return the unresolved hint so GUI can warn
                return "", path or uri
            except Exception:
                continue

    except Exception:
        pass

    return "", ""


def _uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a local filesystem path."""
    if uri.startswith("file://") or uri.startswith("FILE://"):
        parsed = urllib.parse.urlparse(uri)
        path   = urllib.parse.unquote(parsed.path)
        # On Windows, file:///C:/foo → /C:/foo — strip leading slash
        if os.name == "nt" and len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    # Plain path (some Pro Tools versions omit the scheme)
    return uri
