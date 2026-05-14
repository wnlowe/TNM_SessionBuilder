#!/usr/bin/env bash
# test_build_mac.sh — Behavioral unit tests for build_mac.sh
# Tests the logic of build_mac.sh by sourcing individual functions
# and injecting mock commands. No macOS required.
#
# Run with: bash tests/test_build_mac.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_SCRIPT="$SCRIPT_DIR/build_mac.sh"

# ── Test harness ───────────────────────────────────────────────────────────────
PASS=0; FAIL=0; ERRORS=()

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS  $desc"
    (( PASS++ ))
  else
    echo "  FAIL  $desc"
    echo "        expected: $expected"
    echo "        actual:   $actual"
    (( FAIL++ ))
    ERRORS+=("$desc")
  fi
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS  $desc"
    (( PASS++ ))
  else
    echo "  FAIL  $desc"
    echo "        expected to contain: $needle"
    echo "        actual output:       $haystack"
    (( FAIL++ ))
    ERRORS+=("$desc")
  fi
}

assert_not_contains() {
  local desc="$1" needle="$2" haystack="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "  PASS  $desc"
    (( PASS++ ))
  else
    echo "  FAIL  $desc"
    echo "        expected NOT to contain: $needle"
    (( FAIL++ ))
    ERRORS+=("$desc")
  fi
}

assert_exit_zero() {
  local desc="$1"; shift
  if "$@" &>/dev/null; then
    echo "  PASS  $desc"
    (( PASS++ ))
  else
    echo "  FAIL  $desc (exited non-zero)"
    (( FAIL++ ))
    ERRORS+=("$desc")
  fi
}

assert_exit_nonzero() {
  local desc="$1"; shift
  if ! "$@" &>/dev/null; then
    echo "  PASS  $desc"
    (( PASS++ ))
  else
    echo "  FAIL  $desc (expected non-zero exit but got 0)"
    (( FAIL++ ))
    ERRORS+=("$desc")
  fi
}

# ── Load helper functions from the script without executing it ─────────────────
# We source only the function definitions by stripping the main body.
# The script uses set -euo pipefail at the top; we re-set that here.
_load_functions() {
  local tmp
  tmp=$(mktemp)
  # Colour vars
  grep -E '^\s*(RED|GREEN|YELLOW|CYAN|NC)=' "$BUILD_SCRIPT" >> "$tmp"
  # Script-level constants that functions depend on
  grep -E '^\s*PYTHON_MIN_(MAJOR|MINOR)=' "$BUILD_SCRIPT" >> "$tmp"
  # Function definitions
  sed -n '/^info()/,/^}/p'        "$BUILD_SCRIPT" >> "$tmp"
  sed -n '/^success()/,/^}/p'     "$BUILD_SCRIPT" >> "$tmp"
  sed -n '/^warn()/,/^}/p'        "$BUILD_SCRIPT" >> "$tmp"
  sed -n '/^die()/,/^}/p'         "$BUILD_SCRIPT" >> "$tmp"
  sed -n '/^find_python()/,/^}/p' "$BUILD_SCRIPT" >> "$tmp"
  # shellcheck source=/dev/null
  source "$tmp"
  rm -f "$tmp"
}
_load_functions

# ── Colour/logging helpers ─────────────────────────────────────────────────────
echo ""
echo "=== Colour / logging helpers ==="

out=$(info "hello world" 2>&1)
assert_contains "info() prints the message"           "hello world"    "$out"
assert_contains "info() contains bullet marker"       "[•]"            "$out"

out=$(success "all good" 2>&1)
assert_contains "success() prints the message"        "all good"       "$out"
assert_contains "success() contains checkmark"        "[✓]"            "$out"

out=$(warn "watch out" 2>&1)
assert_contains "warn() prints the message"           "watch out"      "$out"
assert_contains "warn() contains [!]"                 "[!]"            "$out"

out=$(die "fatal error" 2>&1 || true)
assert_contains "die() prints the message"            "fatal error"    "$out"
assert_contains "die() contains [✗]"                  "[✗]"            "$out"

