# Workspace Documentation & Notes

## Project Overview: Reaper Session Generator

A Python application that:
1. Transcribes grouped audio takes using local Whisper models
2. Maps transcriptions to spreadsheet lines
3. Generates `.RPP` (Reaper project) files with word-accurate cut points

---

## Directory Structure

```
.
├── main.py              # Entry point, handles PyInstaller freeze support
├── README.md            # User documentation
├── requirements.txt     # Dependencies + jaraco packages for PyInstaller bundling
├── app/                 # Main application module
│   ├── gui.py          # CustomTkinter GUI implementation (main App class)
│   ├── aligner.py      # Audio alignment logic for cut points
│   ├── audio_player.py # Audio playback functionality (pygame?)
│   ├── file_grouper.py # Groups audio files by mic variant (4060/4061/416)
│   ├── rpp_writer.py   # Writes Reaper project XML
│   ├── session_builder.py # Builds Reaper session structure
│   ├── spreadsheet.py  # Loads/parses Excel spreadsheets (.xlsx)
│   ├── transcriber.py  # Whisper transcription logic
│   └── waveform_widget.py  # Waveform visualization widget
├── tests/               # Test suite
├── assets/              # Static resources (icons, etc.)
├── icons/               # Application icons
├── build_mac.sh         # macOS build script for PyInstaller
├── .gitignore           # Git ignore rules
└── .github/             # GitHub configuration
```

---

## Core Modules Overview

### `app/gui.py` - Main Application Interface
- Uses CustomTkinter for modern GUI
- Implements tab-based workflow:
  1. **Setup**: Load spreadsheet, map columns (Index, Output filename, Line text, Character)
  2. **File Groups**: Auto-detect grouped audio files by mic variant
  3. **Transcribe**: Process with Whisper, review/compare transcriptions
  4. **Generate**: Create and open Reaper project

### `app/file_grouper.py` - Audio File Grouping
- Detects mic variants in file naming convention:
  - `BASENAME_4060_INDEX.wav`
  - `BASENAME_4061_INDEX.wav`
  - `BASENAME_416_INDEX.wav`
- Maps found files to spreadsheet index numbers

### `app/transcriber.py` - Whisper Transcription
- Loads local Whisper model (base, medium, large-v3)
- Processes audio with ffmpeg for format conversion
- Returns word-level timestamps (start/end times)
- Supports re-scanning with different models

### `app/aligner.py` - Cut Point Alignment
- Calculates cut positions based on word timestamps
- Applies padding (start/end silence)
- Manages gap between items (default: 1 second)

### `app/rpp_writer.py` - Reaper Project Generation
- Creates `.RPP` XML project files
- Sets up tracks per mic variant (4060, 4061, 416)
- Items use SOFFS (source offset) - never modifies source files
- Item names from spreadsheet "Output filename" column

### `app/spreadsheet.py` - Excel Handling
- Loads `.xlsx` files with pandas/openpyxl
- Maps: Index → Line text, Character (optional filter)

---

## Technical Details

### Dependencies (`requirements.txt`)
- **customtkinter**: Modern Tkinter themeable UI
- **openai-whisper**: Local speech-to-text model
- **pandas**: Data manipulation for spreadsheet
- **openpyxl**: Excel file reading
- **soundfile**: Audio I/O (load/save)
- **pygame**: Audio playback widget (waveform?)
- **jaraco packages**: Required by PyInstaller bundling

### Key Constants/Configurations
- Track naming: `4060`, `4061`, `416` (mic variants)
- Item gap: 1 second between cuts
- Time format: 64-bit float seconds (Reaper native)
- Supported audio: `.wav`, `.aiff`, `.flac`, `.mp3`

### Workflow Flow
1. User loads spreadsheet with index mapping
2. App scans audio folder for matching files
3. Groups files by mic variant per index
4. User selects Whisper model, clicks "Transcribe All"
5. Each group transcribes once (timestamps shared across variants)
6. User reviews side-by-side transcription vs expected text
7. Problem lines marked and re-scanned if needed
8. Final generation creates .RPP in Reaper

---

## Build & Deployment

### Requirements Installation
```bash
pip install -r requirements.txt
# Also need ffmpeg on PATH:
# Mac: brew install ffmpeg
# Linux: sudo apt install ffmpeg
# Windows: download from ffmpeg.org
```

### PyInstaller Build (for macOS)
- `build_mac.sh` handles macOS-specific build
- Main `main.py` has freeze support for Windows GUI bundles
- jaraco packages bundled to satisfy PyTorch worker processes

---

## File Naming Convention Expected

```
BASENAME_4060_INDEX.wav  # Mic 1 (primary) - preferred for transcription
BASENAME_4061_INDEX.wav  # Mic 2 (alternate)
BASENAME_416_INDEX.wav   # Mic 3 (alternate)
```

- BASENAME: any text without underscore separator
- INDEX: matches spreadsheet "Index" column
- Extension: .wav, .aiff, .flac, .mp3 supported

---

## Notes for Future Work

### Areas to Investigate
1. **`waveform_widget.py`**: Purpose unclear - is it visualization or something else?
2. **`audio_player.py`**: Used where? For preview functionality?
3. **Test coverage**: Check `tests/` directory structure
4. **Error handling**: Where are exceptions caught and reported to user?
5. **Performance**: Any caching strategies for large spreadsheets/audio sets?

### User-Facing Features Not in README
- Checkbox marking on problem lines in transcribe tab
- "Re-scan Selected" functionality implementation details
- Exact padding configuration UI controls

---

## API Entry Points Summary

- `app.App` (in `gui.py`) is the main entry point
- Initializes with tabs: Setup → File Groups → Transcribe → Generate
- All heavy logic delegated to modules in `app/` directory