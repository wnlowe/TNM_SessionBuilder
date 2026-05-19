"""
Unit tests for app.aaf_parser

parse_aaf() requires the `aaf2` package at runtime, so the integration-level
tests mock it out. The pure-Python helpers (_suggest_role, _uri_to_path, etc.)
are tested directly without any mocking.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.aaf_parser import (
    AAFClip, AAFTrack, AAFSession,
    _suggest_role, _uri_to_path, _iter_components,
    _component_length, _component_start, _is_source_clip,
    parse_aaf,
)


# ── Data class sanity ─────────────────────────────────────────────────────────

class TestAAFClip:
    def test_duration(self):
        clip = AAFClip("id", "track", "/a.wav", 1.0, 4.5, 10.0)
        assert clip.duration == pytest.approx(3.5)

    def test_duration_zero_if_out_le_in(self):
        clip = AAFClip("id", "track", "/a.wav", 5.0, 3.0, 10.0)
        assert clip.duration == 0.0

    def test_fields(self):
        clip = AAFClip("id1", "4060", "/x.wav", 0.0, 2.0, 30.0)
        assert clip.clip_id == "id1"
        assert clip.track_name == "4060"
        assert clip.source_file == "/x.wav"
        assert clip.source_in == 0.0
        assert clip.source_out == 2.0
        assert clip.timeline_pos == 30.0


class TestAAFTrack:
    def test_default_clips(self):
        t = AAFTrack(name="MyTrack")
        assert t.clips == []
        assert t.suggested_role == "unknown"


class TestAAFSession:
    def test_default_missing_media(self):
        s = AAFSession(tracks=[], source_path="x.aaf")
        assert s.missing_media == []


# ── _suggest_role ─────────────────────────────────────────────────────────────

class TestSuggestRole:
    def test_4060_in_name(self):
        assert _suggest_role("DX 4060 Takes") == "4060"

    def test_4061_in_name(self):
        assert _suggest_role("4061") == "4061"

    def test_416_in_name(self):
        assert _suggest_role("Track-416") == "416"

    def test_short_keyword(self):
        assert _suggest_role("Short Takes") == "short"

    def test_edit_keyword(self):
        assert _suggest_role("Edited Lines") == "short"

    def test_cut_keyword(self):
        assert _suggest_role("cut_takes") == "short"

    def test_clip_keyword(self):
        assert _suggest_role("clip_track") == "short"

    def test_unknown(self):
        assert _suggest_role("FX Bus") == "unknown"

    def test_case_insensitive(self):
        assert _suggest_role("TRACK_4060_MAIN") == "4060"
        assert _suggest_role("SHORT_V2") == "short"

    def test_416_not_confused_with_4160(self):
        # "4160" contains "416" — still matches
        assert _suggest_role("4160 takes") == "416"

    def test_4060_wins_over_short_keyword(self):
        # "4060 short" — 4060 is checked first
        assert _suggest_role("4060 short takes") == "4060"


# ── _uri_to_path ──────────────────────────────────────────────────────────────

class TestUriToPath:
    def test_file_uri_unix(self):
        result = _uri_to_path("file:///home/user/audio/take.wav")
        assert result == "/home/user/audio/take.wav"

    def test_file_uri_with_spaces(self):
        result = _uri_to_path("file:///home/user/my%20audio/take.wav")
        assert "my audio" in result

    def test_plain_path_unchanged(self):
        result = _uri_to_path("/some/plain/path.wav")
        assert result == "/some/plain/path.wav"

    def test_uppercase_FILE(self):
        result = _uri_to_path("FILE:///audio/file.wav")
        assert result == "/audio/file.wav"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows path only")
    def test_file_uri_windows(self):
        result = _uri_to_path("file:///C:/Audio/take.wav")
        assert result == "C:/Audio/take.wav"
        assert not result.startswith("/")


# ── _iter_components ──────────────────────────────────────────────────────────

class TestIterComponents:
    def test_sequence_with_components(self):
        comp_a = MagicMock()
        comp_b = MagicMock()
        seq = MagicMock()
        seq.components = [comp_a, comp_b]
        result = _iter_components(seq)
        assert result == [comp_a, comp_b]

    def test_bare_clip_no_components(self):
        bare = MagicMock(spec=[])  # no 'components' attribute
        result = _iter_components(bare)
        assert result == [bare]

    def test_empty_sequence(self):
        seq = MagicMock()
        seq.components = []
        assert _iter_components(seq) == []


# ── _component_length / _component_start ─────────────────────────────────────

class TestComponentHelpers:
    def test_length_normal(self):
        comp = MagicMock()
        comp.length = 48000
        assert _component_length(comp) == 48000

    def test_length_exception_returns_zero(self):
        # A plain object without a .length attribute raises AttributeError,
        # which _component_length should catch and return 0.
        class NoLength:
            pass
        assert _component_length(NoLength()) == 0

    def test_start_normal(self):
        comp = MagicMock()
        comp.start = 24000
        assert _component_start(comp) == 24000

    def test_start_exception_returns_zero(self):
        class NoStart:
            pass
        assert _component_start(NoStart()) == 0


# ── _is_source_clip ───────────────────────────────────────────────────────────

class TestIsSourceClip:
    def _make_aaf2_module(self):
        """Build a minimal fake aaf2 module with a SourceClip class."""
        mod = types.ModuleType("aaf2")
        comps = types.ModuleType("aaf2.components")

        class SourceClip:
            pass

        comps.SourceClip = SourceClip
        mod.components = comps
        return mod, SourceClip

    def test_returns_true_for_source_clip(self):
        mod, SourceClip = self._make_aaf2_module()
        obj = SourceClip()
        assert _is_source_clip(obj, mod) is True

    def test_returns_false_for_other(self):
        mod, _ = self._make_aaf2_module()

        class Filler:
            pass

        assert _is_source_clip(Filler(), mod) is False

    def test_fallback_class_name(self):
        """If isinstance fails, falls back to checking __name__."""
        mod = MagicMock()
        mod.components.SourceClip = None  # will raise in isinstance

        class FakeClip:
            pass
        FakeClip.__name__ = "SourceClip"

        # The real _is_source_clip catches the exception and uses __name__
        result = _is_source_clip(FakeClip(), mod)
        assert result is True


# ── parse_aaf (mocked) ────────────────────────────────────────────────────────

def _make_fake_aaf2(clips_per_track):
    """
    Build a fake `aaf2` module structure that parse_aaf() can traverse.

    clips_per_track: list of dicts
      [{"slot_name": str, "edit_rate": int, "origin": int,
        "clips": [{"length": int, "start": int, "source_file": str}]}]
    """
    import types as _types

    aaf2_mod = _types.ModuleType("aaf2")

    # Minimal class stubs
    class CompositionMob:
        pass
    class TimelineMobSlot:
        pass
    class SourceClip:
        pass

    mobs_mod = _types.ModuleType("aaf2.mobs")
    mobs_mod.CompositionMob = CompositionMob
    slots_mod = _types.ModuleType("aaf2.mobslots")
    slots_mod.TimelineMobSlot = TimelineMobSlot
    comps_mod = _types.ModuleType("aaf2.components")
    comps_mod.SourceClip = SourceClip

    aaf2_mod.mobs = mobs_mod
    aaf2_mod.mobslots = slots_mod
    aaf2_mod.components = comps_mod

    # Build fake mobs/slots/clips
    fake_slots = []
    for track_spec in clips_per_track:
        slot = MagicMock(spec=TimelineMobSlot)
        slot.name = track_spec["slot_name"]
        slot.edit_rate = MagicMock()
        slot.edit_rate.__float__ = lambda self: float(track_spec["edit_rate"])
        slot.origin = track_spec.get("origin", 0)
        slot.media_kind = track_spec.get("media_kind", "Sound")

        # Build components from spec
        components = []
        for clip_spec in track_spec["clips"]:
            comp = MagicMock(spec=SourceClip)
            comp.length = clip_spec["length"]
            comp.start  = clip_spec["start"]

            # Chain: comp.mob → master_mob; master_mob.slots → [inner_slot]
            # inner_slot.segment.components → [inner_clip]
            # inner_clip.mob → source_mob
            # source_mob.descriptor.locator → [locator]
            # locator["URLString"].value → uri

            source_file = clip_spec.get("source_file", "")
            if source_file:
                locator = MagicMock()
                locator.__getitem__ = lambda self, k: MagicMock(value=f"file://{source_file}")
                source_mob = MagicMock()
                source_mob.descriptor.locator = [locator]
                type(source_mob).__name__ = "SourceMob"

                inner_clip = MagicMock()
                inner_clip.mob = source_mob
                type(inner_clip).__name__ = "SourceClip"

                inner_seg = MagicMock()
                inner_seg.components = [inner_clip]

                inner_slot = MagicMock()
                inner_slot.segment = inner_seg

                master_mob = MagicMock()
                master_mob.slots = [inner_slot]
                comp.mob = master_mob
            else:
                comp.mob = None

            components.append(comp)

        seq = MagicMock()
        seq.components = components
        slot.segment = seq
        fake_slots.append(slot)

    comp_mob = MagicMock(spec=CompositionMob)
    comp_mob.slots = fake_slots

    # open() context manager
    fake_file = MagicMock()
    fake_file.content.mobs = [comp_mob]
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=fake_file)
    ctx.__exit__ = MagicMock(return_value=False)
    aaf2_mod.open = MagicMock(return_value=ctx)

    return aaf2_mod


class TestParseAaf:
    def _parse_with_mock(self, track_specs, tmp_path):
        aaf_path = str(tmp_path / "session.aaf")
        # Create a dummy file so os.path.isfile passes initial checks
        open(aaf_path, "w").close()

        fake_aaf2 = _make_fake_aaf2(track_specs)
        with patch.dict("sys.modules", {
            "aaf2": fake_aaf2,
            "aaf2.mobs": fake_aaf2.mobs,
            "aaf2.mobslots": fake_aaf2.mobslots,
            "aaf2.components": fake_aaf2.components,
        }):
            return parse_aaf(aaf_path)

    def test_returns_aaf_session(self, tmp_path):
        specs = [{"slot_name": "4060 Takes", "edit_rate": 48000, "clips": [
            {"length": 96000, "start": 0, "source_file": "/audio/take1.wav"},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        assert isinstance(result, AAFSession)

    def test_track_count(self, tmp_path):
        specs = [
            {"slot_name": "4060", "edit_rate": 48000, "clips": [
                {"length": 48000, "start": 0, "source_file": "/a.wav"},
            ]},
            {"slot_name": "4061", "edit_rate": 48000, "clips": [
                {"length": 48000, "start": 0, "source_file": "/b.wav"},
            ]},
        ]
        result = self._parse_with_mock(specs, tmp_path)
        assert len(result.tracks) == 2

    def test_clip_count(self, tmp_path):
        specs = [{"slot_name": "4060", "edit_rate": 48000, "clips": [
            {"length": 48000, "start": 0, "source_file": "/a.wav"},
            {"length": 48000, "start": 48000, "source_file": "/a.wav"},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        assert len(result.tracks[0].clips) == 2

    def test_timeline_pos_seconds(self, tmp_path):
        # Two clips at 48000 Hz; first at origin=0 (0s), second at 96000 edit units (2s)
        specs = [{"slot_name": "4060", "edit_rate": 48000, "origin": 0, "clips": [
            {"length": 48000, "start": 0, "source_file": "/a.wav"},
            {"length": 48000, "start": 0, "source_file": "/a.wav"},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        clips = result.tracks[0].clips
        assert clips[0].timeline_pos == pytest.approx(0.0)
        assert clips[1].timeline_pos == pytest.approx(1.0)  # 48000/48000

    def test_source_in_seconds(self, tmp_path):
        specs = [{"slot_name": "4060", "edit_rate": 48000, "clips": [
            {"length": 24000, "start": 48000, "source_file": "/a.wav"},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        clip = result.tracks[0].clips[0]
        assert clip.source_in  == pytest.approx(1.0)   # 48000/48000
        assert clip.source_out == pytest.approx(1.5)   # (48000+24000)/48000

    def test_suggested_role_4060(self, tmp_path):
        specs = [{"slot_name": "DX 4060 Takes", "edit_rate": 48000, "clips": [
            {"length": 48000, "start": 0, "source_file": "/a.wav"},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        assert result.tracks[0].suggested_role == "4060"

    def test_skip_non_audio_slots(self, tmp_path):
        specs = [
            {"slot_name": "Video", "edit_rate": 25, "media_kind": "picture", "clips": [
                {"length": 100, "start": 0, "source_file": "/vid.mp4"},
            ]},
            {"slot_name": "4060", "edit_rate": 48000, "clips": [
                {"length": 48000, "start": 0, "source_file": "/a.wav"},
            ]},
        ]
        result = self._parse_with_mock(specs, tmp_path)
        # Only the audio track should appear
        assert len(result.tracks) == 1
        assert result.tracks[0].name == "4060"

    def test_no_composition_mob_raises(self, tmp_path):
        aaf_path = str(tmp_path / "bad.aaf")
        open(aaf_path, "w").close()

        fake_aaf2 = _make_fake_aaf2([])  # empty tracks
        # Override mobs to yield nothing CompositionMob-like
        fake_aaf2.open.return_value.__enter__.return_value.content.mobs = []

        with patch.dict("sys.modules", {
            "aaf2": fake_aaf2,
            "aaf2.mobs": fake_aaf2.mobs,
            "aaf2.mobslots": fake_aaf2.mobslots,
            "aaf2.components": fake_aaf2.components,
        }):
            with pytest.raises(RuntimeError, match="CompositionMob"):
                parse_aaf(aaf_path)

    def test_missing_media_collected(self, tmp_path):
        # source_file="" means _resolve_source_file returns ("", "")
        specs = [{"slot_name": "4060", "edit_rate": 48000, "clips": [
            {"length": 48000, "start": 0, "source_file": ""},
        ]}]
        result = self._parse_with_mock(specs, tmp_path)
        # Clip is still created but source_file is ""
        assert result.tracks[0].clips[0].source_file == ""
