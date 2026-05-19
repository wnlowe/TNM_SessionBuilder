"""
Reaper Session Generator
Transcribes grouped audio takes with Whisper, maps to spreadsheet lines,
and generates a .RPP Reaper session with word-level cut points.
"""

import sys
import os
import multiprocessing

# macOS Python (python.org installer and PyInstaller bundles) does not trust
# the system keychain for HTTPS, so urllib fails with SSL_CERTIFICATE_VERIFY_FAILED.
# Patching _create_default_https_context with certifi's CA bundle fixes this for
# all urllib-based downloads (including whisper.load_model → torch.hub).
if sys.platform == 'darwin':
    import ssl
    import certifi
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

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
