#!/usr/bin/env python3
"""Master pipeline: InstantSplat per-timestep 4D reconstruction.

This replaces the entire COLMAP → restructure → 4DGS pipeline with:
  InstantSplat (MASt3R + Gaussian Splatting) × 80 timesteps

Usage:
    # Full pipeline (organize + reconstruct + collect)
    python3 pipeline_instantsplat.py --instantsplat-dir /workspace/InstantSplat

    # Test on just 3 frames first
    python3 pipeline_instantsplat.py --instantsplat-dir /workspace/InstantSplat --end 3

    # Resume from where you left off (skips completed timesteps)
    python3 pipeline_instantsplat.py --instantsplat-dir /workspace/InstantSplat
"""

import argparse
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="InstantSplat per-timestep 4D reconstruction pipeline")
    parser.add_argument("--scene-images", type=str, default="scene/images",
                        help="Path to scene/images/ with cam01-04/")
    parser.add_argument("--instantsplat-dir", type=str, default="/workspace/InstantSplat",
                        help="Path to InstantSplat clone")
    parser.add_argument("--viewer-dir", type=str, default="viewer",
                        help="Path to viewer/ directory")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--start", type=int, default=1,
                        help="First timestep (1-indexed)")
    parser.add_argument("--end", type=int, default=None,
                        help="Last timestep (default: all)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--skip-organize", action="store_true",
                        help="Skip step 1 if already organized")
    parser.add_argument("--skip-reconstruct", action="store_true",
                        help="Skip step 2 (just collect existing outputs)")
    args = parser.parse_args()

    pipeline_start = time.time()

    print("=" * 60)
    print("  REPLAY — InstantSplat Per-Timestep 4D Pipeline")
    print("=" * 60)
    print()

    input_dir = Path("instantsplat_input")
    output_dir = Path("instantsplat_output")

    # ── Step 1: Organize ─────────────────────────────────────────────
    if not args.skip_organize:
        print("STEP 1/3: Organizing frames into per-timestep folders...")
        from organize_timesteps import organize
        num_timesteps = organize(args.scene_images, str(input_dir), symlink=False)
        print()
    else:
        num_timesteps = len(list(input_dir.glob("t_*")))
        print(f"STEP 1/3: Skipped (found {num_timesteps} existing timestep folders)")
        print()

    # ── Step 2: Reconstruct ──────────────────────────────────────────
    if not args.skip_reconstruct:
        print("STEP 2/3: Running InstantSplat on each timestep...")
        from run_instantsplat import run_all
        succeeded, failed = run_all(
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            instantsplat_dir=args.instantsplat_dir,
            gpu_id=args.gpu,
            start=args.start,
            end=args.end,
        )
        if succeeded == 0:
            print("[FAIL] No timesteps succeeded. Check InstantSplat installation.")
            sys.exit(1)
        print()
    else:
        print("STEP 2/3: Skipped reconstruction")
        print()

    # ── Step 3: Collect for viewer ───────────────────────────────────
    print("STEP 3/3: Collecting PLY files for viewer...")
    from collect_for_viewer import collect
    collect(str(output_dir), args.viewer_dir, args.fps)

    elapsed = time.time() - pipeline_start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print()
    print("=" * 60)
    print(f"  PIPELINE COMPLETE — {mins}m {secs}s")
    print()
    print(f"  What changed vs. the old pipeline:")
    print(f"    OLD: COLMAP (1% match rate) → 3 viewpoints → garbage")
    print(f"    NEW: MASt3R (per-timestep) → 4 views × 80 timesteps → full 4D")
    print()
    print(f"  To view: cd viewer && npm run dev")
    print("=" * 60)


if __name__ == "__main__":
    main()
