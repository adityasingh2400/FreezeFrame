#!/usr/bin/env python3
"""Master pipeline: VGGT per-timestep 4D reconstruction.

Replaces pipeline_instantsplat.py — uses VGGT instead of MASt3R for ~225x
faster initialization. VGGT processes all views in a single forward pass.

Usage:
    # Full pipeline (organize + reconstruct + collect)
    python3 pipeline_vggt.py

    # Fast mode: VGGT-only, no Gaussian training (~12s for 80 timesteps)
    python3 pipeline_vggt.py --mode fast

    # Test on just 3 frames first
    python3 pipeline_vggt.py --end 3

    # Resume from where you left off (skips completed timesteps)
    python3 pipeline_vggt.py
"""

import argparse
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="VGGT per-timestep 4D reconstruction pipeline")
    parser.add_argument("--scene-images", type=str, default="scene/images",
                        help="Path to scene/images/ with cam01-04/")
    parser.add_argument("--mode", choices=["quality", "fast"], default="quality",
                        help="quality: VGGT+GS training (default), fast: VGGT-only PLY")
    parser.add_argument("--trainer-dir", type=str, default="/workspace/InstantSplat",
                        help="Path to InstantSplat or 3DGS clone (for quality mode)")
    parser.add_argument("--vggt-dir", type=str, default="/workspace/vggt",
                        help="Path to VGGT repo")
    parser.add_argument("--viewer-dir", type=str, default="viewer",
                        help="Path to viewer/ directory")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--start", type=int, default=1,
                        help="First timestep (1-indexed)")
    parser.add_argument("--end", type=int, default=None,
                        help="Last timestep (default: all)")
    parser.add_argument("--train-iter", type=int, default=200,
                        help="Keyframe training iterations (default: 200)")
    parser.add_argument("--warmstart-iter", type=int, default=100,
                        help="Warm-started frame iterations (default: 100)")
    parser.add_argument("--keyframe-interval", type=int, default=10,
                        help="Full re-init every N frames (default: 10)")
    parser.add_argument("--multi-gpu", action="store_true",
                        help="Use all available GPUs in parallel")
    parser.add_argument("--gemini", action="store_true",
                        help="Use Gemini to enhance synthetic views (needs GEMINI_API_KEY)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--skip-organize", action="store_true",
                        help="Skip step 1 if already organized")
    parser.add_argument("--skip-reconstruct", action="store_true",
                        help="Skip step 2 (just collect existing outputs)")
    args = parser.parse_args()

    pipeline_start = time.time()

    print("=" * 60)
    print("  REPLAY — VGGT Per-Timestep 4D Pipeline")
    print(f"  Mode: {args.mode}")
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
        mode_desc = "VGGT only (fast)" if args.mode == "fast" else "VGGT + Gaussian training"
        print(f"STEP 2/3: Running {mode_desc} on each timestep...")
        from run_vggt_pipeline import run_all
        succeeded, failed = run_all(
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            mode=args.mode,
            trainer_dir=args.trainer_dir,
            gpu_id=args.gpu,
            start=args.start,
            end=args.end,
            train_iter=args.train_iter,
            vggt_dir=args.vggt_dir,
            multi_gpu=args.multi_gpu,
            keyframe_interval=args.keyframe_interval,
            keyframe_iter=args.train_iter,
            warmstart_iter=args.warmstart_iter,
            use_gemini=args.gemini,
        )
        if succeeded == 0:
            print("[FAIL] No timesteps succeeded. Check VGGT installation.")
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
    print(f"  Optimizations applied:")
    print(f"    VGGT init .......... ~0.15s/frame (225x faster than MASt3R)")
    print(f"    Keyframes .......... {args.train_iter} iter every {args.keyframe_interval} frames")
    print(f"    Warm-start ......... {args.warmstart_iter} iter (prev frame init)")
    if args.multi_gpu:
        print(f"    Multi-GPU .......... parallel across all GPUs")
    print()
    print(f"  To view: cd viewer && npm run dev")
    print("=" * 60)


if __name__ == "__main__":
    main()
