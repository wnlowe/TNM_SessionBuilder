"""
Unit tests for the AAF session building path in app.session_builder:
  - _find_take_clip
  - _find_overlapping_clips
  - build_session_aaf
"""
import os
import pytest

from app.aaf_parser import AAFClip, AAFTrack, AAFSession
from app.aligner import AlignmentResult
from app.session_builder import (
    build_session_aaf,
    _find_take_clip,
    _find_overlapping_clips,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_clip(track_name, source_file, source_in, source_out, timeline_pos,
              clip_id=None):
    cid = clip_id or f"{track_name}__{source_in}"
    return AAFClip(
        clip_id=cid,
        track_name=track_name,
        source_file=source_file,
        source_in=source_in,
        source_out=source_out,
        timeline_pos=timeline_pos,
    )


def make_ar(row_index, source_offset, length, session_time_start,
            output_name="Line", line_text="text"):
    ar = AlignmentResult(
        row_index    = row_index,
        output_name  = output_name,
        line_text    = line_text,
        matched_text = line_text,
        source_offset= source_offset,
        length       = length,
        confidence   = 4,
        needs_review = False,
    )
    ar.session_time_start = session_time_start
    ar.session_time_end   = session_time_start + length
    return ar


def make_session(track_clips):
    """track_clips: list of (track_name, role, [AAFClip, ...])"""
    tracks = []
    for name, role, clips in track_clips:
        tracks.append(AAFTrack(name=name, clips=clips, suggested_role=role))
    return AAFSession(tracks=tracks, source_path="test.aaf")


# ── _find_take_clip ───────────────────────────────────────────────────────────

class TestFindTakeClip:
    def test_anchor_inside_clip(self):
        clip = make_clip("4060", "/a.wav", 0.0, 10.0, 100.0)
        result = _find_take_clip([clip], anchor=102.0, line_end=104.0)
        assert result is clip

    def test_anchor_at_start(self):
        clip = make_clip("4060", "/a.wav", 0.0, 5.0, 10.0)
        result = _find_take_clip([clip], anchor=10.0, line_end=12.0)
        assert result is clip

    def test_anchor_at_end_exclusive(self):
        # anchor == clip end → should NOT match (window is half-open)
        clip = make_clip("4060", "/a.wav", 0.0, 5.0, 10.0)  # clip ends at 15.0
        result = _find_take_clip([clip], anchor=15.0, line_end=17.0)
        # Fallback: nearest clip returned
        assert result is clip  # fallback by nearest distance

    def test_picks_first_matching(self):
        clip_a = make_clip("4060", "/a.wav", 0.0, 5.0, 100.0)
        clip_b = make_clip("4060", "/b.wav", 0.0, 5.0, 110.0)
        result = _find_take_clip([clip_a, clip_b], anchor=101.0, line_end=103.0)
        assert result is clip_a

    def test_empty_list_returns_none(self):
        assert _find_take_clip([], anchor=0.0, line_end=1.0) is None

    def test_fallback_when_no_exact_match(self):
        clip = make_clip("4060", "/a.wav", 0.0, 5.0, 50.0)  # window 50–55
        # anchor=70 is outside → fallback returns nearest
        result = _find_take_clip([clip], anchor=70.0, line_end=72.0)
        assert result is clip


# ── _find_overlapping_clips ───────────────────────────────────────────────────

class TestFindOverlappingClips:
    def test_full_overlap(self):
        clip = make_clip("short", "/s.wav", 0.0, 2.0, 10.0)  # session 10–12
        result = _find_overlapping_clips([clip], anchor=9.0, line_end=13.0)
        assert clip in result

    def test_clip_starts_inside_line(self):
        clip = make_clip("short", "/s.wav", 0.0, 2.0, 11.0)  # session 11–13
        result = _find_overlapping_clips([clip], anchor=10.0, line_end=12.0)
        assert clip in result

    def test_clip_ends_inside_line(self):
        clip = make_clip("short", "/s.wav", 0.0, 2.0, 9.0)  # session 9–11
        result = _find_overlapping_clips([clip], anchor=10.0, line_end=12.0)
        assert clip in result

    def test_clip_entirely_before_line(self):
        clip = make_clip("short", "/s.wav", 0.0, 2.0, 5.0)  # session 5–7
        result = _find_overlapping_clips([clip], anchor=10.0, line_end=12.0)
        assert clip not in result

    def test_clip_entirely_after_line(self):
        clip = make_clip("short", "/s.wav", 0.0, 2.0, 20.0)  # session 20–22
        result = _find_overlapping_clips([clip], anchor=10.0, line_end=12.0)
        assert clip not in result

    def test_multiple_overlapping(self):
        a = make_clip("short", "/a.wav", 0.0, 2.0, 10.0)
        b = make_clip("short", "/b.wav", 0.0, 1.5, 11.0)
        c = make_clip("short", "/c.wav", 0.0, 2.0, 20.0)  # doesn't overlap
        result = _find_overlapping_clips([a, b, c], anchor=10.0, line_end=13.0)
        assert a in result
        assert b in result
        assert c not in result

    def test_empty_list(self):
        result = _find_overlapping_clips([], anchor=0.0, line_end=5.0)
        assert result == []


# ── AlignmentResult new fields ────────────────────────────────────────────────

class TestAlignmentResultSessionFields:
    def test_defaults_to_zero(self):
        ar = AlignmentResult(
            row_index="001", output_name="L", line_text="x", matched_text="x"
        )
        assert ar.session_time_start == 0.0
        assert ar.session_time_end   == 0.0

    def test_settable(self):
        ar = AlignmentResult(
            row_index="001", output_name="L", line_text="x", matched_text="x",
            session_time_start=30.0, session_time_end=32.5,
        )
        assert ar.session_time_start == 30.0
        assert ar.session_time_end   == 32.5


# ── build_session_aaf ─────────────────────────────────────────────────────────

class TestBuildSessionAaf:
    def _minimal_session(self):
        """One 4060 clip, one 4061 clip, no short clips."""
        clips_4060 = [make_clip("4060", "/audio/take.wav", 0.0, 60.0, 0.0)]
        clips_4061 = [make_clip("4061", "/audio/take.wav", 0.0, 60.0, 0.0)]
        return make_session([
            ("4060 Takes", "4060", clips_4060),
            ("4061 Takes", "4061", clips_4061),
        ])

    def _two_row_aaf(self):
        """Two separate source files, one for each row."""
        clips_4060 = [
            make_clip("4060", "/audio/file1.wav", 0.0, 30.0, 0.0),
            make_clip("4060", "/audio/file2.wav", 0.0, 20.0, 35.0),
        ]
        return make_session([
            ("4060 Takes", "4060", clips_4060),
        ])

    def test_writes_rpp_file(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        session = self._minimal_session()
        ar = make_ar("001", source_offset=5.0, length=3.0,
                     session_time_start=5.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "Line_001", "line_text": "hello"}]
        track_roles = {"4060 Takes": "4060", "4061 Takes": "4061"}

        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session, track_roles=track_roles,
                          output_path=out)
        assert os.path.isfile(out)

    def test_rpp_contains_reaper_project(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        session = self._minimal_session()
        ar = make_ar("001", 5.0, 3.0, 5.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "Line_001", "line_text": "hi"}]
        track_roles = {"4060 Takes": "4060", "4061 Takes": "4061"}

        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session, track_roles=track_roles,
                          output_path=out)
        content = open(out).read()
        assert "<REAPER_PROJECT" in content

    def test_three_long_take_tracks_always_created(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips = [make_clip("4060", "/a.wav", 0.0, 30.0, 0.0)]
        session = make_session([("4060", "4060", clips)])
        ar = make_ar("001", 2.0, 5.0, 2.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session, track_roles={"4060": "4060"},
                          output_path=out)
        content = open(out).read()
        assert '"4060"' in content
        assert '"4061"' in content
        assert '"416"'  in content

    def test_short_clips_track_added_when_present(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips_4060 = [make_clip("4060", "/a.wav", 0.0, 30.0, 0.0)]
        clips_short = [make_clip("short", "/a.wav", 5.0, 8.0, 5.0)]
        session = make_session([
            ("4060 Takes", "4060", clips_4060),
            ("Short",      "short", clips_short),
        ])
        ar = make_ar("001", 5.0, 3.0, 5.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060 Takes": "4060", "Short": "short"},
                          output_path=out)
        content = open(out).read()
        assert "Short Clips" in content

    def test_no_short_clips_track_when_no_short_role(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        session = self._minimal_session()
        ar = make_ar("001", 5.0, 3.0, 5.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060 Takes": "4060", "4061 Takes": "4061"},
                          output_path=out)
        content = open(out).read()
        assert "Short Clips" not in content

    def test_source_offset_written_correctly(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips_4060 = [make_clip("4060", "/a.wav", 0.0, 60.0, 0.0)]
        session = make_session([("4060", "4060", clips_4060)])
        ar = make_ar("001", source_offset=7.25, length=2.5,
                     session_time_start=7.25)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060": "4060"},
                          output_path=out)
        content = open(out).read()
        assert "SOFFS 7.25" in content

    def test_skipped_rows_excluded(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips_4060 = [make_clip("4060", "/a.wav", 0.0, 60.0, 0.0)]
        session = make_session([("4060", "4060", clips_4060)])
        ar = make_ar("001", 5.0, 3.0, 5.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "Line_001", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060": "4060"},
                          output_path=out,
                          skipped_rows={"001"})
        content = open(out).read()
        # Item source file should not appear — row was skipped
        assert "/a.wav" not in content

    def test_short_clip_relative_offset_in_rpp(self, tmp_path):
        """
        Short clip that starts 1.5s into the line should have
        timeline_pos = rpp_line_start + 1.5 in REAPER.
        """
        out = str(tmp_path / "out.rpp")
        # Line starts at session time 10.0, length 5.0 → session end 15.0
        clips_4060  = [make_clip("4060",  "/a.wav", 10.0, 20.0, 10.0)]
        clips_short = [make_clip("short", "/a.wav",  0.0,  2.0, 11.5)]  # 1.5s in
        session = make_session([
            ("4060",  "4060",  clips_4060),
            ("Short", "short", clips_short),
        ])
        ar = make_ar("001", source_offset=10.0, length=5.0,
                     session_time_start=10.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060": "4060", "Short": "short"},
                          output_path=out)
        content = open(out).read()
        # Short clip POSITION should be 1.5 (line_rpp_pos=0.0 + rel_offset=1.5)
        assert "POSITION 1.5" in content

    def test_two_rows_sequential_positions(self, tmp_path):
        """Second row's REAPER position must come after first row + gap."""
        out = str(tmp_path / "out.rpp")
        clips = [
            make_clip("4060", "/a.wav", 0.0, 30.0, 0.0),
            make_clip("4060", "/b.wav", 0.0, 20.0, 35.0),
        ]
        session = make_session([("4060", "4060", clips)])
        ar1 = make_ar("001", source_offset=1.0, length=3.0,
                      session_time_start=1.0)
        ar2 = make_ar("002", source_offset=2.0, length=4.0,
                      session_time_start=37.0)
        rows = [
            {"index": "001", "base_index": "001",
             "output_name": "L1", "line_text": "line 1"},
            {"index": "002", "base_index": "002",
             "output_name": "L2", "line_text": "line 2"},
        ]
        build_session_aaf(rows=rows,
                          alignments={"001": ar1, "002": ar2},
                          aaf_session=session,
                          track_roles={"4060": "4060"},
                          output_path=out)
        content = open(out).read()
        # Row 1: POSITION 0.0; Row 2: POSITION 3.0+1.0=4.0
        assert "POSITION 0" in content
        assert "POSITION 4" in content

    def test_row_without_alignment_skipped(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips = [make_clip("4060", "/a.wav", 0.0, 30.0, 0.0)]
        session = make_session([("4060", "4060", clips)])
        rows = [
            {"index": "001", "base_index": "001",
             "output_name": "L1", "line_text": "found"},
            {"index": "002", "base_index": "002",
             "output_name": "L2", "line_text": "not found"},
        ]
        ar = make_ar("001", 1.0, 2.0, 1.0)
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060": "4060"},
                          output_path=out)
        content = open(out).read()
        assert "L1" in content
        assert "L2" not in content

    def test_returns_output_path(self, tmp_path):
        out = str(tmp_path / "out.rpp")
        clips = [make_clip("4060", "/a.wav", 0.0, 30.0, 0.0)]
        session = make_session([("4060", "4060", clips)])
        ar = make_ar("001", 1.0, 2.0, 1.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        result = build_session_aaf(rows=rows, alignments={"001": ar},
                                   aaf_session=session,
                                   track_roles={"4060": "4060"},
                                   output_path=out)
        assert result == out

    def test_clip_without_source_file_skipped(self, tmp_path):
        """Clips with empty source_file should not produce items."""
        out = str(tmp_path / "out.rpp")
        clips = [make_clip("4060", "", 0.0, 30.0, 0.0)]  # no media
        session = make_session([("4060", "4060", clips)])
        ar = make_ar("001", 1.0, 2.0, 1.0)
        rows = [{"index": "001", "base_index": "001",
                 "output_name": "L", "line_text": "hi"}]
        build_session_aaf(rows=rows, alignments={"001": ar},
                          aaf_session=session,
                          track_roles={"4060": "4060"},
                          output_path=out)
        content = open(out).read()
        # No FILE entry for an empty source
        assert "FILE" not in content
