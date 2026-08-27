"""
================================================================================
  IntelliBI Sales Automation — configuration loader  (common/config_loader.py)
  ------------------------------------------------------------------------------
  ONE centralized configuration mechanism for the whole pipeline.

  Reads  config/config.yaml  and:
    * exposes it as a plain dict via  load()  /  get("a.b.c", default)
    * maps operator settings onto the environment variables the existing
      scripts already understand (so no business logic had to change), via
      apply_to_environment().

  Precedence (highest first):
    1. A variable already set in the real OS environment (operator ad-hoc run)
    2. A value provided in config/config.yaml
    3. The project-root path defaults seeded by common/_bootstrap.py

  YAML is optional.  If PyYAML is not installed or the file is absent, the
  pipeline still runs on the path defaults — nothing raises.
================================================================================
"""
from __future__ import annotations

import os
from pathlib import Path

import paths  # common/ is on sys.path via _bootstrap

CONFIG_YAML = paths.CONFIG_DIR / "config.yaml"

# config.yaml dotted-key  ->  environment variable the scripts read
_KEY_TO_ENV = {
    "google.service_account_file":            "GOOGLE_SERVICE_ACCOUNT_FILE",
    "consolidation.input_mode":               "INTELLIBI_INPUT_MODE",
    "consolidation.target_sheet_id":          "INTELLIBI_TARGET_SHEET_ID",
    "consolidation.lead_type_map_sheet_id":   "INTELLIBI_LEAD_TYPE_MAP_SHEET_ID",
    "consolidation.export_dir":               "INTELLIBI_OUT_DIR",
    "reports.output_dir":                     "REPORT_OUTPUT_DIR",
    "reports.followup_output_dir":            "LFA_OUTPUT_DIR",
    "reports.history_dir":                    "LFA_HISTORY_DIR",
    "reports.dry_run":                        "REPORT_DRY_RUN",
    "reports.followup_dry_run":               "LFA_DRY_RUN",
    "interakt.api_key":                       "INTERAKT_API_KEY",
    "interakt.load_mode":                     "INTERAKT_LOAD_MODE",
    "exotel.api_key":                         "EXOTEL_API_KEY",
    "exotel.api_token":                       "EXOTEL_API_TOKEN",
    "exotel.sid":                             "EXOTEL_SID",
    "exotel.subdomain":                       "EXOTEL_SUBDOMAIN",
    "exotel.load_mode":                       "EXOTEL_LOAD_MODE",
}

_PATH_VALUED_ENV = {  # values that name a file/folder are resolved under the project
    "GOOGLE_SERVICE_ACCOUNT_FILE": paths.CREDENTIALS_DIR,
    "INTELLIBI_OUT_DIR": paths.PROJECT_ROOT,
    "REPORT_OUTPUT_DIR": paths.PROJECT_ROOT,
    "LFA_OUTPUT_DIR": paths.PROJECT_ROOT,
    "LFA_HISTORY_DIR": paths.PROJECT_ROOT,
}

_cache = None


def load() -> dict:
    """Return config.yaml as a dict (cached).  {} if missing/unparseable."""
    global _cache
    if _cache is not None:
        return _cache
    data = {}
    if CONFIG_YAML.exists():
        try:
            import yaml
            with open(CONFIG_YAML, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as e:  # missing PyYAML or bad YAML -> run on defaults
            import sys
            sys.stderr.write(f"[config_loader] could not read config.yaml: {e}\n")
            data = {}
    _cache = data if isinstance(data, dict) else {}
    return _cache


def get(dotted: str, default=None):
    """Fetch a nested value, e.g. get('email.log_recipients', [])."""
    node = load()
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def _resolve_pathish(env_key: str, value: str) -> str:
    base = _PATH_VALUED_ENV.get(env_key)
    if base is None:
        return value
    p = Path(str(value)).expanduser()
    return str(p if p.is_absolute() else (base / str(value)))


def apply_to_environment(original_keys=None) -> None:
    """Map config.yaml settings onto environment variables.

    original_keys: the set of env-var names present BEFORE the bootstrap ran;
    those represent a deliberate operator override and are never touched.
    """
    original_keys = original_keys or set()
    cfg = load()
    if not cfg:
        return
    for dotted, env_key in _KEY_TO_ENV.items():
        if env_key in original_keys:
            continue  # operator set it explicitly on the command line/OS
        val = get(dotted, None)
        if val is None or val == "":
            continue
        os.environ[env_key] = _resolve_pathish(env_key, val)
