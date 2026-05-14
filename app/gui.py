"""
gui.py — Main application window.

Tabs:
  1 · Setup       – XLSX + folder + column mapping
  2 · File Groups – review auto-grouped files
  3 · Transcribe  – run Whisper per group
  4 · Align       – review/correct line-to-audio alignment, playback
  5 · Generate    – build RPP session
"""

from __future__ import annotations
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from .spreadsheet import SpreadsheetData
from .file_grouper import scan_folder, groups_to_display, MIC_VARIANTS
from .transcriber import available_models, transcribe
from .aligner import align_all, AlignmentResult
from .audio_player import AudioPlayer
from .waveform_widget import WaveformWidget
from .session_builder import build_session

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CLR_BG      = "#1a1a2e"
CLR_PANEL   = "#16213e"
CLR_CARD    = "#0f3460"
CLR_ACCENT  = "#e94560"
CLR_TEXT    = "#eaeaea"
CLR_MUTED   = "#7a7a9a"
CLR_OK      = "#27ae60"
CLR_WARN    = "#f39c12"
CLR_ERR     = "#e74c3c"

CONF_COLORS = {1: "#e74c3c", 2: "#e67e22", 3: "#f1c40f", 4: "#2ecc71", 5: "#27ae60"}
CONF_LABELS = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}

