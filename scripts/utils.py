"""Shared utilities for all pipeline stages."""

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: make setup")
    sys.exit(1)


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"


def load_config() -> dict:
    """Load and return the project config with all paths resolved to absolute."""
    if not CONFIG_PATH.exists():
        print(f"ERROR: config.yaml not found at {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    return cfg


def resolve_path(relative_path: str) -> Path:
    """Resolve a config-relative path to an absolute path from project root."""
    return ROOT_DIR / relative_path


def require_file(path: Path, label: str):
    """Exit with a clear message if a required file is missing."""
    if not path.exists():
        print(f"FAIL: {label} — expected file at {path}")
        sys.exit(1)


def require_dir(path: Path, label: str):
    """Exit with a clear message if a required directory is missing."""
    if not path.is_dir():
        print(f"FAIL: {label} — expected directory at {path}")
        sys.exit(1)
