"""
Reaper Session Generator
Transcribes grouped audio takes with Whisper, maps to spreadsheet lines,
and generates a .RPP Reaper session with word-level cut points.
"""

import sys
import os
import multiprocessing

if getattr(sys, 'frozen', False):
    # Required on Windows so PyTorch worker-process spawns re-enter the
    # freeze bootstrap rather than re-launching the GUI.
    multiprocessing.freeze_support()
    # Put the bundle dir on PATH so Whisper's ffmpeg subprocess call resolves
    # to the bundled binary.
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
