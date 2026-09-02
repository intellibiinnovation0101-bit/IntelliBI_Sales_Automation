"""
================================================================================
  IntelliBI Sales Automation — runtime bootstrap  (common/_bootstrap.py)
  ------------------------------------------------------------------------------
  Imported as the very first project import by every entry script and every
  runner.  It makes the moved scripts run from any folder on any machine by:

    1. Putting  common/  and  credentials/  on sys.path so the shared modules
       (utils, interakt_common, exotel_common, email_config, ...) import by
       name exactly as they did when everything lived in one flat folder.
    2. Seeding environment-variable *defaults* (only when not already set) for
       every override the scripts already honour — service account, output,
       cache, temp and history locations — all anchored to PROJECT_ROOT.
    3. Loading config/config.yaml (if present) and exporting the operator's
       settings (sheet IDs, toggles, email, ...) into the same env vars, so a
       single YAML file configures the whole pipeline without editing code.
    4. Creating the writable working folders.

  Import side-effect only:   `import _bootstrap`   (no functions to call).
================================================================================
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Force UTF-8 on this process's stdout/stderr ──────────────────────────────
# Log/console output across the pipeline contains arrows (→), check-marks (✓),
# ↳ and similar. In a UTF-8 console / PyCharm those print fine, but under
# Windows Task Scheduler (or a legacy cp1252 console) Python defaults stdout and
# stderr to the OS code page, which cannot encode them — every such line then
# raises 'charmap' UnicodeEncodeError and kills the script. _bootstrap is the
# very first import in every entry script and runner, so reconfiguring the
# streams here fixes the whole pipeline in one place. reconfigure() mutates the
# existing stream in place (Python 3.7+); errors="replace" is a last-resort
# safety net so output is never fatal. The log FILE is already UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Snapshot env vars the operator set BEFORE we seed any defaults, so config.yaml
# never overrides a deliberate command-line/OS override.
_ORIGINAL_ENV_KEYS = set(os.environ)

# ── locate the project + put shared code on the import path ──────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_COMMON = _PROJECT_ROOT / "common"
_CREDENTIALS = _PROJECT_ROOT / "credentials"
_CONFIG = _PROJECT_ROOT / "config"

for _p in (str(_COMMON), str(_CREDENTIALS), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import paths  # noqa: E402  (now importable — common/ is on sys.path)

paths.ensure_dirs()


def _setdefault(key: str, value) -> None:
    if value is not None and not os.environ.get(key):
        os.environ[key] = str(value)


# ── 1. path defaults every script already understands ────────────────────────
_setdefault("GOOGLE_SERVICE_ACCOUNT_FILE", paths.CREDENTIALS_DIR / "service_account.json")
_setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])

# lead consolidation (pyConsolidateLeadsLoad.py) writes CSV/XLSX exports here
_setdefault("INTELLIBI_OUT_DIR", paths.OUTPUT_EXPORTS_DIR)
_setdefault("INTELLIBI_LOCAL_DIR", paths.OUTPUT_EXPORTS_DIR)

# report scripts
_setdefault("REPORT_OUTPUT_DIR", paths.OUTPUT_REPORTS_DIR)
_setdefault("LFA_OUTPUT_DIR", paths.OUTPUT_REPORTS_DIR)
_setdefault("LFA_HISTORY_DIR", paths.HISTORY_DIR)

# temp/cache — keep scratch inside the portable project, never the OS temp dir
_setdefault("TMPDIR", paths.TEMP_DIR)
_setdefault("TEMP", paths.TEMP_DIR)
_setdefault("TMP", paths.TEMP_DIR)

# ── 2. optional YAML config overrides everything above + carries app settings ─
try:
    import config_loader
    config_loader.apply_to_environment(_ORIGINAL_ENV_KEYS)
except Exception as _e:  # never let optional config break a run
    sys.stderr.write(f"[bootstrap] config.yaml not applied: {_e}\n")

# Expose the resolved root for scripts/tools that want it.
PROJECT_ROOT = str(_PROJECT_ROOT)
