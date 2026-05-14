#!/usr/bin/env bash
# build_mac.sh — Install dependencies and build ReaperSessionGenerator.app
# Works on macOS Intel (x86_64) and Apple Silicon (arm64).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-build"
APP_NAME="ReaperSessionGenerator"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[•]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
die()     { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# ── Architecture detection ─────────────────────────────────────────────────────
ARCH=$(uname -m)   # x86_64 or arm64
case "$ARCH" in
  x86_64) ARCH_LABEL="Intel (x86_64)" ;;
  arm64)  ARCH_LABEL="Apple Silicon (arm64)" ;;
  *)      die "Unsupported architecture: $ARCH" ;;
esac
info "Detected architecture: $ARCH_LABEL"

# ── Homebrew ───────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  warn "Homebrew not found. Installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Add Homebrew to PATH for Apple Silicon (it installs to /opt/homebrew)
  if [[ "$ARCH" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  success "Homebrew installed."
else
  success "Homebrew found: $(brew --prefix)"
fi

# ── ffmpeg ─────────────────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
  info "Installing ffmpeg (required by Whisper)..."
  brew install ffmpeg
  success "ffmpeg installed."
else
  success "ffmpeg found: $(command -v ffmpeg)"
fi

# ── Python ─────────────────────────────────────────────────────────────────────
find_python() {
  for candidate in python3 python3.12 python3.11 python3.10; do
    if cmd=$(command -v "$candidate" 2>/dev/null); then
      ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
      major=${ver%%.*}; minor=${ver##*.}
      if (( major > PYTHON_MIN_MAJOR || (major == PYTHON_MIN_MAJOR && minor >= PYTHON_MIN_MINOR) )); then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

if ! PYTHON=$(find_python); then
  warn "Python $PYTHON_MIN_MAJOR.$PYTHON_MIN_MINOR+ not found. Installing via Homebrew..."
  brew install python@3.12
  hash -r
  PYTHON=$(find_python) || die "Python install succeeded but executable not found. Open a new terminal and re-run."
fi
PY_VER=$("$PYTHON" --version)
success "Using Python: $PYTHON ($PY_VER)"

# ── Check for tkinter support ──────────────────────────────────────────────────
if ! "$PYTHON" -c "import tkinter" &>/dev/null; then
  warn "tkinter not found in $PYTHON."
  info "Installing python-tk via Homebrew..."
  # Determine the Python version for the tk formula
  PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  brew install python-tk@"$PY_VER" 2>/dev/null || brew install python-tk 2>/dev/null || \
    die "Could not install tkinter. Try: brew install python-tk@3.12"
  # Retry finding Python with tkinter
  PYTHON=$(find_python) || die "Python not found after tk install."
  "$PYTHON" -c "import tkinter" || die "tkinter still not available. Install Python from python.org which bundles Tk."
fi
success "tkinter is available."

# ── Virtual environment ────────────────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
  info "Removing existing virtual environment..."
  rm -rf "$VENV_DIR"
fi
info "Creating virtual environment at $VENV_DIR ..."
"$PYTHON" -m venv "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
success "Virtual environment created."

# ── Upgrade pip ────────────────────────────────────────────────────────────────
info "Upgrading pip..."
"$VENV_PIP" install --quiet --upgrade pip

# ── Install project dependencies ───────────────────────────────────────────────
info "Installing project dependencies (this may take a while — Whisper + PyTorch are large)..."
"$VENV_PIP" install --upgrade -r "$SCRIPT_DIR/requirements.txt"
success "Project dependencies installed."

# ── Install PyInstaller ────────────────────────────────────────────────────────
info "Installing PyInstaller..."
"$VENV_PIP" install --upgrade pyinstaller
success "PyInstaller installed."

# ── Check Whisper is importable ────────────────────────────────────────────────
"$VENV_PYTHON" -c "import whisper" 2>/dev/null \
  || die "openai-whisper failed to import. Check the install output above."
success "openai-whisper importable."

# ── Build ──────────────────────────────────────────────────────────────────────
info "Building $APP_NAME.app for $ARCH_LABEL ..."
cd "$SCRIPT_DIR"

"$VENV_DIR/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --name "$APP_NAME" \
  --windowed \
  --onefile \
  --add-data "app:app" \
  --target-arch "$ARCH" \
  main.py

# ── Result ─────────────────────────────────────────────────────────────────────
EXE_PATH="$SCRIPT_DIR/dist/$APP_NAME"
APP_PATH="$SCRIPT_DIR/dist/$APP_NAME.app"

if [[ -f "$EXE_PATH" ]]; then
  SIZE=$(du -sh "$EXE_PATH" | cut -f1)
  success "Build complete!"
  echo ""
  echo -e "  Executable : ${GREEN}$EXE_PATH${NC}  ($SIZE)"
  [[ -d "$APP_PATH" ]] && echo -e "  App bundle : ${GREEN}$APP_PATH${NC}"
  echo ""
  echo -e "  Architecture : $ARCH_LABEL"
  echo -e "  Run with     : open \"$APP_PATH\"  or  \"$EXE_PATH\""
  echo ""
  warn "Note: ffmpeg must be on PATH when running the app (it is now via Homebrew)."
  warn "If you move the app to another machine, install ffmpeg there too."
else
  die "Build failed — $EXE_PATH not found. Check PyInstaller output above."
fi
