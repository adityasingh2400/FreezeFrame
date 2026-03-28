#!/usr/bin/env python3
"""Collect InstantSplat output PLYs into the viewer's expected format.

Reads:  instantsplat_output/time_00000.ply ... time_00079.ply
Writes: viewer/public/frames/time_00000.ply ... time_00079.ply
        viewer/public/manifest.json
"""

import argparse
import json
import shutil
import time
from pathlib import Path


def collect(output_dir, viewer_dir, fps=30):
    output_dir = Path(output_dir)
    viewer_dir = Path(viewer_dir)
    frames_dir = viewer_dir / "public" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    ply_files = sorted(output_dir.glob("time_*.ply"))
    if not ply_files:
        print(f"[FAIL] No time_*.ply files in {output_dir}")
        raise SystemExit(1)

    print(f"Found {len(ply_files)} PLY files in {output_dir}")

    filenames = []
    total_size = 0
    for ply in ply_files:
        dst = frames_dir / ply.name
        shutil.copy2(str(ply), str(dst))
        filenames.append(ply.name)
        total_size += ply.stat().st_size

    hero_idx = len(filenames) // 3
    manifest = {
        "name": "Replay — InstantSplat 4D",
        "frames": filenames,
        "fps": fps,
        "baseDir": "/frames/",
        "hero_frame": hero_idx,
        "total_frames": len(filenames),
        "pipeline": "instantsplat-per-timestep",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    manifest_path = viewer_dir / "public" / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    avg_size = total_size / len(filenames) / 1024
    print(f"\n[OK] Copied {len(filenames)} PLY files to {frames_dir}")
    print(f"     Total size: {total_size / 1024 / 1024:.1f} MB ({avg_size:.0f} KB avg)")
    print(f"     Manifest: {manifest_path}")
    print(f"     FPS: {fps}, Hero frame: {hero_idx}")
    print(f"\n     Run the viewer: cd viewer && npm run dev")


def main():
    parser = argparse.ArgumentParser(
        description="Collect InstantSplat PLYs into viewer format")
    parser.add_argument("--output-dir", type=str, default="instantsplat_output",
                        help="Directory with time_*.ply files")
    parser.add_argument("--viewer-dir", type=str, default="viewer",
                        help="Path to the viewer/ directory")
    parser.add_argument("--fps", type=int, default=30,
                        help="Playback FPS for the viewer")
    args = parser.parse_args()
    collect(args.output_dir, args.viewer_dir, args.fps)


if __name__ == "__main__":
    main()
