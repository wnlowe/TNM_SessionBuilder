# TNM Session Builder — Developer Notes

## Project overview

Desktop GUI app (Python 3.12, CustomTkinter) that transcribes grouped audio takes
with OpenAI Whisper, maps them to spreadsheet dialogue lines, and generates a
`.RPP` Reaper session with word-level cut points.

Entry point: `main.py` → `app/gui.py` (`App` class, subclasses `ctk.CTk`).

---

## Building

### Local build (Windows)

```powershell
# Copy the real ffmpeg binary (NOT the Chocolatey shim) into assets/ first.
# `Get-Command ffmpeg` returns the shim, which breaks when moved into the bundle.
Copy-Item "C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe" assets\ffmpeg.exe -Force
py -3.12 -m pip install -r requirements.txt
py -3.12 -m PyInstaller build.spec --clean --noconfirm
dist\ReaperSessionGenerator\ReaperSessionGenerator.exe
```

**Run from a non-admin terminal.** PyInstaller 6.x warns when run as admin;
PyInstaller 7.0 will block it entirely.

### CI / GitHub Actions

Trigger from the Actions tab → **Build Mac & Windows** → Run workflow.
The `platform` input accepts `all`, `mac`, or `windows`.
Artifacts are retained for 30 days; a GitHub Release is created automatically
on version tag pushes (`v*`).

---

## PyInstaller bundling — known gotchas

### 1. `pkg_resources` startup crash (`No module named 'X'`)

**Root cause:** Modern setuptools (≥65) imports `jaraco.text`, `jaraco.functools`,
`jaraco.context`, `jaraco.collections`, `platformdirs`, and `more_itertools`
directly in `pkg_resources/__init__.py`. In a frozen app the `pkg_resources.extern`
vendor-proxy tries to load these during its own initialisation, which creates a
circular-import failure because `pkg_resources` is only partially initialised at
that point.

**Fix (three-part):**

1. **`requirements.txt`** — the jaraco/platformdirs/more-itertools packages must
   be *installed* so PyInstaller can find and bundle them:
   ```
   jaraco.text
   jaraco.functools
   jaraco.context
   jaraco.collections
   platformdirs
   more-itertools
   ```

2. **`build.spec` hiddenimports** — `collect_all('jaraco.X')` only collects
   *submodules*, not the package itself. Each package must be listed explicitly:
   ```python
   'jaraco', 'jaraco.text', 'jaraco.functools',
   'jaraco.context', 'jaraco.collections',
   'platformdirs', 'more_itertools',
   ```

3. **`hooks/rthook_pkgres_preload.py`** (runtime hook) — pre-loads all six
   packages into `sys.modules` *before* PyInstaller's built-in `pyi_rth_pkgres`
   hook runs. Once they are already in `sys.modules`, the vendor-proxy fallback
   succeeds without re-importing. Wired in via `runtime_hooks=[...]` in `build.spec`.

### 2. `jaraco` namespace package (`No module named 'jaraco'`)

`jaraco` is a PEP 420 namespace package — no `__init__.py` exists on disk.
PyInstaller's frozen importer can find `jaraco.text` etc. inside the embedded PYZ
archive, but Python's importer must first resolve the top-level `jaraco` name,
which requires a filesystem `__init__.py`.

**Fix:** `build.spec` generates a minimal stub at build time and injects it as
`_internal/jaraco/__init__.py`:
```python
_jaraco_stub_path = os.path.join(tempfile.mkdtemp(), '__init__.py')
with open(_jaraco_stub_path, 'w') as f:
    f.write('__path__ = __import__("pkgutil").extend_path(__path__, __name__)\n')
jaraco_datas = [(_jaraco_stub_path, 'jaraco')]
```

### 3. ffmpeg not found at runtime

Whisper calls ffmpeg as a subprocess. The binary must be on `PATH` inside the
frozen app.

**Build side:** CI copies the system ffmpeg to `assets/ffmpeg.exe` (Windows) or
`assets/ffmpeg` (macOS) before running PyInstaller. `build.spec` includes it as
a binary landing in the bundle root (`.`).

**Runtime side:** `main.py` prepends `sys._MEIPASS` to `PATH` when frozen:
```python
if getattr(sys, 'frozen', False):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
```

### 4. PyTorch multiprocessing on Windows

Without `multiprocessing.freeze_support()`, spawning worker processes in a
windowed (no-console) frozen app on Windows re-launches the GUI instead of
entering the worker bootstrap.

**Fix:** `main.py` calls `multiprocessing.freeze_support()` before any other code
when `sys.frozen` is true.

### 5. Window icon shows default tkinter feather

`icon=` in the PyInstaller `EXE()` block only sets the *file* icon visible in
Explorer. The *window* title-bar/taskbar icon must be set via tkinter at runtime.

**Fix:** `app/gui.py` `App._set_icon()` resolves `assets/icon.ico` (Windows) or
`assets/icon.png` (macOS) from `sys._MEIPASS` when frozen, or from the repo root
when running as a script, and calls `self.iconbitmap()` / `self.iconphoto()`.
`build.spec` bundles both files into `assets/` via `icon_datas`.

### 6. Hidden imports that do NOT exist (do not re-add)

These were removed because they are not installed and not used by the app.
Adding them causes confusing `ERROR: Hidden import 'X' not found` lines in every
build log:
- `PIL._tkinter_finder`
- `openai` (referenced only in torch internal comments, not used by the app)
- `scipy` / `scipy.signal` (same — torch testing internals only)

### 7. `collect_submodules('torch')` noise

`collect_submodules('torch')` emits dozens of `ERROR: Hidden import not found`
lines for deprecated `torch.distributed._shard.checkpoint.*` shims that were
moved in torch 2.x. This is unavoidable noise — the app still works correctly.

---

## Assets

| File | Purpose |
|---|---|
| `assets/icon.ico` | Windows exe file icon (PyInstaller) + window icon (runtime) |
| `assets/icon.png` | macOS window icon (runtime) |
| `assets/icon.icns` | macOS `.app` bundle icon (PyInstaller) |
| `assets/ffmpeg.exe` | Bundled ffmpeg — copied here by CI before PyInstaller runs |

`assets/ffmpeg.exe` is git-ignored (large binary added by CI).
