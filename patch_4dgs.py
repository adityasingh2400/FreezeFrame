#!/usr/bin/env python3
"""Patch 4DGaussians source for headless RunPod containers.

Applies minimal, targeted fixes so 4DGS runs on containers that lack
tkinter, have stale system Python packages, etc. Each patch is
idempotent — safe to run multiple times.

Run AFTER cloning 4DGaussians, BEFORE training.
"""

import re
import sys
from pathlib import Path


def patch_file(path, old, new, description):
    """Replace exact string in file. Idempotent: skips if already patched."""
    p = Path(path)
    if not p.exists():
        print(f"  SKIP {p} (not found)")
        return False
    content = p.read_text()
    if new in content:
        print(f"  OK   {description} (already patched)")
        return True
    if old not in content:
        print(f"  WARN {description} (old string not found)")
        return False
    content = content.replace(old, new)
    p.write_text(content)
    print(f"  FIXED {description}")
    return True


def patch_deformation_tkinter(fourdgs_dir):
    """Replace `from tkinter import W` with a constant.

    The imported W is immediately shadowed by the class parameter W=256,
    so the tkinter value is never used. Safe to replace with any string.
    """
    patch_file(
        fourdgs_dir / "scene" / "deformation.py",
        "from tkinter import W",
        'W = "w"  # patched: tkinter unavailable in headless containers',
        "deformation.py: tkinter → constant",
    )


def patch_mmcv_config(fourdgs_dir):
    """Replace mmcv.Config.fromfile with a stdlib equivalent.

    mmcv is a heavy dependency that often has version conflicts.
    Config.fromfile() just exec()s a Python file and collects its globals,
    which we can do with importlib.
    """
    config_shim = fourdgs_dir / "utils" / "config_shim.py"
    if not config_shim.exists():
        config_shim.write_text('''\
"""Minimal replacement for mmcv.Config.fromfile().

Loads a Python config file and exposes its top-level variables
as attributes/dict keys, exactly like mmcv.Config does.
"""

import importlib.util
import sys
from pathlib import Path


class Config(dict):
    """Dict subclass with attribute access, mimicking mmcv.Config."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def keys(self):
        return super().keys()

    @staticmethod
    def fromfile(filepath):
        filepath = str(Path(filepath).resolve())
        spec = importlib.util.spec_from_file_location("_config", filepath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = Config()
        for key, value in mod.__dict__.items():
            if not key.startswith("_"):
                cfg[key] = value
        return cfg
''')
        print("  FIXED created config_shim.py (mmcv replacement)")
    else:
        print("  OK   config_shim.py already exists")

    for script in ["train.py", "render.py", "export_perframe_3DGS.py", "merge_many_4dgs.py"]:
        path = fourdgs_dir / script
        if not path.exists():
            continue
        patch_file(
            path,
            "import mmcv",
            "from utils.config_shim import Config as _Config  # patched: mmcv replacement",
            f"{script}: mmcv import",
        )
        patch_file(
            path,
            "mmcv.Config.fromfile",
            "_Config.fromfile",
            f"{script}: mmcv.Config.fromfile call",
        )


def main():
    if len(sys.argv) > 1:
        fourdgs_dir = Path(sys.argv[1])
    else:
        fourdgs_dir = Path(__file__).resolve().parent / "4DGaussians"

    print(f"Patching 4DGaussians at {fourdgs_dir}")
    print()

    print("[1/2] Patching tkinter import...")
    patch_deformation_tkinter(fourdgs_dir)
    print()

    print("[2/2] Replacing mmcv.Config with stdlib shim...")
    patch_mmcv_config(fourdgs_dir)
    print()

    print("All patches applied. Verifying imports...")
    # Quick smoke test
    sys.path.insert(0, str(fourdgs_dir))
    try:
        from utils.config_shim import Config
        print("  OK   config_shim imports")
    except Exception as e:
        print(f"  FAIL config_shim: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
