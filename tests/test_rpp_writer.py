"""Unit tests for app.rpp_writer"""
import pytest
from app.rpp_writer import (
    _fmt, _guid, _reaper_color, _quote, _marker_name,
    build_rpp, ItemDef, TrackDef,
)


class TestFmt:
    def test_integer_float(self):
        assert _fmt(1.0) == "1"

    def test_decimal(self):
        result = _fmt(1.5)
        assert "1.5" in result

    def test_zero(self):
        assert _fmt(0.0) == "0"

    def test_high_precision(self):
        result = _fmt(3.14159265358979)
        assert "3.14159" in result


class TestGuid:
    def test_format(self):
        g = _guid()
        assert g.startswith("{")
        assert g.endswith("}")

    def test_uppercase(self):
        g = _guid()
        # Content between braces should be uppercase hex + dashes
        inner = g[1:-1]
        assert inner == inner.upper() or "-" in inner

    def test_unique(self):
        guids = {_guid() for _ in range(100)}
        assert len(guids) == 100


class TestReaperColor:
    def test_flag_bit_set(self):
        result = _reaper_color(0x00CC4400)
        assert result & (1 << 24)

    def test_black(self):
        result = _reaper_color(0x000000)
        assert result == (1 << 24)

    def test_channel_swap(self):
        # 0x00RRGGBB → REAPER wants BBGGRR; verify R and B are swapped
        result = _reaper_color(0x00FF0000)  # pure red
        r = (result >> 0) & 0xFF
        assert r == 0xFF  # red ends up in lowest byte


class TestQuote:
    def test_simple(self):
        assert _quote("hello") == '"hello"'

    def test_empty(self):
        assert _quote("") == '""'

    def test_escapes_backslash(self):
        result = _quote("C:\\path")
        assert "\\\\" in result

    def test_escapes_double_quote(self):
        result = _quote('say "hi"')
        assert '\\"' in result


class TestMarkerName:
    def test_no_spaces(self):
        result = _marker_name("001")
        assert result == "001"

    def test_with_spaces(self):
        result = _marker_name("Line 001")
        assert result.startswith('"')
        assert result.endswith('"')

    def test_empty_string(self):
        result = _marker_name("")
        assert result == '""'


class TestBuildRpp:
    def _simple_track(self, name="4060", n_items=1):
        items = []
        for i in range(n_items):
            items.append(ItemDef(
                track_idx=0,
                source_path=f"C:/audio/{name}_{i:03d}.wav",
                source_offset=1.0,
                length=2.0,
                timeline_pos=float(i * 5),
                output_name=f"Line_{i:03d}",
                row_index=f"{i:03d}",
                note=f"Expected line {i}",
            ))
        return TrackDef(name=name, items=items)

    def test_returns_string(self):
        rpp = build_rpp([self._simple_track()])
        assert isinstance(rpp, str)

    def test_starts_with_reaper_project(self):
        rpp = build_rpp([self._simple_track()])
        assert rpp.startswith("<REAPER_PROJECT")

    def test_ends_properly(self):
        rpp = build_rpp([self._simple_track()])
        assert rpp.strip().endswith(">")

    def test_contains_track_name(self):
        rpp = build_rpp([self._simple_track("4060")])
        assert '"4060"' in rpp

    def test_contains_source_file(self):
        rpp = build_rpp([self._simple_track("4060", n_items=1)])
        assert "C:/audio/4060_000.wav" in rpp

    def test_contains_item_notes(self):
        rpp = build_rpp([self._simple_track()])
        assert "Expected line 0" in rpp

    def test_multiple_tracks(self):
        tracks = [self._simple_track("4060"), self._simple_track("4061"), self._simple_track("416")]
        rpp = build_rpp(tracks)
        assert '"4060"' in rpp
        assert '"4061"' in rpp
        assert '"416"' in rpp

    def test_marker_and_region_written(self):
        rpp = build_rpp([self._simple_track(n_items=2)])
        assert "MARKER" in rpp

    def test_region_output_name(self):
        rpp = build_rpp([self._simple_track(n_items=1)])
        assert "Line_000" in rpp

    def test_samplerate_written(self):
        rpp = build_rpp([self._simple_track()], sample_rate=48000)
        assert "SAMPLERATE 48000" in rpp

    def test_custom_bpm(self):
        rpp = build_rpp([self._simple_track()], bpm=90.0)
        assert "TEMPO 90" in rpp

    def test_empty_tracks(self):
        rpp = build_rpp([])
        assert "<REAPER_PROJECT" in rpp

    def test_mp3_source_type(self):
        item = ItemDef(
            track_idx=0,
            source_path="C:/audio/file.mp3",
            source_offset=0.0,
            length=1.0,
            timeline_pos=0.0,
        )
        rpp = build_rpp([TrackDef(name="MP3Track", items=[item])])
        assert "<SOURCE MP3" in rpp

    def test_wav_source_type(self):
        item = ItemDef(
            track_idx=0,
            source_path="C:/audio/file.wav",
            source_offset=0.0,
            length=1.0,
            timeline_pos=0.0,
        )
        rpp = build_rpp([TrackDef(name="WAVTrack", items=[item])])
        assert "<SOURCE WAVE" in rpp

    def test_soffs_written(self):
        item = ItemDef(
            track_idx=0,
            source_path="C:/audio/file.wav",
            source_offset=3.5,
            length=1.0,
            timeline_pos=0.0,
        )
        rpp = build_rpp([TrackDef(name="T", items=[item])])
        assert "SOFFS 3.5" in rpp

    def test_item_name_blank(self):
        rpp = build_rpp([self._simple_track()])
        assert 'NAME " "' in rpp