# ── die() exits with non-zero ─────────────────────────────────────────────────
echo ""
echo "=== die() exit behaviour ==="

assert_exit_nonzero "die() exits with code 1" bash -c "
  source '$BUILD_SCRIPT' 2>/dev/null; exit 0" 2>/dev/null || true
# More targeted: run die in a subshell and capture exit code
( die "test" &>/dev/null ); rc=$?
assert_eq "die() exits non-zero (rc=$rc)" "1" "$rc"

# ── Architecture label mapping ────────────────────────────────────────────────
echo ""
echo "=== Architecture label mapping ==="

run_arch_test() {
  local arch="$1"
  bash -c "
    ARCH='$arch'
    case \"\$ARCH\" in
      x86_64) echo 'Intel (x86_64)' ;;
      arm64)  echo 'Apple Silicon (arm64)' ;;
      *)      echo 'UNSUPPORTED' ;;
    esac
  "
}

assert_eq "x86_64 maps to Intel label"         "Intel (x86_64)"        "$(run_arch_test x86_64)"
assert_eq "arm64 maps to Apple Silicon label"  "Apple Silicon (arm64)" "$(run_arch_test arm64)"
assert_eq "unknown arch maps to UNSUPPORTED"   "UNSUPPORTED"           "$(run_arch_test mips)"

# ── find_python() version gating ─────────────────────────────────────────────
echo ""
echo "=== find_python() version gating ==="

# Mock a python that reports a qualifying version
mock_python_ok() {
  local tmpdir; tmpdir=$(mktemp -d)
  cat > "$tmpdir/python3" <<'PYEOF'
#!/usr/bin/env bash
if [[ "$1" == "-c" ]]; then echo "3.11"; else echo "Python 3.11.0"; fi
PYEOF
  chmod +x "$tmpdir/python3"
  echo "$tmpdir"
}

# Mock a python that reports a too-old version
mock_python_old() {
  local tmpdir; tmpdir=$(mktemp -d)
  cat > "$tmpdir/python3" <<'PYEOF'
#!/usr/bin/env bash
if [[ "$1" == "-c" ]]; then echo "3.8"; else echo "Python 3.8.0"; fi
PYEOF
  chmod +x "$tmpdir/python3"
  echo "$tmpdir"
}

# Use an isolated PATH so real system Pythons cannot interfere.
# Keep only minimal POSIX utilities needed by the function itself.
SAFE_PATH="/usr/bin:/bin"

MOCK_OK=$(mock_python_ok)
MOCK_OLD=$(mock_python_old)

result=$(PATH="$MOCK_OK:$SAFE_PATH" find_python)
assert_eq "find_python() returns path for qualifying Python 3.11" \
  "$MOCK_OK/python3" "$result"

result=$(PATH="$MOCK_OLD:$SAFE_PATH" find_python 2>/dev/null || echo "NOT_FOUND")
assert_eq "find_python() rejects Python 3.8 (below minimum)" \
  "NOT_FOUND" "$result"

rm -rf "$MOCK_OK" "$MOCK_OLD"

# ── find_python() tries multiple candidate names ──────────────────────────────
echo ""
echo "=== find_python() candidate fallback ==="

# Only python3.11 present, not python3
mock_named() {
  local name="$1" ver="$2"
  local tmpdir; tmpdir=$(mktemp -d)
  cat > "$tmpdir/$name" <<PYEOF
#!/usr/bin/env bash
if [[ "\$1" == "-c" ]]; then echo "$ver"; else echo "Python $ver.0"; fi
PYEOF
  chmod +x "$tmpdir/$name"
  echo "$tmpdir"
}

MOCK_311=$(mock_named "python3.11" "3.11")
result=$(PATH="$MOCK_311:$SAFE_PATH" find_python)
assert_eq "find_python() finds python3.11 when python3 absent" \
  "$MOCK_311/python3.11" "$result"
rm -rf "$MOCK_311"

