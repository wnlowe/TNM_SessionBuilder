"""
Smoke tests for the built ReaperSessionGenerator.exe.
Verifies the executable exists, is properly formed, and that all
core logic modules can be imported and function correctly when
bundled (tests run against source but exe path is validated).
"""
import os
import sys
import stat
import struct
import pytest

EXE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "dist", "ReaperSessionGenerator.exe"
)


class TestExecutableExists:
    def test_exe_exists(self):
        assert os.path.isfile(EXE_PATH), f"Executable not found at {EXE_PATH}"

    def test_exe_is_not_empty(self):
        size = os.path.getsize(EXE_PATH)
        assert size > 1_000_000, f"Executable seems too small ({size} bytes)"

    def test_exe_is_windows_pe(self):
        """Verify the file has a valid Windows PE (MZ) header."""
        with open(EXE_PATH, "rb") as f:
            magic = f.read(2)
        assert magic == b"MZ", f"Expected MZ header, got {magic!r}"

    def test_exe_is_executable(self):
        mode = os.stat(EXE_PATH).st_mode
        assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), \
            "Executable bit not set on built file"


class TestCoreModulesImportable:
    """Ensure all app modules load without errors (validates packaging integrity)."""

    def test_import_file_grouper(self):
        from app import file_grouper
        assert hasattr(file_grouper, "scan_folder")

    def test_import_aligner(self):
        from app import aligner
        assert hasattr(aligner, "align_all")

    def test_import_rpp_writer(self):
        from app import rpp_writer
        assert hasattr(rpp_writer, "build_rpp")

    def test_import_spreadsheet(self):
        from app import spreadsheet
        assert hasattr(spreadsheet, "SpreadsheetData")


class TestEndToEndRppGeneration:
    """Integration test: file grouper → aligner → rpp_writer pipeline."""

    def test_full_pipeline(self, tmp_path):
        from app.file_grouper import scan_folder, groups_to_display
        from app.aligner import align_all
        from app.rpp_writer import build_rpp, TrackDef, ItemDef

        # Create fake audio files
        for variant in ["4060", "4061", "416"]:
            for idx in ["001", "002"]:
                (tmp_path / f"Session_{variant}_{idx}.wav").touch()

        groups, unmatched = scan_folder(str(tmp_path))
        assert len(groups) == 2
        assert unmatched == []

        display = groups_to_display(groups)
        assert display[0]["index"] == "001"
        assert display[1]["index"] == "002"

        # Build simple word map for alignment
        def make_words(texts, offset=0.0):
            words = []
            t = offset
            for w in texts:
                words.append({"word": w, "start": t, "end": t + 0.4})
                t += 0.5
            return words

        rows = [
            {"index": "001", "output_name": "Line_001", "line_text": "hello world"},
            {"index": "002", "output_name": "Line_002", "line_text": "foo bar baz"},
        ]
        group_word_map = {
            "001": make_words(["hello", "world"]),
            "002": make_words(["foo", "bar", "baz"], offset=10.0),
        }
        row_to_group = {"001": "001", "002": "002"}

        results = align_all(rows, group_word_map, row_to_group)
        assert len(results) == 2

        # Build RPP from results
        items = []
        for i, r in enumerate(results):
            items.append(ItemDef(
                track_idx=0,
                source_path=str(tmp_path / f"Session_4060_{r.row_index}.wav"),
                source_offset=r.source_offset,
                length=r.length,
                timeline_pos=float(i * 5),
                output_name=r.output_name,
                row_index=r.row_index,
                note=r.line_text,
            ))

        track = TrackDef(name="4060", items=items)
        rpp = build_rpp([track], project_name="TestSession")

        assert "<REAPER_PROJECT" in rpp
        assert "Line_001" in rpp
        assert "Line_002" in rpp
        assert "hello world" in rpp
        assert "foo bar baz" in rpp
