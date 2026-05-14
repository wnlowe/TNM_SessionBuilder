"""
Reaper Session Generator
Transcribes grouped audio takes with Whisper, maps to spreadsheet lines,
and generates a .RPP Reaper session with word-level cut points.
"""

import sys
import os

# When running as a PyInstaller bundle, put the extraction dir on PATH so
# Whisper can find the bundled ffmpeg binary via subprocess.
if getattr(sys, 'frozen', False):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
