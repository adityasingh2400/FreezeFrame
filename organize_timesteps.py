#!/usr/bin/env python3
"""Organize multi-camera frames into per-timestep folders for InstantSplat.

Takes the scene/images/cam01-04/ structure with 80 frames each and creates:
  instantsplat_input/
    t_00001/
      cam01.jpg
      cam02.jpg
      cam03.jpg
      cam04.jpg
    t_00002/
      ...
    t_00080/
      ...

Each folder = one timestep = one InstantSplat reconstruction.
"""

import argparse
import os
import shutil
from pathlib import Path


def organize(scene_images_dir, output_dir, symlink=True):
    scene_images_dir = Path(scene_images_dir)
    output_dir = Path(output_dir)

    cam_dirs = sorted([
        d for d in scene_images_dir.iterdir()
        if d.is_dir() and d.name.startswith("cam")
    ])
    if not cam_dirs:
        print(f"[FAIL] No cam* directories found in {scene_images_dir}")
        raise SystemExit(1)

    print(f"Found {len(cam_dirs)} cameras: {[d.name for d in cam_dirs]}")

    first_cam_frames = sorted(cam_dirs[0].glob("frame_*.jpg"))
    num_frames = len(first_cam_frames)
    if num_frames == 0:
        print(f"[FAIL] No frame_*.jpg files in {cam_dirs[0]}")
        raise SystemExit(1)

    print(f"Frames per camera: {num_frames}")

    for cam_dir in cam_dirs:
        count = len(list(cam_dir.glob("frame_*.jpg")))
        if count != num_frames:
            print(f"[WARN] {cam_dir.name} has {count} frames, expected {num_frames}")

    output_dir.mkdir(parents=True, exist_ok=True)
    created = 0

    for frame_idx in range(1, num_frames + 1):
        frame_name = f"frame_{frame_idx:05d}.jpg"
        timestep_dir = output_dir / f"t_{frame_idx:05d}" / "images"
        timestep_dir.mkdir(parents=True, exist_ok=True)

        for cam_dir in cam_dirs:
            src = cam_dir / frame_name
            dst = timestep_dir / f"{cam_dir.name}.jpg"

            if not src.exists():
                print(f"[WARN] Missing {src}")
                continue

            if dst.exists() or dst.is_symlink():
                dst.unlink()

            if symlink:
                os.symlink(str(src.resolve()), str(dst))
            else:
                shutil.copy2(str(src), str(dst))

        created += 1

    print(f"\n[OK] Created {created} timestep folders in {output_dir}")
    print(f"     Each contains {len(cam_dirs)} camera images")
    print(f"     Ready for InstantSplat processing")
    return created


def main():
    parser = argparse.ArgumentParser(
        description="Organize multi-camera frames into per-timestep folders")
    parser.add_argument("--scene-images", type=str, default="scene/images",
                        help="Path to scene/images/ with cam01/ cam02/ etc.")
    parser.add_argument("--output", type=str, default="instantsplat_input",
                        help="Output directory for per-timestep folders")
    parser.add_argument("--copy", action="store_true",
                        help="Copy files instead of symlinking (use on RunPod)")
    args = parser.parse_args()
    organize(args.scene_images, args.output, symlink=not args.copy)


if __name__ == "__main__":
    main()
