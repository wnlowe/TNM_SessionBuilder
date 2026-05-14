# Reaper Session Generator

Transcribes grouped audio takes with local Whisper, maps them to a spreadsheet,
and generates a `.RPP` Reaper project with word-accurate cut points.

---

## Setup

```bash
pip install -r requirements.txt
```

> Whisper also needs `ffmpeg` on your PATH:
> - **Mac**: `brew install ffmpeg`
> - **Windows**: download from https://ffmpeg.org and add to PATH
> - **Linux**: `sudo apt install ffmpeg`

---

## Run

```bash
python main.py
```

---

## Workflow

### Tab 1 · Setup
1. Load your `.xlsx` spreadsheet.
2. Map columns:
   - **Index** – the line number / identifier (e.g. `001`, `042`)
   - **Output filename** – what the final clip should be named in Reaper
   - **Line text** – the expected dialogue (used for transcription review)
   - **Character** *(optional)* – filter to a single character's lines
3. Point to your audio folder.
4. Enable the naming convention toggle if your files follow:
   `BASENAME_4060_INDEX.wav` / `_4061_` / `_416_`
5. Click **Apply Settings & Scan Files**.

### Tab 2 · File Groups
Review the auto-detected groupings. Each row shows which mic variant
file was found for each index. Rows highlighted in red have no match
in the spreadsheet.

### Tab 3 · Transcribe
- Select a Whisper model (larger = more accurate but slower).
  Recommended: `base` for speed, `medium` or `large-v3` for accuracy.
- Click **▶ Transcribe All** to process all lines.
  Only **one file per group** (4060 preferred) is transcribed —
  the same word timestamps are shared across all three takes.
- Review the transcribed text vs. expected text side-by-side.
- Tick checkboxes on problem lines and click **⟳ Re-scan Selected**
  to retry with a different model or after correcting the audio.
- Adjust **Pad start / end** (seconds) to fine-tune silence around cuts.

### Tab 4 · Generate
- Set a project name.
- Choose an output `.rpp` path.
- Click **Generate** — the session opens immediately in Reaper.

---

## Reaper Session Structure

```
Track 1: 4060  |  Line_001  |  Line_002  |  Line_003  | ...
Track 2: 4061  |  Line_001  |  Line_002  |  Line_003  | ...
Track 3: 416   |  Line_001  |  Line_002  |  Line_003  | ...
                ^-- 1 second gap between items
```

- All times in seconds (64-bit float, Reaper native).
- Items use `SOFFS` (source offset) — source files are **never modified**.
- Item names come from the **Output filename** spreadsheet column.

---

## File Naming Convention

```
BASENAME_4060_INDEX.wav
BASENAME_4061_INDEX.wav
BASENAME_416_INDEX.wav
```

- `BASENAME` can be anything (no underscores between base and variant).
- `INDEX` matches the Index column in the spreadsheet (numeric or alphanumeric).
- Extension: `.wav`, `.aiff`, `.flac`, `.mp3` all supported.