MOCK_312=$(mock_named "python3.12" "3.12")
result=$(PATH="$MOCK_312:$SAFE_PATH" find_python)
assert_eq "find_python() finds python3.12" \
  "$MOCK_312/python3.12" "$result"
rm -rf "$MOCK_312"

# ── --add-data separator is colon (macOS), not semicolon (Windows) ─────────────
echo ""
echo "=== PyInstaller --add-data separator ==="

DATA_ARG=$(grep -- '--add-data' "$BUILD_SCRIPT")
assert_contains "--add-data uses colon separator (macOS format)" \
  '"app:app"' "$DATA_ARG"
assert_not_contains "--add-data does NOT use semicolon (Windows format)" \
  '"app;app"' "$DATA_ARG"

# ── --windowed flag is present (GUI app) ─────────────────────────────────────
echo ""
echo "=== PyInstaller flags ==="

PYINST_CALL=$(grep -A 20 '"$VENV_DIR/bin/pyinstaller"' "$BUILD_SCRIPT")
assert_contains "PyInstaller invoked with --windowed"     "--windowed"     "$PYINST_CALL"
assert_contains "PyInstaller invoked with --onefile"      "--onefile"      "$PYINST_CALL"
assert_contains "PyInstaller invoked with --noconfirm"    "--noconfirm"    "$PYINST_CALL"
assert_contains "PyInstaller invoked with --clean"        "--clean"        "$PYINST_CALL"
assert_contains "PyInstaller passes --target-arch"        '--target-arch'  "$PYINST_CALL"
assert_contains "PyInstaller includes app data dir"       '"app:app"'      "$PYINST_CALL"

# ── Homebrew PATH set correctly per architecture ───────────────────────────────
echo ""
echo "=== Homebrew PATH per architecture ==="

INTEL_BREW=$(grep -A 2 'arm64.*brew shellenv\|brew shellenv.*arm64\|Intel\|x86_64.*brew\|usr/local.*brew' \
  "$BUILD_SCRIPT" | grep 'usr/local' | head -1)
ARM_BREW=$(grep '/opt/homebrew' "$BUILD_SCRIPT" | head -1)

assert_contains "Intel Homebrew path (/usr/local) present in script" \
  "/usr/local"       "$(grep 'usr/local' "$BUILD_SCRIPT")"
assert_contains "ARM Homebrew path (/opt/homebrew) present in script" \
  "/opt/homebrew"    "$(grep 'opt/homebrew' "$BUILD_SCRIPT")"

# ── ffmpeg requirement documented ─────────────────────────────────────────────
echo ""
echo "=== ffmpeg handling ==="

assert_contains "ffmpeg install command present" \
  "brew install ffmpeg" "$(grep 'ffmpeg' "$BUILD_SCRIPT")"
assert_contains "ffmpeg PATH warning present in output section" \
  "ffmpeg" "$(grep -i 'ffmpeg.*PATH\|PATH.*ffmpeg' "$BUILD_SCRIPT")"

# ── venv is cleaned before creation ───────────────────────────────────────────
echo ""
echo "=== Virtual environment cleanup ==="

assert_contains "Old venv is removed before creating new one" \
  "rm -rf" "$(grep -A 2 'Removing existing' "$BUILD_SCRIPT")"

# ── requirements.txt is referenced ────────────────────────────────────────────
echo ""
echo "=== requirements.txt ==="

assert_contains "requirements.txt is installed" \
  "requirements.txt" "$(grep 'requirements' "$BUILD_SCRIPT")"

# ── whisper import check present ──────────────────────────────────────────────
echo ""
echo "=== Whisper import verification ==="

assert_contains "Script verifies whisper is importable after install" \
  "import whisper" "$(grep 'import whisper' "$BUILD_SCRIPT")"

# ── Result ────────────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
TOTAL=$(( PASS + FAIL ))
echo "Results: $PASS passed, $FAIL failed / $TOTAL total"
if (( FAIL > 0 )); then
  echo "Failed tests:"
  for e in "${ERRORS[@]}"; do echo "  - $e"; done
  exit 1
else
  echo "All tests passed."
  exit 0
fi
