"""Convert PLY frames to SPZ format using gsbox.

USAGE:
  make convert   — converts output/frames/*.ply → output/frames_sog/*.spz

REQUIRES:
  gsbox binary on PATH — download from https://github.com/gotoeasy/gsbox/releases

OUTPUT:
  output/frames_sog/frame_00000.spz, frame_00001.spz, ...
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path

GSBOX = "gsbox.exe" if sys.platform == "win32" else "gsbox"


def check_deps():
    if not shutil.which(GSBOX):
        print(f"ERROR: {GSBOX} not found on PATH.")
        print("Download from: https://github.com/gotoeasy/gsbox/releases")
        print("Extract gsbox.exe and add it to your PATH.")
        sys.exit(1)


def run():
    check_deps()

    cfg = load_config()
    frames_dir = resolve_path(cfg["stage3"]["export_dir"])
    spz_dir = frames_dir.parent / "frames_sog"
    meta_path = resolve_path(cfg["stage3"]["output_meta_path"])

    if not meta_path.exists():
        print(f"ERROR: No output_meta.json at {meta_path}")
        print("Run 'make train' first.")
        sys.exit(1)

    ply_files = sorted(frames_dir.glob("frame_*.ply"))
    if not ply_files:
        print(f"ERROR: No PLY files found in {frames_dir}")
        print("Run 'make train' first.")
        sys.exit(1)

    spz_dir.mkdir(parents=True, exist_ok=True)

    total = len(ply_files)
    skipped = 0
    converted = 0

    print(f"Converting {total} PLY frames to SPZ (~10x compression)...")
    print(f"  Input:  {frames_dir}")
    print(f"  Output: {spz_dir}\n")

    for i, ply_path in enumerate(ply_files):
        spz_path = spz_dir / ply_path.with_suffix(".spz").name
        label = f"[{i + 1}/{total}] {ply_path.name}"

        if spz_path.exists():
            print(f"  {label} — skip (exists)")
            skipped += 1
            continue

        print(f"  {label} → {spz_path.name}")
        result = subprocess.run(
            [GSBOX, "ply2spz", "-i", str(ply_path), "-o", str(spz_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"\nERROR: conversion failed for {ply_path.name}")
            if result.stderr:
                print(result.stderr)
            if result.stdout:
                print(result.stdout)
            sys.exit(1)

        converted += 1

    print(f"\nDone. {converted} converted, {skipped} skipped.")
    print(f"Run 'python scripts/stage4_viewer.py' to launch the viewer.")


if __name__ == "__main__":
    run()
