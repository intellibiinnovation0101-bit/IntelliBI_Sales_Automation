"""
================================================================================
  IntelliBI Sales Automation — central path resolver  (common/paths.py)
  ------------------------------------------------------------------------------
  EVERY path in this project is derived from PROJECT_ROOT, which is discovered
  at run time from this file's own location:

        common/paths.py   ->   parents[1]   =   <project root>

  Nothing here is machine-specific.  Copy the whole IntelliBI_Sales_Automation
  folder to any machine and every path still resolves, because it is always
  computed relative to where this file physically lives.

  Import this module (directly, or via `common._bootstrap`) to get canonical
  directories and helpers:

        from paths import PROJECT_ROOT, CONFIG_DIR, CREDENTIALS_DIR, \
                          CACHE_DIR, LOGS_DIR, OUTPUT_DIR, TEMP_DIR
================================================================================
"""
from __future__ import annotations

import os
from pathlib import Path

# ── project root = the folder that contains this common/ package ─────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# ── layer / source folders ───────────────────────────────────────────────────
LAYER1_DIR = PROJECT_ROOT / "sales_data_collection"
LAYER2_DIR = PROJECT_ROOT / "sales_consolidation"
LAYER3_DIR = PROJECT_ROOT / "sales_reports"
COMMON_DIR = PROJECT_ROOT / "common"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# ── configuration & secrets ──────────────────────────────────────────────────
CONFIG_DIR = PROJECT_ROOT / "config"            # config.yaml, logging_config.yaml, mapping overrides
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"  # service account, cookies, tokens, email_config.py

# ── working / output folders ─────────────────────────────────────────────────
CACHE_DIR = PROJECT_ROOT / "cache"
LOGS_DIR = PROJECT_ROOT / "logs"
TEMP_DIR = PROJECT_ROOT / "temp"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_REPORTS_DIR = OUTPUT_DIR / "reports"
OUTPUT_EXPORTS_DIR = OUTPUT_DIR / "exports"

# ── optional historical training data for the conversion model ───────────────
HISTORY_DIR = PROJECT_ROOT / "intellibi_lead_cycle"

# Directories that must exist for the pipeline to write into. (config/credentials
# are expected to be provisioned by the operator, so they are not force-created.)
_ENSURE = (CACHE_DIR, LOGS_DIR, TEMP_DIR, OUTPUT_DIR,
           OUTPUT_REPORTS_DIR, OUTPUT_EXPORTS_DIR, HISTORY_DIR)


def ensure_dirs() -> None:
    """Create the writable working folders if they are missing (idempotent)."""
    for d in _ENSURE:
        d.mkdir(parents=True, exist_ok=True)


# Filenames that are configuration overrides (kept in config/, safe to commit).
# Everything else resolved through cfg() is treated as a secret (credentials/).
_CONFIG_FILE_NAMES = {
    "notes_field_mapping.json",
    "website_field_mapping.json",
    "intellibi_field_mapping.json",
    "technology_mapping.json",
    "course_technologies_mapping.json",
}


def cfg(name: str) -> str:
    """Resolve a legacy ``config_files/<name>`` reference to its new home.

    Mapping/override JSONs live in ``config/``; credentials, cookies, tokens,
    browser profiles and runtime auth caches live in ``credentials/``.  Returns
    an absolute path string (the file need not exist yet — callers handle that,
    exactly as they did when the store was named ``config_files/``).
    """
    base = CONFIG_DIR if name in _CONFIG_FILE_NAMES else CREDENTIALS_DIR
    return str(base / name)


def as_str(p) -> str:
    return str(p)
