"""
spreadsheet.py
Loads an XLSX and exposes the data. Column mapping is done at runtime
by the user via the GUI — we just provide helpers to read/inspect.
"""

from __future__ import annotations
import pandas as pd
from typing import List, Optional, Tuple


class SpreadsheetData:
    def __init__(self, path: str):
        self.path = path
        self.df: pd.DataFrame = pd.DataFrame()
        self.columns: List[str] = []
        self._load()

    def _load(self):
        self.df = pd.read_excel(self.path, dtype=str)
        self.df = self.df.fillna("")
        # Strip leading/trailing whitespace from all string columns
        for col in self.df.columns:
            self.df[col] = self.df[col].str.strip()
        self.columns = list(self.df.columns)

    def preview(self, n: int = 5) -> pd.DataFrame:
        return self.df.head(n)

    def get_rows(
        self,
        index_col: str,
        output_name_col: str,
        line_text_col: str,
        character_col: Optional[str] = None,
        character_filter: Optional[str] = None,
    ) -> List[dict]:
        """
        Return list of dicts with normalised keys:
          index, output_name, line_text, character (may be "")
        Optionally filter to a single character value.
        """
        rows = []
        seen_indices: dict = {}   # index → first row_number seen (for dedup tracking)
        for row_number, row in self.df.iterrows():
            char = row[character_col].strip() if character_col and character_col in row else ""
            if character_filter and character_col:
                if char.lower() != character_filter.lower():
                    continue
            idx = row[index_col].strip()

            # Each spreadsheet row becomes its own entry. Duplicate index values
            # are allowed — the aligner handles them. We give each a unique
            # internal key so the GUI can display and track them individually.
            # Rows with the same index share one AlignmentResult (keyed by idx).
            occurrence = seen_indices.get(idx, 0)
            seen_indices[idx] = occurrence + 1
            # For the first occurrence keep the plain idx; subsequent ones get
            # a suffix so they are distinct keys but still sort together.
            unique_key = idx if occurrence == 0 else f"{idx}#{occurrence}"

            rows.append({
                "index":      unique_key,
                "base_index": idx,            # original spreadsheet value
                "row_number": row_number + 2, # 1-based + header row
                "output_name": row[output_name_col].strip(),
                "line_text":   row[line_text_col].strip(),
                "character":   char,
            })
        return rows

    def unique_characters(self, character_col: str) -> List[str]:
        if character_col not in self.df.columns:
            return []
        return sorted(self.df[character_col].dropna().unique().tolist())
