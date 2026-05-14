"""
Reaper Session Generator
Transcribes grouped audio takes with Whisper, maps to spreadsheet lines,
and generates a .RPP Reaper session with word-level cut points.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