FONT_TITLE   = ("Helvetica", 18, "bold")
FONT_HEADING = ("Helvetica", 13, "bold")
FONT_BODY    = ("Helvetica", 11)
FONT_MONO    = ("Courier New", 10)
FONT_SMALL   = ("Helvetica", 9)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Reaper Session Generator")
        self._set_icon()
        self.geometry("1280x860")
        self.configure(fg_color=CLR_BG)
        self.minsize(1000, 680)

        # ── Core state ────────────────────────────────────────────────────────
        self.xlsx_path     = tk.StringVar()
        self.folder_path   = tk.StringVar()
        self.sheet_data: Optional[SpreadsheetData] = None
        self.rows:       List[Dict] = []
        self.file_groups: Dict[str, Dict] = {}   # group_index → {4060/4061/416: path}
        self.display_groups: List[Dict] = []

        # Transcription results (keyed by group index)
        self.transcripts: Dict[str, str]        = {}
        self.word_data:   Dict[str, List[Dict]] = {}

        # Alignment results (keyed by row index)
        self.alignments: Dict[str, AlignmentResult] = {}

        # Column mapping
        self.col_index     = tk.StringVar()
        self.col_output    = tk.StringVar()
        self.col_line_text = tk.StringVar()
        self.col_character = tk.StringVar(value="(none)")
        self.char_filter   = tk.StringVar()
        self.use_grouping  = tk.BooleanVar(value=True)

        # Row→group assignment
        self.row_to_group: Dict[str, str] = {}

        self.whisper_model = tk.StringVar(value="base")
        self.project_name  = tk.StringVar(value="Session")
        self.output_rpp    = tk.StringVar()

        # Shared mic selector state (used by review tab expand panels)
        self._detail_mic = tk.StringVar(value="4060")

        # Review tab state (populated in _build_review_tab)
        self._review_card_widgets: Dict[str, Dict] = {}
        self._review_sel_group: Optional[str] = None
        self._review_sel_row:   Optional[str] = None
        self._review_sel_var:   Dict[str, tk.BooleanVar] = {}

        # Combined word list and group offsets (set by _review_run_alignment)
        self._combined_words: List[Dict] = []
        self._group_offsets:  Dict[str, float] = {}

        # Rows explicitly removed / skipped by the user (never written to RPP)
        self.skipped_rows: set = set()

        # Reference to open coverage popup (prevent duplicates)
        self._coverage_popup: Optional[tk.Toplevel] = None

        self._player = AudioPlayer()

        self._build_header()
        self._build_tabs()

    def _set_icon(self):
        base = sys._MEIPASS if getattr(sys, 'frozen', False) else \
               os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if sys.platform == 'win32':
            ico = os.path.join(base, 'assets', 'icon.ico')
            if os.path.exists(ico):
                self.iconbitmap(ico)
        else:
            png = os.path.join(base, 'assets', 'icon.png')
            if os.path.exists(png):
                self.iconphoto(True, tk.PhotoImage(file=png))

    # ═══════════════════════════════════════════════════════════════════════════
    # Header
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=CLR_PANEL, height=52, corner_radius=0)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="⬡  REAPER SESSION GENERATOR",
                     font=FONT_TITLE, text_color=CLR_ACCENT).pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(hdr, text="Whisper  →  align  →  .RPP",
                     font=FONT_BODY, text_color=CLR_MUTED).pack(side="left", padx=4)

    # ═══════════════════════════════════════════════════════════════════════════
    # Tabs
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self, fg_color=CLR_PANEL,
            segmented_button_fg_color=CLR_CARD,
            segmented_button_selected_color=CLR_ACCENT,
            segmented_button_selected_hover_color="#c73d52",
            segmented_button_unselected_hover_color="#1f3a5f",
            text_color=CLR_TEXT,
        )
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        for n in ("1 · Setup", "2 · File Groups", "3 · Review", "4 · Generate"):
            self.tabs.add(n)
        self._build_setup_tab(self.tabs.tab("1 · Setup"))
        self._build_groups_tab(self.tabs.tab("2 · File Groups"))
        self._build_review_tab(self.tabs.tab("3 · Review"))
        self._build_generate_tab(self.tabs.tab("4 · Generate"))

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 – Setup
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_setup_tab(self, parent):
        parent.configure(fg_color=CLR_BG)
        scroll = ctk.CTkScrollableFrame(parent, fg_color=CLR_BG)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        sec = self._section(scroll, "📄  Spreadsheet (XLSX)")
        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkEntry(row, textvariable=self.xlsx_path, width=480,
                     fg_color=CLR_CARD, text_color=CLR_TEXT, border_color=CLR_ACCENT,
                     placeholder_text="Path to .xlsx…").pack(side="left", padx=(0,8))
        ctk.CTkButton(row, text="Browse…", width=90, fg_color=CLR_ACCENT,
                      hover_color="#c73d52", command=self._browse_xlsx).pack(side="left")
        ctk.CTkButton(row, text="Load", width=70, fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT, command=self._load_xlsx).pack(side="left", padx=8)

        self._col_map_frame = self._section(scroll, "🗂  Column Mapping")
        self._col_map_hint = ctk.CTkLabel(self._col_map_frame,
            text="Load a spreadsheet first.", font=FONT_BODY, text_color=CLR_MUTED)
        self._col_map_hint.pack(anchor="w")

        sec2 = self._section(scroll, "🎵  Audio Folder")
        frow = ctk.CTkFrame(sec2, fg_color="transparent")
        frow.pack(fill="x", pady=4)
        ctk.CTkEntry(frow, textvariable=self.folder_path, width=480,
                     fg_color=CLR_CARD, text_color=CLR_TEXT, border_color=CLR_ACCENT,
                     placeholder_text="Folder containing .wav files…").pack(side="left", padx=(0,8))
        ctk.CTkButton(frow, text="Browse…", width=90, fg_color=CLR_ACCENT,
                      hover_color="#c73d52", command=self._browse_folder).pack(side="left")
        ctk.CTkSwitch(sec2, text="Use 4060/4061/416 naming convention",
                      variable=self.use_grouping, progress_color=CLR_ACCENT,
                      font=FONT_BODY, text_color=CLR_TEXT).pack(anchor="w", pady=6)

        ctk.CTkButton(scroll, text="Apply Settings & Scan Files  →",
                      fg_color=CLR_ACCENT, hover_color="#c73d52",
                      font=FONT_HEADING, height=42,
                      command=self._apply_setup).pack(pady=14, anchor="e", padx=4)
        self._setup_status = ctk.CTkLabel(scroll, text="", font=FONT_BODY, text_color=CLR_OK)
        self._setup_status.pack(anchor="w")

    def _browse_xlsx(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls"), ("All", "*.*")])
        if p:
            self.xlsx_path.set(p)
            self._load_xlsx()

    def _browse_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.folder_path.set(p)

    def _load_xlsx(self):
        path = self.xlsx_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Select a valid XLSX file.")
            return
        try:
            self.sheet_data = SpreadsheetData(path)
            self._build_column_mapping()
            self._setup_status.configure(
                text=f"✓ {len(self.sheet_data.df)} rows, {len(self.sheet_data.columns)} columns",
                text_color=CLR_OK)
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _build_column_mapping(self):
        for w in self._col_map_frame.winfo_children():
            w.destroy()
        cols = self.sheet_data.columns
        opts_req = list(cols)
        opts_opt = ["(none)"] + list(cols)

        def _row(lbl, var, opts):
            f = ctk.CTkFrame(self._col_map_frame, fg_color="transparent")
            f.pack(fill="x", pady=3)
            ctk.CTkLabel(f, text=lbl, font=FONT_BODY, width=190,
                         text_color=CLR_TEXT, anchor="w").pack(side="left")
            ctk.CTkOptionMenu(f, variable=var, values=opts,
                              fg_color=CLR_CARD, button_color=CLR_ACCENT,
                              button_hover_color="#c73d52", text_color=CLR_TEXT,
                              width=250).pack(side="left", padx=8)

        _row("Index / order column:", self.col_index, opts_req)
        _row("Output filename column:", self.col_output, opts_req)
        _row("Line text column:", self.col_line_text, opts_req)
        _row("Character column (opt):", self.col_character, opts_opt)

        cf = ctk.CTkFrame(self._col_map_frame, fg_color="transparent")
        cf.pack(fill="x", pady=3)
        ctk.CTkLabel(cf, text="Filter to character:", font=FONT_BODY, width=190,
                     text_color=CLR_TEXT, anchor="w").pack(side="left")
        ctk.CTkEntry(cf, textvariable=self.char_filter, width=250,
                     fg_color=CLR_CARD, text_color=CLR_TEXT,
                     placeholder_text="blank = all").pack(side="left", padx=8)

        ctk.CTkLabel(self._col_map_frame, text="Preview:",
                     font=FONT_SMALL, text_color=CLR_MUTED).pack(anchor="w", pady=(8,2))
        ctk.CTkLabel(self._col_map_frame,
                     text=self.sheet_data.preview(3).to_string(index=False),
                     font=FONT_MONO, text_color=CLR_MUTED, justify="left").pack(anchor="w")

    def _apply_setup(self):
        for var, name in [(self.col_index, "Index"), (self.col_output, "Output filename"),
                          (self.col_line_text, "Line text")]:
            if not var.get() or var.get() == "(none)":
                messagebox.showerror("Missing", f"{name} column must be selected.")
                return
        if not self.sheet_data:
            messagebox.showerror("Error", "Load a spreadsheet first.")
            return
        char_col  = self.col_character.get() if self.col_character.get() != "(none)" else None
        char_filt = self.char_filter.get().strip() or None
        self.rows = self.sheet_data.get_rows(
            index_col=self.col_index.get(), output_name_col=self.col_output.get(),
            line_text_col=self.col_line_text.get(),
            character_col=char_col, character_filter=char_filt)
        folder = self.folder_path.get().strip()
        if self.use_grouping.get() and folder:
            raw, _ = scan_folder(folder)
            self.display_groups = groups_to_display(raw)
            self.file_groups = {g["index"]: {"4060": g["4060"], "4061": g["4061"],
                                             "416": g["416"]} for g in raw}
        else:
            self.display_groups = []
            self.file_groups = {}
        self.transcripts      = {}
        self.word_data        = {}
        self.alignments       = {}
        self._combined_words  = []
        self._group_offsets   = {}
        self.skipped_rows     = set()
        self._setup_status.configure(
            text=f"✓ {len(self.rows)} rows · {len(self.file_groups)} file groups",
            text_color=CLR_OK)
        self._refresh_groups_tab()
        self._refresh_review_tab()
        self.tabs.set("2 · File Groups")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 – File Groups
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_groups_tab(self, parent):
        parent.configure(fg_color=CLR_BG)
        top = ctk.CTkFrame(parent, fg_color=CLR_PANEL, height=44, corner_radius=6)
        top.pack(fill="x", padx=10, pady=(10,4))
        ctk.CTkLabel(top, text="Review auto-grouped files. One group may cover multiple lines.",
                     font=FONT_BODY, text_color=CLR_MUTED).pack(side="left", padx=14, pady=8)
        ctk.CTkButton(top, text="Proceed to Review  →", width=190,
                      fg_color=CLR_ACCENT, hover_color="#c73d52",
                      command=lambda: self.tabs.set("3 · Review")).pack(side="right", padx=10, pady=6)
        ctk.CTkButton(top, text="Re-scan", width=90, fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT, command=self._apply_setup).pack(side="right", padx=4, pady=6)

        self._groups_scroll = ctk.CTkScrollableFrame(parent, fg_color=CLR_BG)
        self._groups_scroll.pack(fill="both", expand=True, padx=10, pady=4)
        self._groups_table_frame = self._groups_scroll
        self._groups_status = ctk.CTkLabel(parent, text="", font=FONT_SMALL, text_color=CLR_MUTED)
        self._groups_status.pack(anchor="w", padx=12, pady=4)

    def _refresh_groups_tab(self):
        for w in self._groups_table_frame.winfo_children():
            w.destroy()
        if not self.display_groups:
            ctk.CTkLabel(self._groups_table_frame,
                         text="No groups found.", font=FONT_BODY, text_color=CLR_WARN).pack(pady=20)
            return
        self._grp_row(["Index", "Base name", "4060", "4061", "416"], header=True)
        for g in self.display_groups:
            missing = any(g[mk] == "---" for mk in ["4060","4061","416"])
            self._grp_row([g["index"], g["base"], g["4060"], g["4061"], g["416"]], missing=missing)
        complete = sum(1 for g in self.display_groups if all(g[mk] != "---" for mk in ["4060","4061","416"]))
        self._groups_status.configure(
            text=f"{len(self.display_groups)} groups · {complete} complete · {len(self.display_groups)-complete} partial")

    def _grp_row(self, vals, header=False, missing=False):
        bg = CLR_CARD if header else CLR_PANEL
        f  = ctk.CTkFrame(self._groups_table_frame, fg_color=bg, corner_radius=4)
        f.pack(fill="x", pady=1, padx=2)
        for val, w in zip(vals, [80, 280, 190, 190, 190]):
            tc = CLR_ACCENT if header else (CLR_WARN if (missing and str(val)=="---") else CLR_TEXT)
            ctk.CTkLabel(f, text=str(val), font=FONT_HEADING if header else FONT_BODY,
                         text_color=tc, width=w, anchor="w").pack(side="left", padx=8, pady=5)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 – Review  (combined Transcribe + Align)
    # ═══════════════════════════════════════════════════════════════════════════

    # Palette for colouring rows — each row index gets one colour
    ROW_PALETTE = [
        "#3a7bd5", "#e94560", "#27ae60", "#f39c12", "#9b59b6",
        "#1abc9c", "#e67e22", "#2980b9", "#c0392b", "#16a085",
        "#8e44ad", "#d35400", "#27ae60", "#2471a3", "#a93226",
    ]

    def _build_review_tab(self, parent):
        parent.configure(fg_color=CLR_BG)

        # ── Top control bar ────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(parent, fg_color=CLR_PANEL, corner_radius=6)
        ctrl.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(ctrl, text="Model:", font=FONT_BODY,
                     text_color=CLR_TEXT).pack(side="left", padx=(14, 4), pady=8)
        ctk.CTkOptionMenu(ctrl, variable=self.whisper_model, values=available_models(),
                          fg_color=CLR_CARD, button_color=CLR_ACCENT,
                          button_hover_color="#c73d52", text_color=CLR_TEXT,
                          width=130).pack(side="left", padx=4)

        ctk.CTkButton(ctrl, text="▶  Transcribe All", fg_color=CLR_OK,
                      hover_color="#1e8449",
                      command=self._review_transcribe_all).pack(side="left", padx=10)
        ctk.CTkButton(ctrl, text="⟳  Re-transcribe Selected", fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT,
                      command=self._review_retranscribe_selected).pack(side="left", padx=4)
        ctk.CTkButton(ctrl, text="⚡  Run Alignment", fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT,
                      command=self._review_run_alignment).pack(side="left", padx=4)

        self._review_progress = ctk.CTkLabel(ctrl, text="", font=FONT_SMALL,
                                             text_color=CLR_MUTED)
        self._review_progress.pack(side="left", padx=14)

        ctk.CTkButton(ctrl, text="📋  Coverage Review", width=160,
                      fg_color=CLR_CARD, hover_color="#1f5080",
                      command=self._open_coverage_popup).pack(
                      side="right", padx=4, pady=6)

        ctk.CTkButton(ctrl, text="Proceed to Generate  →", width=190,
                      fg_color=CLR_ACCENT, hover_color="#c73d52",
                      command=lambda: self.tabs.set("4 · Generate")).pack(
                      side="right", padx=10, pady=6)

        # ── Scrollable cards area ──────────────────────────────────────────────
        self._review_scroll = ctk.CTkScrollableFrame(parent, fg_color=CLR_BG)
        self._review_scroll.pack(fill="both", expand=True, padx=10, pady=4)

        # Per-card state
        self._review_card_widgets: Dict[str, Dict] = {}   # gidx → widget refs
        self._review_sel_group:    Optional[str]   = None  # expanded group
        self._review_sel_row:      Optional[str]   = None  # expanded row idx
        self._review_sel_var:      Dict[str, tk.BooleanVar] = {}  # gidx → checkbox

    def _row_color(self, row_index: str) -> str:
        """Stable colour assignment per row index."""
        rows_by_idx = {r["index"]: i for i, r in enumerate(self.rows)}
        i = rows_by_idx.get(row_index, 0)
        return self.ROW_PALETTE[i % len(self.ROW_PALETTE)]

    def _refresh_review_tab(self):
        for w in self._review_scroll.winfo_children():
            w.destroy()
        self._review_card_widgets = {}
        self._review_sel_group    = None
        self._review_sel_row      = None
        self._review_sel_var      = {}

        if not self.display_groups:
            ctk.CTkLabel(self._review_scroll,
                         text="No groups found. Complete Setup first.",
                         font=FONT_BODY, text_color=CLR_WARN).pack(pady=20)
            return

        for g in self.display_groups:
            self._build_group_card(self._review_scroll, g)

    def _build_group_card(self, parent, g: Dict):
        gidx   = g["index"]
        has_tx = gidx in self.transcripts

        card = ctk.CTkFrame(parent, fg_color=CLR_PANEL, corner_radius=8)
        card.pack(fill="x", pady=6, padx=2)

        # ── Card header ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(card, fg_color=CLR_CARD, corner_radius=6)
        hdr.pack(fill="x", padx=8, pady=(8, 4))

        # Left: checkbox + group index + file badges
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", padx=10, pady=6)

        sel_var = tk.BooleanVar(value=False)
        self._review_sel_var[gidx] = sel_var
        ctk.CTkCheckBox(left, text="", variable=sel_var, width=20,
                        checkbox_width=16, checkbox_height=16,
                        fg_color=CLR_ACCENT, border_color=CLR_MUTED,
                        hover_color="#c73d52").pack(side="left", padx=(0, 8))

        ctk.CTkLabel(left, text=f"Group {gidx}", font=FONT_HEADING,
                     text_color=CLR_ACCENT).pack(side="left", padx=(0, 12))

        for mic in ["4060", "4061", "416"]:
            has = g.get(f"{mic}_path") is not None
            clr = CLR_OK if has else "#333355"
            ctk.CTkLabel(left, text=mic, font=FONT_SMALL, text_color=clr,
                         fg_color="#1a2a1a" if has else "#1a1a2a",
                         corner_radius=4, width=40).pack(side="left", padx=2)

        # Middle: status label
        st_lbl = ctk.CTkLabel(hdr, text="pending" if not has_tx else "✓ transcribed",
                               font=FONT_SMALL,
                               text_color=CLR_OK if has_tx else CLR_MUTED)
        st_lbl.pack(side="left", padx=16)

        # Right: per-card transcribe button
        tx_btn = ctk.CTkButton(hdr, text="▶ Transcribe", width=110,
                               fg_color=CLR_OK if not has_tx else CLR_CARD,
                               hover_color="#1e8449",
                               command=lambda gi=gidx: self._review_transcribe_one(gi))
        tx_btn.pack(side="right", padx=10, pady=6)

        # ── Body ────────────────────────────────────────────────────────────────
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=8, pady=(0, 6))

        # Transcript section (collapsible)
        tx_frame = ctk.CTkFrame(body, fg_color="#0a1520", corner_radius=6)
        tx_frame.pack(fill="x", pady=(0, 6))

        tx_toggle_var = tk.BooleanVar(value=True)
        tx_header = ctk.CTkFrame(tx_frame, fg_color="transparent")
        tx_header.pack(fill="x", padx=8, pady=(4, 0))
        tx_toggle_btn = ctk.CTkButton(
            tx_header, text="▾ Transcript", width=110, height=24,
            fg_color="transparent", hover_color=CLR_CARD,
            text_color=CLR_MUTED, font=FONT_SMALL,
            command=lambda tf=tx_frame, tv=tx_toggle_var: self._toggle_transcript(tf, tv))
        tx_toggle_btn.pack(side="left")

        # Transcript text canvas (word-highlighted)
        tx_canvas_frame = ctk.CTkFrame(tx_frame, fg_color="transparent")
        tx_canvas_frame.pack(fill="x", padx=8, pady=(2, 6))
        tx_text = tk.Text(tx_canvas_frame, bg="#0a1520", fg=CLR_MUTED,
                          font=FONT_MONO, height=3, wrap="word",
                          relief="flat", bd=0, cursor="arrow",
                          state="disabled", selectbackground=CLR_CARD)
        tx_text.pack(fill="x")

        # ── Timeline strip ─────────────────────────────────────────────────────
        tl_frame = ctk.CTkFrame(body, fg_color="#0a1520", corner_radius=6)
        tl_frame.pack(fill="x", pady=(0, 4))
        tl_label = ctk.CTkLabel(tl_frame, text="Timeline", font=FONT_SMALL,
                                text_color=CLR_MUTED)
        tl_label.pack(anchor="w", padx=10, pady=(4, 0))
        tl_canvas = tk.Canvas(tl_frame, bg="#0a1520", height=32,
                              highlightthickness=0)
        tl_canvas.pack(fill="x", padx=8, pady=(2, 6))

        # ── Row list ────────────────────────────────────────────────────────────
        rows_frame = ctk.CTkFrame(body, fg_color="transparent")
        rows_frame.pack(fill="x")

        # Store all widget refs for this card
        self._review_card_widgets[gidx] = {
            "card":       card,
            "st_lbl":     st_lbl,
            "tx_btn":     tx_btn,
            "tx_text":    tx_text,
            "tx_frame":   tx_canvas_frame,
            "tl_canvas":  tl_canvas,
            "rows_frame": rows_frame,
            "row_widgets": {},   # ridx → widget dict
            "expanded_ridx": None,
        }

        # Populate if we already have data
        if has_tx:
            self._update_card_transcript(gidx)
        if self.alignments:
            self._update_card_rows(gidx)
            self._update_timeline(gidx)

        # Bind timeline click
        tl_canvas.bind("<Button-1>",
                       lambda e, gi=gidx: self._on_timeline_click(e, gi))

    def _toggle_transcript(self, tx_frame, var):
        var.set(not var.get())
        if var.get():
            tx_frame.pack(fill="x", padx=8, pady=(2, 6))
        else:
            tx_frame.pack_forget()

    # ── Transcript update ──────────────────────────────────────────────────────

    def _update_card_transcript(self, gidx: str):
        w = self._review_card_widgets.get(gidx)
        if not w:
            return
        tx_text = w["tx_text"]
        words   = self.word_data.get(gidx, [])

        tx_text.configure(state="normal")
        tx_text.delete("1.0", "end")

        if not words:
            tx_text.insert("end", self.transcripts.get(gidx, ""), "default")
            tx_text.tag_configure("default", foreground=CLR_MUTED)
            tx_text.configure(state="disabled")
            return

        # Build a word→row colour map from alignments
        word_colors = self._compute_word_colors(gidx)

        for i, wd in enumerate(words):
            colour = word_colors.get(i, CLR_MUTED)
            tag    = f"w_{gidx}_{i}"
            tx_text.insert("end", wd["word"] + " ", tag)
            tx_text.tag_configure(tag, foreground=colour)
            # Click handler: snap selected row's nearest handle to this word's time
            tx_text.tag_bind(tag, "<Button-1>",
                             lambda e, gi=gidx, wi=i: self._on_word_click(gi, wi))
            tx_text.tag_bind(tag, "<Enter>",
                             lambda e, t=tag, txt=tx_text: txt.tag_configure(t, underline=True))
            tx_text.tag_bind(tag, "<Leave>",
                             lambda e, t=tag, txt=tx_text: txt.tag_configure(t, underline=False))

        tx_text.configure(state="disabled", cursor="arrow")
        w["st_lbl"].configure(text="✓ transcribed", text_color=CLR_OK)
        w["tx_btn"].configure(fg_color=CLR_CARD, text="⟳ Re-transcribe")

    def _compute_word_colors(self, gidx: str) -> Dict[int, str]:
        """Return {word_index: hex_colour} for every word in gidx."""
        words  = self.word_data.get(gidx, [])
        result: Dict[int, str] = {}
        if not words:
            return result

        # Map each word index to the row that owns it (by time overlap)
        for ridx, ar in self.alignments.items():
            if not ar.takes:
                continue
            # Only colour words from the owning group
            if not self._ar_belongs_to_group(ar, gidx):
                continue
            clr = self._row_color(ridx)
            soffs = ar.source_offset
            send  = ar.source_offset + ar.length
            for wi, wd in enumerate(words):
                mid = (wd["start"] + wd["end"]) / 2
                if soffs <= mid <= send:
                    # Overlap detection: already claimed → warning colour
                    if wi in result and result[wi] != clr:
                        result[wi] = CLR_WARN
                    else:
                        result[wi] = clr
        return result

    def _alignment_group(self, ar: "AlignmentResult") -> Optional[str]:
        """
        Return the gidx that owns this alignment by reading the _group tag
        on the matched word in the combined (offset) word list.
        This is O(1) and 100% reliable regardless of timestamp ranges.
        """
        combined = getattr(self, "_combined_words", None)
        if combined and ar.takes:
            wi = ar.word_start_i
            if 0 <= wi < len(combined):
                return combined[wi].get("_group")
        # Fallback: single group session
        if len(self.word_data) == 1:
            return next(iter(self.word_data))
        return None

    def _ar_belongs_to_group(self, ar: "AlignmentResult", gidx: str) -> bool:
        """Check if an alignment result belongs to gidx via _group tag lookup."""
        return self._alignment_group(ar) == gidx

    # ── Timeline update ────────────────────────────────────────────────────────

    def _update_timeline(self, gidx: str):
        w = self._review_card_widgets.get(gidx)
        if not w:
            return
        canvas = w["tl_canvas"]
        canvas.delete("all")
        words  = self.word_data.get(gidx, [])
        if not words:
            return

        g_start   = words[0]["start"]
        g_end     = words[-1]["end"]
        duration  = max(0.01, g_end - g_start)

        def to_px(t):
            cw = canvas.winfo_width() or 500
            return int((t - g_start) / duration * cw)

        # Background track
        cw = canvas.winfo_width() or 500
        canvas.create_rectangle(0, 8, cw, 24, fill="#1a2a3a", outline="")

        # Draw row blocks
        row_blocks = []  # (ridx, x1, x2) for click detection
        for ridx, ar in self.alignments.items():
            if not self._ar_belongs_to_group(ar, gidx):
                continue
            x1 = to_px(ar.source_offset)
            x2 = to_px(ar.source_offset + ar.length)
            x2 = max(x1 + 3, x2)
            clr = self._row_color(ridx)
            is_sel = (ridx == self._review_sel_row)
            outline = "#ffffff" if is_sel else ""
            canvas.create_rectangle(x1, 6, x2, 26, fill=clr,
                                    outline=outline, width=2 if is_sel else 0)
            # Row index label if wide enough
            if x2 - x1 > 24:
                canvas.create_text((x1 + x2) // 2, 16, text=ridx,
                                   fill="#ffffff", font=("Courier New", 7))
            row_blocks.append((ridx, x1, x2))

        # Store block positions for click detection
        w["tl_blocks"] = row_blocks
        w["tl_g_start"] = g_start
        w["tl_g_end"]   = g_end

        # Bind resize to redraw
        canvas.bind("<Configure>",
                    lambda e, gi=gidx: self.after(10, lambda: self._update_timeline(gi)))

    def _on_timeline_click(self, event, gidx: str):
        w = self._review_card_widgets.get(gidx)
        if not w:
            return
        blocks = w.get("tl_blocks", [])
        for ridx, x1, x2 in blocks:
            if x1 <= event.x <= x2:
                self._review_select_row(gidx, ridx)
                return

    # ── Row list update ────────────────────────────────────────────────────────

    def _update_card_rows(self, gidx: str):
        w = self._review_card_widgets.get(gidx)
        if not w:
            return
        rows_frame = w["rows_frame"]
        for child in rows_frame.winfo_children():
            child.destroy()
        w["row_widgets"] = {}

        words = self.word_data.get(gidx, [])

        # Collect rows that belong to this group, sorted by source_offset
        group_rows = []
        for row in self.rows:
            ridx = row["index"]
            ar   = self.alignments.get(ridx)
            if ar and self._ar_belongs_to_group(ar, gidx):
                group_rows.append((ar.source_offset, ridx, row, ar))
        group_rows.sort(key=lambda x: x[0])

        if not group_rows:
            ctk.CTkLabel(rows_frame,
                         text="No aligned rows for this group. Run alignment.",
                         font=FONT_SMALL, text_color=CLR_MUTED).pack(anchor="w", padx=10, pady=4)
            return

        for _, ridx, row, ar in group_rows:
            self._build_row_entry(rows_frame, gidx, ridx, row, ar, w)

    def _build_row_entry(self, parent, gidx, ridx, row, ar, card_w):
        clr      = self._row_color(ridx)
        conf_clr = CONF_COLORS.get(ar.confidence, CLR_MUTED)
        bg       = "#1e0a0a" if ar.needs_review else "#0e1a0e"
        is_sel   = (ridx == self._review_sel_row)

        # Outer container — tk.Frame for click binding
        outer = tk.Frame(parent, bg=CLR_CARD if is_sel else bg, cursor="hand2")
        outer.pack(fill="x", pady=2, padx=4)

        # Colour stripe
        stripe = tk.Frame(outer, bg=clr, width=4)
        stripe.pack(side="left", fill="y")

        # Row summary line
        summary = tk.Frame(outer, bg=CLR_CARD if is_sel else bg)
        summary.pack(side="left", fill="x", expand=True)

        def _lbl(f, text, fg, fnt=FONT_BODY, w=None, anchor="w"):
            kw = {"width": w} if w else {}
            lb = tk.Label(f, text=text, font=fnt, fg=fg,
                          bg=CLR_CARD if is_sel else bg, anchor=anchor, **kw)
            lb.pack(side="left", padx=4, pady=4)
            return lb

        row_num    = row.get("row_number", "")
        display_idx = row.get("base_index", ridx)
        _lbl(summary, f"#{row_num}",                       "#4a5568",  FONT_MONO, w=4)
        _lbl(summary, display_idx,                         CLR_MUTED,  FONT_MONO, w=5)
        _lbl(summary, CONF_LABELS[ar.confidence],          conf_clr,   FONT_SMALL)
        _lbl(summary, self._trunc(ar.line_text, 35),       CLR_TEXT)
        _lbl(summary, "→",                                 CLR_MUTED,  FONT_SMALL)
        _lbl(summary, self._trunc(ar.matched_text, 35),
             CLR_TEXT if not ar.needs_review else CLR_WARN)
        _lbl(summary, f"{ar.source_offset:.2f}+{ar.length:.2f}s",
             CLR_MUTED, FONT_MONO)

        # Expand/collapse area (hidden by default)
        expand_frame = tk.Frame(outer, bg=CLR_BG)
        if is_sel:
            expand_frame.pack(fill="x", padx=4, pady=4)
            self._build_row_expand(expand_frame, gidx, ridx, ar)

        # Click to select
        for widget in (outer, stripe, summary):
            widget.bind("<Button-1>",
                        lambda e, gi=gidx, ri=ridx: self._review_select_row(gi, ri))
        for child in summary.winfo_children():
            child.bind("<Button-1>",
                       lambda e, gi=gidx, ri=ridx: self._review_select_row(gi, ri))

        # Right-side action buttons (always visible, don't trigger expand)
        btn_area = tk.Frame(outer, bg=CLR_CARD if is_sel else bg)
        btn_area.pack(side="right", padx=6, pady=2)

        # ✓ Confirm button (only shown when needs_review)
        if ar.needs_review:
            def _confirm(event=None, gi=gidx, ri=ridx):
                _ar = self.alignments.get(ri)
                if _ar:
                    _ar.needs_review = False
                    _ar.confidence   = max(_ar.confidence, 3)
                self._refresh_all_review_cards()
            ctk.CTkButton(btn_area, text="✓", width=28, height=22,
                          fg_color=CLR_OK, hover_color="#1e8449",
                          font=FONT_SMALL,
                          command=_confirm).pack(side="left", padx=2)

        # ✕ Remove button (always shown)
        def _remove(event=None, gi=gidx, ri=ridx):
            if messagebox.askyesno("Remove alignment",
                                   f"Remove alignment for row '{ri}'?\n"
                                   "It will appear as Not Found in the coverage review."):
                self.alignments.pop(ri, None)
                self.skipped_rows.add(ri)
                self._review_sel_row   = None
                self._review_sel_group = None
                self._refresh_all_review_cards()
        ctk.CTkButton(btn_area, text="✕", width=28, height=22,
                      fg_color="#3a1a1a", hover_color=CLR_ERR,
                      font=FONT_SMALL,
                      command=_remove).pack(side="left", padx=2)

        card_w["row_widgets"][ridx] = {
            "outer":        outer,
            "expand_frame": expand_frame,
            "bg":           bg,
        }

    def _build_row_expand(self, parent, gidx, ridx, ar):
        """Build the inline expanded view: waveform + controls + timestamps."""
        clr = self._row_color(ridx)

        # Mic selector
        mic_row = tk.Frame(parent, bg=CLR_BG)
        mic_row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(mic_row, text="Mic:", font=FONT_SMALL, fg=CLR_MUTED,
                 bg=CLR_BG).pack(side="left", padx=(0, 6))
        for mic in ["4060", "4061", "416"]:
            ctk.CTkRadioButton(mic_row, text=mic, variable=self._detail_mic,
                               value=mic, fg_color=clr,
                               font=FONT_SMALL, text_color=CLR_TEXT,
                               command=lambda gi=gidx, ri=ridx: self._review_reload_waveform(gi, ri)
                               ).pack(side="left", padx=4)

        # Waveform
        wf_outer = tk.Frame(parent, bg="#0a1520")
        wf_outer.pack(fill="x", padx=8, pady=4)
        wf = WaveformWidget(wf_outer, width=600, height=80)
        wf.pack(fill="x", padx=2, pady=2)
        wf.on_change = lambda s, e, gi=gidx, ri=ridx: self._on_review_waveform_change(gi, ri, s, e)

        # Playback
        pb = tk.Frame(parent, bg=CLR_BG)
        pb.pack(fill="x", padx=8, pady=2)
        play_btn = ctk.CTkButton(pb, text="▶  Play", width=90,
                                 fg_color=CLR_OK, hover_color="#1e8449",
                                 command=lambda gi=gidx, ri=ridx: self._review_play(gi, ri))
        play_btn.pack(side="left", padx=(0, 6))
        ctk.CTkButton(pb, text="■  Stop", width=70, fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT,
                      command=self._stop_playback).pack(side="left")

        # Timestamp entry
        ts_row = tk.Frame(parent, bg=CLR_BG)
        ts_row.pack(fill="x", padx=8, pady=4)
        tk.Label(ts_row, text="Start:", font=FONT_SMALL, fg=CLR_MUTED,
                 bg=CLR_BG).pack(side="left")
        ts_start_var = tk.StringVar(value=f"{ar.source_offset:.4f}")
        ts_end_var   = tk.StringVar(value=f"{ar.source_offset + ar.length:.4f}")
        ts_start_e = ctk.CTkEntry(ts_row, textvariable=ts_start_var, width=90,
                                   fg_color=CLR_CARD, text_color=CLR_TEXT, font=FONT_MONO)
        ts_start_e.pack(side="left", padx=4)
        tk.Label(ts_row, text="End:", font=FONT_SMALL, fg=CLR_MUTED,
                 bg=CLR_BG).pack(side="left", padx=(8, 0))
        ts_end_e = ctk.CTkEntry(ts_row, textvariable=ts_end_var, width=90,
                                 fg_color=CLR_CARD, text_color=CLR_TEXT, font=FONT_MONO)
        ts_end_e.pack(side="left", padx=4)
        ctk.CTkButton(ts_row, text="Apply", width=60, fg_color=clr,
                      hover_color="#c73d52", font=FONT_SMALL,
                      command=lambda wi=wf, sv=ts_start_var, ev=ts_end_var:
                          self._review_apply_manual_ts(wi, sv, ev)).pack(side="left", padx=8)

        # Save button
        ctk.CTkButton(parent, text="✓  Save correction", fg_color=CLR_OK,
                      hover_color="#1e8449",
                      command=lambda gi=gidx, ri=ridx: self._review_save_correction(gi, ri)
                      ).pack(padx=8, pady=(4, 8), fill="x")

        # Store waveform + ts vars in card widget dict
        cw = self._review_card_widgets.get(gidx, {})
        rw = cw.get("row_widgets", {}).get(ridx, {})
        rw["waveform"]    = wf
        rw["ts_start_var"] = ts_start_var
        rw["ts_end_var"]   = ts_end_var
        rw["play_btn"]     = play_btn

        # Load waveform
        self._review_reload_waveform(gidx, ridx)

    # ── Selection / expand ─────────────────────────────────────────────────────

    def _review_select_row(self, gidx: str, ridx: str):
        """Toggle expanded state for a row. Collapse any previously expanded."""
        prev_ridx = self._review_sel_row
        prev_gidx = self._review_sel_group

        # Collapse previous
        if prev_ridx and prev_gidx:
            pcw = self._review_card_widgets.get(prev_gidx, {})
            prw = pcw.get("row_widgets", {}).get(prev_ridx, {})
            ef  = prw.get("expand_frame")
            if ef:
                for c in ef.winfo_children():
                    c.destroy()
                ef.pack_forget()
            outer = prw.get("outer")
            if outer:
                bg = prw.get("bg", CLR_PANEL)
                self._set_row_bg(outer, bg)

        # If clicking the same row → just collapse
        if ridx == prev_ridx and gidx == prev_gidx:
            self._review_sel_row   = None
            self._review_sel_group = None
            self._update_timeline(gidx)
            self._update_card_transcript(gidx)
            return

        # Expand new row
        self._review_sel_row   = ridx
        self._review_sel_group = gidx
        cw = self._review_card_widgets.get(gidx, {})
        rw = cw.get("row_widgets", {}).get(ridx, {})
        outer = rw.get("outer")
        ef    = rw.get("expand_frame")
        if outer:
            self._set_row_bg(outer, CLR_CARD)
        if ef:
            ef.pack(fill="x", padx=4, pady=4)
            ar = self.alignments.get(ridx)
            if ar:
                self._build_row_expand(ef, gidx, ridx, ar)

        self._update_timeline(gidx)
        self._update_card_transcript(gidx)

    # ── Waveform / playback helpers ────────────────────────────────────────────

    def _review_reload_waveform(self, gidx: str, ridx: str):
        cw  = self._review_card_widgets.get(gidx, {})
        rw  = cw.get("row_widgets", {}).get(ridx, {})
        wf  = rw.get("waveform")
        ar  = self.alignments.get(ridx)
        if not wf or not ar:
            return
        mic   = self._detail_mic.get()
        fpath = self._file_for_group(gidx, mic)
        if fpath:
            wf.load(fpath, initial_start=ar.source_offset,
                    initial_end=ar.source_offset + ar.length)

    def _file_for_group(self, gidx: str, mic: str) -> Optional[str]:
        """Return filepath for a group+mic, falling back through variants."""
        g = next((g for g in self.display_groups if g["index"] == gidx), None)
        if not g:
            return None
        for m in [mic, "4060", "4061", "416"]:
            p = g.get(f"{m}_path")
            if p:
                if m != mic:
                    self._detail_mic.set(m)
                return p
        return None

    def _on_review_waveform_change(self, gidx: str, ridx: str,
                                   start: float, end: float):
        """Waveform handle moved → update timestamps, timeline, transcript."""
        ar = self.alignments.get(ridx)
        if not ar:
            return
        ar.source_offset = start
        ar.length        = max(0.01, end - start)

        cw = self._review_card_widgets.get(gidx, {})
        rw = cw.get("row_widgets", {}).get(ridx, {})
        sv = rw.get("ts_start_var")
        ev = rw.get("ts_end_var")
        if sv:
            sv.set(f"{start:.4f}")
        if ev:
            ev.set(f"{end:.4f}")

        self._update_timeline(gidx)
        self._update_card_transcript(gidx)

    def _review_apply_manual_ts(self, wf, start_var, end_var):
        try:
            s = float(start_var.get())
            e = float(end_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Enter numeric seconds.")
            return
        wf.set_selection(s, e)

    def _review_play(self, gidx: str, ridx: str):
        cw    = self._review_card_widgets.get(gidx, {})
        rw    = cw.get("row_widgets", {}).get(ridx, {})
        wf    = rw.get("waveform")
        pbtn  = rw.get("play_btn")
        mic   = self._detail_mic.get()
        fpath = self._file_for_group(gidx, mic)
        if not fpath:
            messagebox.showwarning("No file", f"No {mic} file for group {gidx}.")
            return
        s, e = wf.get_selection() if wf else (0, 0)
        if pbtn:
            pbtn.configure(text="▶  Playing…", state="disabled")
        self._player.play(fpath, s, e - s,
                         on_done=lambda b=pbtn: self.after(0, lambda: b.configure(
                             text="▶  Play", state="normal") if b else None))

    def _review_save_correction(self, gidx: str, ridx: str):
        cw = self._review_card_widgets.get(gidx, {})
        rw = cw.get("row_widgets", {}).get(ridx, {})
        wf = rw.get("waveform")
        ar = self.alignments.get(ridx)
        if not ar or not wf:
            return
        s, e = wf.get_selection()
        ar.source_offset = s
        ar.length        = max(0.01, e - s)
        ar.needs_review  = False
        ar.confidence    = max(ar.confidence, 3)
        self._update_timeline(gidx)
        self._update_card_transcript(gidx)
        # Refresh the row summary label
        self._update_card_rows(gidx)
        # Re-expand the row after refresh
        self._review_sel_row   = ridx
        self._review_sel_group = gidx
        cw2 = self._review_card_widgets.get(gidx, {})
        rw2 = cw2.get("row_widgets", {}).get(ridx, {})
        outer = rw2.get("outer")
        ef    = rw2.get("expand_frame")
        if outer:
            self._set_row_bg(outer, CLR_CARD)
        if ef:
            ef.pack(fill="x", padx=4, pady=4)
            self._build_row_expand(ef, gidx, ridx, ar)

    # ── Word click ─────────────────────────────────────────────────────────────

    def _on_word_click(self, gidx: str, word_idx: int):
        """Snap nearest handle of the expanded row to this word's timestamp."""
        ridx = self._review_sel_row
        if not ridx or self._review_sel_group != gidx:
            return
        words = self.word_data.get(gidx, [])
        if word_idx >= len(words):
            return
        wd  = words[word_idx]
        ar  = self.alignments.get(ridx)
        cw  = self._review_card_widgets.get(gidx, {})
        rw  = cw.get("row_widgets", {}).get(ridx, {})
        wf  = rw.get("waveform")
        if not ar or not wf:
            return
        # Snap start or end depending on which is closer
        mid = (wd["start"] + wd["end"]) / 2
        cur_s = ar.source_offset
        cur_e = ar.source_offset + ar.length
        if abs(mid - cur_s) <= abs(mid - cur_e):
            wf.set_selection(wd["start"], cur_e)
        else:
            wf.set_selection(cur_s, wd["end"])

    # ── Transcription ──────────────────────────────────────────────────────────

    def _review_transcribe_all(self):
        self._run_review_transcription(self.display_groups)

    def _review_retranscribe_selected(self):
        sel = [g for g in self.display_groups
               if self._review_sel_var.get(g["index"], tk.BooleanVar()).get()]
        if not sel:
            messagebox.showinfo("Nothing selected",
                                "Tick group checkboxes to re-transcribe.")
            return
        self._run_review_transcription(sel)

    def _review_transcribe_one(self, gidx: str):
        g = next((g for g in self.display_groups if g["index"] == gidx), None)
        if g:
            self._run_review_transcription([g])

    def _run_review_transcription(self, groups):
        """
        Transcribe groups sequentially in a single background thread.
        Whisper is not safe to run in multiple threads simultaneously —
        parallel workers race on model loading and the first job loses.
        """
        model = self.whisper_model.get()
        total = len(groups)

        # Mark all queued immediately so the UI reflects pending state
        for g in groups:
            gidx = g["index"]
            cw   = self._review_card_widgets.get(gidx, {})
            ref  = g.get("4060_path") or g.get("4061_path") or g.get("416_path")
            if not ref:
                if cw.get("st_lbl"):
                    cw["st_lbl"].configure(text="no audio", text_color=CLR_WARN)
            else:
                if cw.get("st_lbl"):
                    cw["st_lbl"].configure(text="queued…", text_color=CLR_MUTED)

        def run_sequence():
            done = 0
            for g in groups:
                gidx     = g["index"]
                ref_file = g.get("4060_path") or g.get("4061_path") or g.get("416_path")
                if not ref_file:
                    done += 1
                    continue

                # Update status on UI thread
                self.after(0, lambda gi=gidx: (
                    self._review_card_widgets.get(gi, {}).get("st_lbl") and
                    self._review_card_widgets[gi]["st_lbl"].configure(
                        text="transcribing…", text_color=CLR_MUTED)
                ))

                try:
                    def progress_cb(msg, gi=gidx):
                        self.after(0, lambda m=msg, g2=gi: (
                            self._review_card_widgets.get(g2, {}).get("st_lbl") and
                            self._review_card_widgets[g2]["st_lbl"].configure(
                                text=m[:30], text_color=CLR_MUTED)
                        ))

                    text, words = transcribe(ref_file, model_name=model,
                                             progress_cb=progress_cb)
                    done += 1
                    # Use a real function — dict.update() returns None so
                    # chaining with `or` would silently skip everything after it
                    def _on_done(gi=gidx, t=text, w=words, d=done):
                        self.transcripts[gi] = t
                        self.word_data[gi]   = w
                        self._update_card_transcript(gi)
                        self._review_progress.configure(text=f"{d}/{total} done")
                    self.after(0, _on_done)

                except Exception as exc:
                    done += 1
                    err_msg = str(exc)
                    self.after(0, lambda gi=gidx, m=err_msg, d=done: (
                        self._review_card_widgets.get(gi, {}).get("st_lbl") and
                        self._review_card_widgets[gi]["st_lbl"].configure(
                            text="✗ error", text_color=CLR_ERR) or
                        self._review_progress.configure(text=f"{d}/{total} done  (last: ✗ {m[:40]})")
                    ))

        threading.Thread(target=run_sequence, daemon=True).start()

    def _review_run_alignment(self):
        if not self.word_data:
            messagebox.showwarning("Not ready",
                                   "Transcribe at least one group first.")
            return
        if not self.rows:
            messagebox.showwarning("Not ready", "No spreadsheet rows loaded.")
            return

        self._review_progress.configure(text="Aligning…", text_color=CLR_MUTED)

        # Snapshot data needed by the worker so we don't touch live state
        rows_snapshot       = list(self.rows)
        word_data_snapshot  = dict(self.word_data)
        display_groups_snap = list(self.display_groups)

        def _run():
            # Offset each group's timestamps by a large per-group delta so
            # words from different files don't share the same time range.
            # This makes source_offset globally unique across groups, which
            # lets _ar_belongs_to_group reliably identify the owning group.
            OFFSET_STEP = 100_000.0   # 100 000 s gap — far beyond any real file
            all_words   = []
            group_offsets: Dict[str, float] = {}

            for i, (gidx, words) in enumerate(word_data_snapshot.items()):
                offset = i * OFFSET_STEP
                group_offsets[gidx] = offset
                for wd in words:
                    tagged = dict(wd)
                    tagged["start"]  = wd["start"]  + offset
                    tagged["end"]    = wd["end"]    + offset
                    tagged["_group"] = gidx
                    all_words.append(tagged)

            all_words.sort(key=lambda w: w["start"])

            COMBINED     = "_all"
            row_to_group = {row["index"]: COMBINED for row in rows_snapshot}

            results = align_all(
                rows=rows_snapshot,
                group_word_map={COMBINED: all_words},
                row_to_group=row_to_group,
            )

            def _apply(res=results, r2g=row_to_group, dg=display_groups_snap,
                       aw=all_words, go=group_offsets):
                self.alignments        = {r.row_index: r for r in res}
                self.row_to_group      = r2g
                self._combined_words   = aw      # stored for _ar_belongs_to_group
                self._group_offsets    = go      # stored for waveform seek (de-offset)

                # De-offset source_offset back to file-relative seconds
                for ar in self.alignments.values():
                    gidx_of_ar = self._alignment_group(ar)
                    if gidx_of_ar and gidx_of_ar in go:
                        ar.source_offset = max(0.0, ar.source_offset - go[gidx_of_ar])
                        for take in ar.takes:
                            take.start_sec = max(0.0, take.start_sec - go[gidx_of_ar])
                            take.end_sec   = max(0.0, take.end_sec   - go[gidx_of_ar])

                for g in dg:
                    gi = g["index"]
                    self._update_card_rows(gi)
                    self._update_timeline(gi)
                    self._update_card_transcript(gi)
                self._review_progress.configure(
                    text=f"✓ Aligned {len(self.alignments)} rows",
                    text_color=CLR_OK)

            self.after(0, _apply)

        threading.Thread(target=_run, daemon=True).start()


    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 4 – Generate
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_generate_tab(self, parent):
        parent.configure(fg_color=CLR_BG)
        scroll = ctk.CTkScrollableFrame(parent, fg_color=CLR_BG)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        sec = self._section(scroll, "🎛  Session Settings")

        def _field(lbl, var, ph=""):
            f = ctk.CTkFrame(sec, fg_color="transparent")
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(f, text=lbl, font=FONT_BODY, width=190,
                         text_color=CLR_TEXT, anchor="w").pack(side="left")
            ctk.CTkEntry(f, textvariable=var, width=360,
                         fg_color=CLR_CARD, text_color=CLR_TEXT,
                         placeholder_text=ph).pack(side="left", padx=8)

        _field("Project name:", self.project_name, "Session")

        of = ctk.CTkFrame(sec, fg_color="transparent")
        of.pack(fill="x", pady=4)
        ctk.CTkLabel(of, text="Output .RPP path:", font=FONT_BODY, width=190,
                     text_color=CLR_TEXT, anchor="w").pack(side="left")
        ctk.CTkEntry(of, textvariable=self.output_rpp, width=360,
                     fg_color=CLR_CARD, text_color=CLR_TEXT).pack(side="left", padx=8)
        ctk.CTkButton(of, text="…", width=36, fg_color=CLR_CARD,
                      hover_color=CLR_ACCENT,
                      command=self._browse_rpp).pack(side="left", padx=4)

        self._gen_summary = ctk.CTkLabel(scroll, text="", font=FONT_BODY,
                                         text_color=CLR_MUTED, justify="left")
        self._gen_summary.pack(anchor="w", padx=4, pady=8)

        ctk.CTkButton(scroll, text="🎬  Generate Reaper Session (.RPP)",
                      fg_color=CLR_ACCENT, hover_color="#c73d52",
                      font=FONT_HEADING, height=48,
                      command=self._generate).pack(pady=14, anchor="e", padx=4)

        self._gen_result = ctk.CTkLabel(scroll, text="", font=FONT_BODY,
                                        text_color=CLR_OK, justify="left")
        self._gen_result.pack(anchor="w", padx=4)

        # Hook tab changes: wrap the original segmented button command so
        # CTk's own tab-switching still fires, then we also get our callback.
        try:
            _orig_tab_cmd = self.tabs._segmented_button.cget("command")
            def _tab_changed(name):
                try:
                    if _orig_tab_cmd:
                        _orig_tab_cmd(name)
                except Exception:
                    pass
                self._on_tab_change(name)
            self.tabs._segmented_button.configure(command=_tab_changed)
        except Exception:
            pass   # If CTk internals change, tabs still work, we just lose the callback


    # ═══════════════════════════════════════════════════════════════════════════
    # Coverage Review Popup
    # ═══════════════════════════════════════════════════════════════════════════

    def _refresh_all_review_cards(self):
        """Refresh row list + timeline for every group card currently rendered."""
        for gidx in list(self._review_card_widgets.keys()):
            self._update_card_rows(gidx)
            self._update_timeline(gidx)
            self._update_card_transcript(gidx)

    def _open_coverage_popup(self):
        """Open the full spreadsheet coverage review popup."""
        # Only one instance allowed
        if self._coverage_popup and self._coverage_popup.winfo_exists():
            self._coverage_popup.lift()
            return

        pop = tk.Toplevel(self)
        pop.title("Coverage Review")
        pop.geometry("1100x780")
        pop.configure(bg=CLR_BG)
        pop.minsize(900, 600)
        self._coverage_popup = pop

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(pop, bg=CLR_PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Coverage Review",
                 font=FONT_HEADING, fg=CLR_ACCENT, bg=CLR_PANEL).pack(
                 side="left", padx=16, pady=10)

        # Live stats label
        stats_lbl = tk.Label(hdr, text="", font=FONT_SMALL,
                             fg=CLR_MUTED, bg=CLR_PANEL)
        stats_lbl.pack(side="right", padx=16)

        def _refresh_stats():
            total     = len(self.rows)
            confirmed = sum(1 for r in self.rows
                            if r["index"] in self.alignments
                            and not self.alignments[r["index"]].needs_review)
            low       = sum(1 for r in self.rows
                            if r["index"] in self.alignments
                            and self.alignments[r["index"]].needs_review)
            missing   = sum(1 for r in self.rows if r["index"] not in self.alignments)
            skipped   = len(self.skipped_rows)
            stats_lbl.configure(
                text=f"Total: {total}   ✓ {confirmed}   ⚠ {low}   ✗ {missing}   ⊘ {skipped}")

        _refresh_stats()

        # ── Scrollable body ───────────────────────────────────────────────────
        body_frame = tk.Frame(pop, bg=CLR_BG)
        body_frame.pack(fill="both", expand=True)

        canvas   = tk.Canvas(body_frame, bg=CLR_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(body_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=CLR_BG)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_resize(e):
            canvas.itemconfig(inner_id, width=e.width)
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        # Mouse-wheel scrolling
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        pop.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Build sections ────────────────────────────────────────────────────
        # We store per-row expand state here (ridx → Frame or None)
        _expand_frames: Dict[str, Optional[tk.Frame]] = {}
        _expanded: Dict[str, bool] = {}

        def _section_header(text, colour):
            f = tk.Frame(inner, bg=CLR_PANEL)
            f.pack(fill="x", padx=8, pady=(10, 2))
            tk.Label(f, text=text, font=FONT_HEADING,
                     fg=colour, bg=CLR_PANEL).pack(anchor="w", padx=12, pady=6)
            return f   # caller uses this as jump anchor

        def _build_popup_row(parent_frame, row, ar, status):
            """
            Build one row card in the popup.
            status: "confirmed" | "low" | "missing" | "skipped"
            """
            ridx    = row["index"]
            row_num = row.get("row_number", "")
            clr     = self._row_color(ridx)

            bg_map  = {
                "confirmed": "#0a1a0a",
                "low":       "#1a1200",
                "missing":   "#1a0808",
                "skipped":   "#111118",
            }
            bg = bg_map.get(status, CLR_BG)

            card = tk.Frame(parent_frame, bg=bg, relief="flat")
            card.pack(fill="x", padx=8, pady=2)

            stripe = tk.Frame(card, bg=clr, width=4)
            stripe.pack(side="left", fill="y")

            body = tk.Frame(card, bg=bg)
            body.pack(side="left", fill="x", expand=True, padx=6, pady=4)

            # Summary line
            top = tk.Frame(body, bg=bg)
            top.pack(fill="x")

            def _lbl(f, text, fg, fnt=FONT_BODY, anchor="w"):
                tk.Label(f, text=text, font=fnt, fg=fg,
                         bg=bg, anchor=anchor).pack(side="left", padx=3)

            display_idx = row.get("base_index", ridx)
            _lbl(top, f"#{row_num}", "#4a5568",  FONT_MONO)
            _lbl(top, display_idx,   CLR_MUTED,  FONT_MONO)

            if ar:
                conf_clr = CONF_COLORS.get(ar.confidence, CLR_MUTED)
                _lbl(top, CONF_LABELS[ar.confidence], conf_clr, FONT_SMALL)
                _lbl(top, self._trunc(ar.line_text,   40), CLR_TEXT)
                _lbl(top, "→", CLR_MUTED, FONT_SMALL)
                match_clr = CLR_OK if status == "confirmed" else (
                            CLR_WARN if status == "low" else CLR_ERR)
                _lbl(top, self._trunc(ar.matched_text, 40), match_clr)
                _lbl(top, f"{ar.source_offset:.2f}+{ar.length:.2f}s",
                     CLR_MUTED, FONT_MONO)
            else:
                _lbl(top, self._trunc(row["line_text"], 60), CLR_MUTED)
                status_txt = "⊘ skipped" if ridx in self.skipped_rows else "✗ not found"
                _lbl(top, status_txt, CLR_ERR, FONT_SMALL)

            # Action buttons (right side)
            actions = tk.Frame(card, bg=bg)
            actions.pack(side="right", padx=8, pady=4)

            expand_holder = tk.Frame(body, bg=bg)

            def _toggle_assign(ri=ridx, eh=expand_holder, row_=row):
                if _expanded.get(ri):
                    # Collapse
                    for child in eh.winfo_children():
                        child.destroy()
                    _expanded[ri] = False
                else:
                    # Expand: build manual assign panel
                    _expanded[ri] = True
                    _build_assign_panel(eh, row_, ri)
                    eh.pack(fill="x", pady=(4, 0))
                _refresh_stats()

            def _confirm_row(ri=ridx, row_=row):
                _ar = self.alignments.get(ri)
                if not _ar:
                    return
                _ar.needs_review = False
                _ar.confidence   = max(_ar.confidence, 3)
                self.skipped_rows.discard(ri)
                # Refresh main review tab (all groups)
                self._refresh_all_review_cards()
                # Refresh popup card
                card.destroy()
                _build_popup_row(parent_frame, row_, _ar, "confirmed")
                _refresh_stats()

            def _remove_row(ri=ridx, row_=row):
                self.alignments.pop(ri, None)
                self.skipped_rows.add(ri)
                # Refresh main review tab (all groups)
                self._refresh_all_review_cards()
                card.destroy()
                _build_popup_row(parent_frame, row_, None, "skipped")
                _refresh_stats()

            def _restore_row(ri=ridx, row_=row):
                self.skipped_rows.discard(ri)
                self._refresh_all_review_cards()
                card.destroy()
                _build_popup_row(parent_frame, row_, None, "missing")
                _refresh_stats()

            if status in ("low", "confirmed"):
                ctk.CTkButton(actions, text="✓ Confirm", width=80, height=24,
                              fg_color=CLR_OK, hover_color="#1e8449",
                              font=FONT_SMALL,
                              command=_confirm_row).pack(side="left", padx=2)

            if status in ("missing", "low", "confirmed"):
                ctk.CTkButton(actions, text="✎ Assign", width=76, height=24,
                              fg_color=CLR_CARD, hover_color="#1f5080",
                              font=FONT_SMALL,
                              command=_toggle_assign).pack(side="left", padx=2)

            if status in ("low", "confirmed", "missing"):
                ctk.CTkButton(actions, text="✕ Remove", width=76, height=24,
                              fg_color="#3a1a1a", hover_color=CLR_ERR,
                              font=FONT_SMALL,
                              command=_remove_row).pack(side="left", padx=2)

            if status == "skipped":
                ctk.CTkButton(actions, text="↩ Restore", width=80, height=24,
                              fg_color=CLR_CARD, hover_color="#1f5080",
                              font=FONT_SMALL,
                              command=_restore_row).pack(side="left", padx=2)

        # ── Manual assign panel ───────────────────────────────────────────────

        def _build_assign_panel(parent, row, ridx):
            """
            Builds an inline manual assignment panel showing the group
            transcript with word colouring. User clicks words to set
            start/end, or types timestamps directly.
            """
            clr = self._row_color(ridx)
            bg  = "#0a0e18"

            panel = tk.Frame(parent, bg=bg, relief="ridge", bd=1)
            panel.pack(fill="x", padx=4, pady=4)

            # Find which group this row probably belongs to based on
            # existing alignment (or first available group as fallback)
            ar = self.alignments.get(ridx)
            gidx = self._alignment_group(ar) if ar else None
            if not gidx and self.display_groups:
                gidx = self.display_groups[0]["index"]

            # ── Transcript with word-click ─────────────────────────────────
            tk.Label(panel, text="Click words to set start  /  double-click to set end:",
                     font=FONT_SMALL, fg=CLR_MUTED, bg=bg).pack(anchor="w", padx=8, pady=(6,2))

            tx_frame = tk.Frame(panel, bg=bg)
            tx_frame.pack(fill="x", padx=8, pady=2)

            tx = tk.Text(tx_frame, font=FONT_MONO, bg="#0d1117", fg=CLR_TEXT,
                         height=4, wrap="word", cursor="arrow",
                         relief="flat", bd=0, padx=6, pady=4)
            tx.pack(fill="x")

            # Track selected range
            _sel = {"start": None, "end": None}
            ts_start_var = tk.StringVar(value="0.0000")
            ts_end_var   = tk.StringVar(value="0.0000")

            # Pre-fill from existing alignment
            if ar:
                ts_start_var.set(f"{ar.source_offset:.4f}")
                ts_end_var.set(f"{ar.source_offset + ar.length:.4f}")
                _sel["start"] = ar.source_offset
                _sel["end"]   = ar.source_offset + ar.length

            # Build coloured word text from gidx transcript
            words = self.word_data.get(gidx, []) if gidx else []
            word_colors = self._compute_word_colors(gidx) if gidx else {}

            tx.configure(state="normal")
            tx.delete("1.0", "end")

            for wi, wd in enumerate(words):
                tag = f"w{wi}"
                wclr = word_colors.get(wi, CLR_MUTED)
                # Highlight the currently selected range
                if (_sel["start"] is not None and _sel["end"] is not None
                        and _sel["start"] <= wd["start"] <= _sel["end"]):
                    wclr = clr
                tx.insert("end", wd["word"] + " ", tag)
                tx.tag_configure(tag, foreground=wclr)

                def _click_word(e, wi_=wi, wd_=wd):
                    _sel["start"] = wd_["start"]
                    ts_start_var.set(f"{wd_['start']:.4f}")
                    # If end not set yet or is before start, auto-set end
                    cur_end = _sel.get("end")
                    if cur_end is None or cur_end < wd_["start"]:
                        _sel["end"] = wd_["end"]
                        ts_end_var.set(f"{wd_['end']:.4f}")
                    _recolour()

                def _dbl_word(e, wi_=wi, wd_=wd):
                    _sel["end"] = wd_["end"]
                    ts_end_var.set(f"{wd_['end']:.4f}")
                    _recolour()

                tx.tag_bind(tag, "<Button-1>",       _click_word)
                tx.tag_bind(tag, "<Double-Button-1>", _dbl_word)
                tx.tag_bind(tag, "<Enter>",
                            lambda e, t=tag: tx.tag_configure(t, underline=True))
                tx.tag_bind(tag, "<Leave>",
                            lambda e, t=tag: tx.tag_configure(t, underline=False))

            tx.configure(state="disabled")

            def _recolour():
                """Re-colour transcript to show selected range."""
                tx.configure(state="normal")
                s = _sel.get("start")
                e = _sel.get("end")
                for wi_, wd_ in enumerate(words):
                    tag_ = f"w{wi_}"
                    base = word_colors.get(wi_, CLR_MUTED)
                    if s is not None and e is not None and s <= wd_["start"] <= e:
                        tx.tag_configure(tag_, foreground=clr, font=(FONT_MONO[0], FONT_MONO[1], "bold"))
                    else:
                        tx.tag_configure(tag_, foreground=base, font=FONT_MONO)
                tx.configure(state="disabled")

            # ── Timestamp entry row ────────────────────────────────────────
            ts_row = tk.Frame(panel, bg=bg)
            ts_row.pack(fill="x", padx=8, pady=4)

            tk.Label(ts_row, text="Start:", font=FONT_SMALL,
                     fg=CLR_MUTED, bg=bg).pack(side="left")
            ctk.CTkEntry(ts_row, textvariable=ts_start_var, width=90,
                         fg_color=CLR_CARD, text_color=CLR_TEXT,
                         font=FONT_MONO).pack(side="left", padx=4)
            tk.Label(ts_row, text="End:", font=FONT_SMALL,
                     fg=CLR_MUTED, bg=bg).pack(side="left", padx=(8,0))
            ctk.CTkEntry(ts_row, textvariable=ts_end_var, width=90,
                         fg_color=CLR_CARD, text_color=CLR_TEXT,
                         font=FONT_MONO).pack(side="left", padx=4)

            def _apply_ts():
                try:
                    s = float(ts_start_var.get())
                    e = float(ts_end_var.get())
                    if e > s:
                        _sel["start"] = s
                        _sel["end"]   = e
                        _recolour()
                except ValueError:
                    pass

            ctk.CTkButton(ts_row, text="Apply", width=60,
                          fg_color=clr, hover_color="#c73d52",
                          font=FONT_SMALL,
                          command=_apply_ts).pack(side="left", padx=8)

            # ── Save button ────────────────────────────────────────────────
            def _save_assign():
                try:
                    s = float(ts_start_var.get())
                    e = float(ts_end_var.get())
                except ValueError:
                    messagebox.showerror("Invalid", "Enter valid start/end times.",
                                         parent=pop)
                    return
                if e <= s:
                    messagebox.showerror("Invalid",
                                         "End must be after start.", parent=pop)
                    return

                # Build or update AlignmentResult
                existing = self.alignments.get(ridx)
                if existing:
                    existing.source_offset = s
                    existing.length        = max(0.01, e - s)
                    existing.needs_review  = False
                    existing.confidence    = max(existing.confidence, 3)
                else:
                    # Create a synthetic AlignmentResult for a manually assigned row
                    from .aligner import AlignmentResult as AR
                    self.alignments[ridx] = AR(
                        row_index     = ridx,
                        output_name   = row.get("output_name", ridx),
                        line_text     = row.get("line_text", ""),
                        matched_text  = f"[manual @ {s:.2f}s]",
                        source_offset = s,
                        length        = max(0.01, e - s),
                        confidence    = 3,
                        needs_review  = False,
                        take_count    = 1,
                    )
                    # Store group assignment so RPP generator can find the file
                    if gidx:
                        self.row_to_group[ridx] = "_all"

                self.skipped_rows.discard(ridx)

                # Refresh main review tab (all groups)
                self._refresh_all_review_cards()

                # Rebuild popup row
                par = panel.master.master   # expand_holder → body → card parent
                panel.master.destroy()      # collapse expand_holder
                _expanded[ridx] = False
                _refresh_stats()
                messagebox.showinfo("Saved",
                    f"Alignment for '{ridx}' saved: {s:.2f}s -> {e:.2f}s",
                    parent=pop)

            ctk.CTkButton(panel, text="✓  Save manual alignment",
                          fg_color=CLR_OK, hover_color="#1e8449",
                          command=_save_assign).pack(fill="x", padx=8, pady=(4,8))

        # ── Categorise all rows ───────────────────────────────────────────────
        confirmed_rows, low_rows, missing_rows, skipped_rows_list = [], [], [], []

        for row in self.rows:
            ridx = row["index"]
            ar   = self.alignments.get(ridx)
            if ridx in self.skipped_rows:
                skipped_rows_list.append((row, ar))
            elif not ar or not ar.takes:
                missing_rows.append((row, ar))
            elif ar.needs_review or ar.confidence <= 2:
                low_rows.append((row, ar))
            else:
                confirmed_rows.append((row, ar))

        if not any([confirmed_rows, low_rows, missing_rows, skipped_rows_list]):
            tk.Label(inner, text="No rows loaded. Run alignment first.",
                     font=FONT_BODY, fg=CLR_MUTED, bg=CLR_BG).pack(pady=30)
            return

        # ── Jump-nav bar ──────────────────────────────────────────────────────
        nav = tk.Frame(inner, bg=CLR_PANEL)
        nav.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(nav, text="Jump to:", font=FONT_SMALL,
                 fg=CLR_MUTED, bg=CLR_PANEL).pack(side="left", padx=8)

        # section_anchors: label widget → canvas y position (filled after build)
        _anchors: Dict[str, tk.Widget] = {}

        def _jump(key):
            anchor = _anchors.get(key)
            if not anchor:
                return
            inner.update_idletasks()
            # Get y position of anchor relative to inner frame
            y = anchor.winfo_y()
            total_h = inner.winfo_height()
            canvas_h = canvas.winfo_height()
            frac = y / max(1, total_h - canvas_h)
            canvas.yview_moveto(max(0.0, min(1.0, frac)))

        nav_btns = []
        if confirmed_rows:
            b = ctk.CTkButton(nav, text=f"✓ {len(confirmed_rows)}", width=60, height=22,
                              fg_color=CLR_OK, hover_color="#1e8449", font=FONT_SMALL,
                              command=lambda: _jump("confirmed"))
            b.pack(side="left", padx=3, pady=4)
        if low_rows:
            b = ctk.CTkButton(nav, text=f"⚠ {len(low_rows)}", width=60, height=22,
                              fg_color="#7a5a00", hover_color="#b07800", font=FONT_SMALL,
                              command=lambda: _jump("low"))
            b.pack(side="left", padx=3, pady=4)
        if missing_rows:
            b = ctk.CTkButton(nav, text=f"✗ {len(missing_rows)}", width=60, height=22,
                              fg_color="#5a1a1a", hover_color=CLR_ERR, font=FONT_SMALL,
                              command=lambda: _jump("missing"))
            b.pack(side="left", padx=3, pady=4)
        if skipped_rows_list:
            b = ctk.CTkButton(nav, text=f"⊘ {len(skipped_rows_list)}", width=60, height=22,
                              fg_color=CLR_CARD, hover_color=CLR_MUTED, font=FONT_SMALL,
                              command=lambda: _jump("skipped"))
            b.pack(side="left", padx=3, pady=4)

        # ── Build sections in order: problems first ───────────────────────────
        def _add_section(key, label, colour, rows_list):
            hdr_widget = _section_header(label, colour)
            _anchors[key] = hdr_widget
            for row, ar in rows_list:
                status = key
                _build_popup_row(inner, row, ar, status)

        # Problems first so they're immediately visible
        if low_rows:
            _add_section("low",       f"⚠  Low confidence / needs review  ({len(low_rows)})",      CLR_WARN,  low_rows)
        if missing_rows:
            _add_section("missing",   f"✗  Not found  ({len(missing_rows)})",                       CLR_ERR,   missing_rows)
        if skipped_rows_list:
            _add_section("skipped",   f"⊘  Skipped / removed  ({len(skipped_rows_list)})",          CLR_MUTED, skipped_rows_list)
        if confirmed_rows:
            _add_section("confirmed", f"✓  Confirmed  ({len(confirmed_rows)})",                     CLR_OK,    confirmed_rows)

        # Auto-scroll to first problem section after layout settles
        def _auto_scroll():
            first_key = next((k for k in ["low", "missing", "skipped"] if k in _anchors), None)
            if first_key:
                _jump(first_key)
        pop.after(150, _auto_scroll)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = tk.Frame(pop, bg=CLR_PANEL)
        footer.pack(fill="x", side="bottom")
        ctk.CTkButton(footer, text="Close",
                      fg_color=CLR_CARD, hover_color=CLR_ACCENT,
                      command=pop.destroy).pack(side="right", padx=12, pady=8)
        ctk.CTkButton(footer, text="🎬  Generate RPP now",
                      fg_color=CLR_ACCENT, hover_color="#c73d52",
                      command=lambda: [pop.destroy(), self._generate()]
                      ).pack(side="right", padx=6, pady=8)

    def _on_tab_change(self, name):
        if name == "4 · Generate":
            try:
                total   = len(self.rows)
                aligned = len(self.alignments)
                review  = sum(1 for a in self.alignments.values() if a.needs_review)
                skipped = len(self.skipped_rows)
                self._gen_summary.configure(text=(
                    f"  Rows:              {total}\n"
                    f"  Aligned:           {aligned}\n"
                    f"  Needs review:      {review}\n"
                    f"  Skipped:           {skipped}\n"
                    f"  Ready:             {aligned - review}\n"
                ))
            except Exception:
                pass

    def _browse_rpp(self):
        p = filedialog.asksaveasfilename(defaultextension=".rpp",
            filetypes=[("Reaper project", "*.rpp"), ("All", "*.*")])
        if p:
            self.output_rpp.set(p)

    def _generate(self):
        if not self.rows:
            messagebox.showerror("Error", "No rows loaded.")
            return
        out = self.output_rpp.get().strip()
        if not out:
            messagebox.showerror("Error", "Choose an output .RPP path.")
            return
        # Build cuts from alignments
        cuts = {ar.row_index: (ar.source_offset, ar.length)
                for ar in self.alignments.values()}
        # Build file_groups keyed by row index.
        # row_to_group maps everything to "_all" (combined transcription),
        # so we resolve the real group via _alignment_group(ar) instead.
        row_file_groups = {}
        for row in self.rows:
            ridx = row["index"]
            ar = self.alignments.get(ridx)
            if ar is None:
                continue
            gidx = self._alignment_group(ar)
            if gidx and gidx in self.file_groups:
                row_file_groups[ridx] = self.file_groups[gidx]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        try:
            result = build_session(rows=self.rows, file_groups=row_file_groups,
                                   cuts=cuts, output_path=out,
                                   project_name=self.project_name.get() or "Session")
            self._gen_result.configure(text=f"✓ Written: {result}", text_color=CLR_OK)
            messagebox.showinfo("Done", f"Session written:\n{result}")
        except Exception as e:
            self._gen_result.configure(text=f"✗ {e}", text_color=CLR_ERR)
            messagebox.showerror("Error", str(e))


    def _stop_playback(self):
        self._player.stop()

    # ═══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════════════════
    def _section(self, parent, title):
        outer = ctk.CTkFrame(parent, fg_color=CLR_PANEL, corner_radius=8)
        outer.pack(fill="x", pady=6, padx=2)
        ctk.CTkLabel(outer, text=title, font=FONT_HEADING,
                     text_color=CLR_ACCENT).pack(anchor="w", padx=14, pady=(10,4))
        inner = ctk.CTkFrame(outer, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=(0,10))
        return inner

    @staticmethod
    def _trunc(s, n):
        return (s[:n] + "…") if len(s) > n else s

    @staticmethod
    def _hex(colour: str) -> str:
        """Return colour as-is (already hex). Exists for clarity."""
        return colour

    @staticmethod
    def _set_row_bg(frame, colour: str):
        """Set background of a tk.Frame and all its label children."""
        try:
            frame.configure(bg=colour)
            for child in frame.winfo_children():
                try:
                    child.configure(bg=colour)
                except Exception:
                    pass
        except Exception:
            pass


def _nearest_index(ridx: str, group_indices: list) -> Optional[str]:
    """Find the group index numerically nearest to ridx."""
    if not group_indices:
        return None
    if ridx in group_indices:
        return ridx
    try:
        ri = int(ridx)
        best = min(group_indices, key=lambda g: abs(int(g) - ri) if g.isdigit() else 9999)
        return best
    except (ValueError, TypeError):
        return group_indices[0]
