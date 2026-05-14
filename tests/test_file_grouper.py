"""Unit tests for app.file_grouper"""
import os
import tempfile
import pytest
from app.file_grouper import scan_folder, groups_to_display, _sort_key, _PATTERN


class TestSortKey:
    def test_numeric_index(self):
        assert _sort_key("001") == (0, 1, "")
        assert _sort_key("42") == (0, 42, "")

    def test_numeric_sort_order(self):
        keys = [_sort_key(i) for i in ["003", "001", "010", "002"]]
        assert sorted(keys) == [_sort_key("001"), _sort_key("002"), _sort_key("003"), _sort_key("010")]

    def test_alphanumeric_index(self):
        k = _sort_key("AB1")
        assert k[0] == 1  # non-numeric goes in bucket 1

    def test_numeric_before_alpha(self):
        assert _sort_key("1") < _sort_key("A")


class TestPattern:
    def test_standard_match(self):
        assert _PATTERN.match("Session_4060_001.wav")
        assert _PATTERN.match("Session_4061_001.wav")
        assert _PATTERN.match("Session_416_001.wav")

    def test_take_suffix(self):
        m = _PATTERN.match("Base_4060_01.2.wav")
        assert m is not None
        assert m.group(3) == "01"

    def test_case_insensitive(self):
        assert _PATTERN.match("Session_4060_001.WAV")
        assert _PATTERN.match("session_4060_001.AIFF")

    def test_supported_extensions(self):
        for ext in ["wav", "aiff", "flac", "mp3"]:
            assert _PATTERN.match(f"Base_4060_01.{ext}")

    def test_no_match_wrong_variant(self):
        assert _PATTERN.match("Session_4062_001.wav") is None

    def test_no_match_missing_variant(self):
        assert _PATTERN.match("Session_001.wav") is None

    def test_complex_basename(self):
        m = _PATTERN.match("250722_TNM_Rickey_Cross_4060_01.1.wav")
        assert m is not None
        assert m.group(2) == "4060"
        assert m.group(3) == "01"


class TestScanFolder:
    def test_nonexistent_folder(self):
        groups, unmatched = scan_folder("/nonexistent/path/xyz")
        assert groups == []
        assert unmatched == []

    def test_empty_folder(self, tmp_path):
        groups, unmatched = scan_folder(str(tmp_path))
        assert groups == []
        assert unmatched == []

    def test_groups_by_index(self, tmp_path):
        for name in ["Sess_4060_001.wav", "Sess_4061_001.wav", "Sess_416_001.wav"]:
            (tmp_path / name).touch()
        groups, unmatched = scan_folder(str(tmp_path))
        assert len(groups) == 1
        assert groups[0]["index"] == "001"
        assert groups[0]["4060"] is not None
        assert groups[0]["4061"] is not None
        assert groups[0]["416"] is not None

    def test_partial_group(self, tmp_path):
        (tmp_path / "Sess_4060_002.wav").touch()
        groups, unmatched = scan_folder(str(tmp_path))
        assert len(groups) == 1
        assert groups[0]["4060"] is not None
        assert groups[0]["4061"] is None
        assert groups[0]["416"] is None

    def test_unmatched_audio_file(self, tmp_path):
        (tmp_path / "random_audio.wav").touch()
        groups, unmatched = scan_folder(str(tmp_path))
        assert groups == []
        assert len(unmatched) == 1

    def test_non_audio_ignored(self, tmp_path):
        (tmp_path / "notes.txt").touch()
        (tmp_path / "image.png").touch()
        groups, unmatched = scan_folder(str(tmp_path))
        assert groups == []
        assert unmatched == []

    def test_multiple_indices_sorted(self, tmp_path):
        for idx in ["010", "002", "001"]:
            (tmp_path / f"Sess_4060_{idx}.wav").touch()
        groups, _ = scan_folder(str(tmp_path))
        assert [g["index"] for g in groups] == ["001", "002", "010"]

    def test_groups_share_base(self, tmp_path):
        (tmp_path / "MyBase_4060_01.wav").touch()
        (tmp_path / "MyBase_4061_01.wav").touch()
        groups, _ = scan_folder(str(tmp_path))
        assert len(groups) == 1
        assert groups[0]["base"] == "MyBase"


class TestGroupsToDisplay:
    def _make_group(self, index, base, p4060=None, p4061=None, p416=None):
        return {"index": index, "base": base, "4060": p4060, "4061": p4061, "416": p416}

    def test_with_all_variants(self):
        g = self._make_group("001", "Base", "/a/Base_4060_001.wav", "/a/Base_4061_001.wav", "/a/Base_416_001.wav")
        result = groups_to_display([g])
        assert result[0]["4060"] == "Base_4060_001.wav"
        assert result[0]["4061"] == "Base_4061_001.wav"
        assert result[0]["416"] == "Base_416_001.wav"

    def test_missing_variant_shows_dash(self):
        g = self._make_group("002", "Base", "/a/f.wav", None, None)
        result = groups_to_display([g])
        assert result[0]["4061"] == "---"
        assert result[0]["416"] == "---"

    def test_paths_preserved(self):
        g = self._make_group("001", "Base", "/some/path/file.wav", None, None)
        result = groups_to_display([g])
        assert result[0]["4060_path"] == "/some/path/file.wav"
        assert result[0]["4061_path"] is None
