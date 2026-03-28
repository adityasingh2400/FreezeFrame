#!/usr/bin/env python3
"""Run InstantSplat on each timestep folder to produce per-frame 3D Gaussians.

For each t_00001/, t_00002/, ..., t_00080/:
  1. Copies images into InstantSplat's expected asset path
  2. Runs InstantSplat's init_geo.py (MASt3R geometric initialization)
  3. Runs InstantSplat's train.py (Gaussian Bundle Adjustment)
  4. Collects the output PLY file

Matches the real InstantSplat CLI from scripts/run_infer.sh exactly.

Outputs:
  instantsplat_output/
    time_00000.ply
    time_00001.ply
    ...
    time_00079.ply
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

GS_TRAIN_ITER = 500
GS_TRAIN_ITER_MAX = 7000
TIMEOUT_SECONDS = 600
TIMEOUT_SECONDS_MAX = 1800


def find_output_ply(model_path):
    """Find the best output PLY from InstantSplat's model output directory.

    InstantSplat saves point clouds at:
      {model_path}/point_cloud/iteration_{N}/point_cloud.ply
    """
    model_path = Path(model_path)
    pc_dir = model_path / "point_cloud"

    if pc_dir.exists():
        iteration_dirs = sorted(
            [d for d in pc_dir.iterdir() if d.is_dir() and d.name.startswith("iteration_")],
            key=lambda d: int(d.name.split("_")[1]),
            reverse=True,
        )
        for d in iteration_dirs:
            ply = d / "point_cloud.ply"
            if ply.exists() and ply.stat().st_size > 1000:
                return ply

    for ply in sorted(model_path.rglob("*.ply"), key=lambda p: p.stat().st_mtime, reverse=True):
        if ply.stat().st_size > 1000:
            return ply

    return None


def run_timestep(instantsplat_dir, timestep_dir, output_ply_path, gpu_id=0, train_iter=GS_TRAIN_ITER, timeout=TIMEOUT_SECONDS):
    """Run InstantSplat on a single timestep folder.

    Follows the exact same steps as scripts/run_infer.sh:
      (1) init_geo.py  — Co-visible Global Geometry Initialization (MASt3R)
      (2) train.py     — Jointly optimize pose + Gaussians (GauBA)
    """
    instantsplat_dir = Path(instantsplat_dir)
    timestep_dir = Path(timestep_dir)

    images = sorted(timestep_dir.glob("images/*.jpg"))
    if len(images) == 0:
        print(f"\n  [SKIP] No images in {timestep_dir}")
        return False

    timestep_name = timestep_dir.name
    n_views = len(images)

    source_path = instantsplat_dir / "assets" / "replay" / timestep_name
    image_dir = source_path / "images"
    model_path = instantsplat_dir / "output_replay" / timestep_name / f"{n_views}_views"

    if image_dir.exists():
        shutil.rmtree(str(image_dir))
    image_dir.mkdir(parents=True, exist_ok=True)
    model_path.mkdir(parents=True, exist_ok=True)

    for img in images:
        shutil.copy2(str(img), str(image_dir / img.name))

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    # ── (1) Co-visible Global Geometry Initialization (MASt3R) ───────
    init_cmd = [
        sys.executable, "-W", "ignore", "./init_geo.py",
        "-s", str(source_path),
        "-m", str(model_path),
        "--n_views", str(n_views),
        "--focal_avg",
        "--co_vis_dsp",
        "--conf_aware_ranking",
    ]

    try:
        result = subprocess.run(
            init_cmd,
            cwd=str(instantsplat_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-800:]
            print(f"\n  [FAIL] init_geo.py returned {result.returncode}")
            if stderr_tail:
                print(f"  stderr: ...{stderr_tail}")
            return False
    except subprocess.TimeoutExpired:
        print(f"\n  [FAIL] init_geo.py timed out after {TIMEOUT_SECONDS}s")
        return False

    # ── (2) Train: jointly optimize pose + Gaussians (GauBA) ─────────
    port = 6100 + (hash(timestep_name) % 900)
    train_cmd = [
        sys.executable, "./train.py",
        "-s", str(source_path),
        "-m", str(model_path),
        "-r", "1",
        "--n_views", str(n_views),
        "--iterations", str(train_iter),
        "--pp_optimizer",
        "--optim_pose",
    ]

    # Max quality: ensure densification runs long enough for high iteration counts
    if train_iter >= 3000:
        train_cmd += [
            "--densify_from_iter", "500",
            "--densify_until_iter", str(int(train_iter * 0.85)),
            "--densification_interval", "100",
            "--opacity_reset_interval", "3000",
        ]

    try:
        result = subprocess.run(
            train_cmd,
            cwd=str(instantsplat_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-800:]
            print(f"\n  [FAIL] train.py returned {result.returncode}")
            if stderr_tail:
                print(f"  stderr: ...{stderr_tail}")
            return False
    except subprocess.TimeoutExpired:
        print(f"\n  [FAIL] train.py timed out after {TIMEOUT_SECONDS}s")
        return False

    # ── (3) Collect output PLY ───────────────────────────────────────
    out_ply = find_output_ply(model_path)
    if out_ply is None:
        print(f"\n  [FAIL] No output PLY found in {model_path}")
        return False

    output_ply_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(out_ply), str(output_ply_path))
    size_kb = out_ply.stat().st_size / 1024
    print(f"[OK] {output_ply_path.name} ({size_kb:.0f} KB)")

    # ── Cleanup to save disk space ───────────────────────────────────
    asset_scene = source_path
    if asset_scene.exists():
        shutil.rmtree(str(asset_scene), ignore_errors=True)
    if model_path.exists():
        shutil.rmtree(str(model_path), ignore_errors=True)

    return True


def run_all(input_dir, output_dir, instantsplat_dir, gpu_id=0, start=1, end=None,
            skip_existing=True, train_iter=GS_TRAIN_ITER, timeout=TIMEOUT_SECONDS):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    instantsplat_dir = Path(instantsplat_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not (instantsplat_dir / "init_geo.py").exists():
        print(f"[FAIL] init_geo.py not found in {instantsplat_dir}")
        print(f"       Is InstantSplat cloned there?")
        raise SystemExit(1)

    timestep_dirs = sorted([
        d for d in input_dir.iterdir()
        if d.is_dir() and d.name.startswith("t_")
    ])
    if not timestep_dirs:
        print(f"[FAIL] No t_* directories in {input_dir}")
        raise SystemExit(1)

    if end is None:
        end = len(timestep_dirs)

    print(f"Processing timesteps {start}-{end} out of {len(timestep_dirs)}")
    print(f"InstantSplat: {instantsplat_dir}")
    print(f"Train iters:  {train_iter}")
    print(f"Output:       {output_dir}")
    print()

    succeeded = 0
    failed = 0
    skipped = 0
    total_start = time.time()

    for ts_dir in timestep_dirs:
        ts_num = int(ts_dir.name.split("_")[1])
        if ts_num < start or ts_num > end:
            continue

        out_name = f"time_{ts_num - 1:05d}.ply"
        out_path = output_dir / out_name

        if skip_existing and out_path.exists() and out_path.stat().st_size > 1000:
            skipped += 1
            continue

        elapsed_so_far = time.time() - total_start
        avg = elapsed_so_far / max(succeeded, 1) if succeeded > 0 else 0
        remaining = (end - ts_num) * avg if avg > 0 else 0
        eta = f" ETA {int(remaining // 60)}m{int(remaining % 60)}s" if avg > 0 else ""

        print(f"[{ts_num:3d}/{end}] {ts_dir.name}... ", end="", flush=True)
        step_start = time.time()

        if run_timestep(instantsplat_dir, ts_dir, out_path, gpu_id, train_iter, timeout):
            succeeded += 1
            step_elapsed = time.time() - step_start
            print(f" ({step_elapsed:.1f}s){eta}")
        else:
            failed += 1

    total_elapsed = time.time() - total_start
    mins = int(total_elapsed // 60)
    secs = int(total_elapsed % 60)

    print(f"\n{'='*60}")
    print(f"  DONE: {succeeded} OK, {failed} failed, {skipped} skipped")
    print(f"  Time: {mins}m {secs}s")
    print(f"  Output: {output_dir}")
    if succeeded > 0:
        print(f"  Avg per timestep: {total_elapsed / succeeded:.1f}s")
    print(f"{'='*60}")

    return succeeded, failed


def main():
    parser = argparse.ArgumentParser(
        description="Run InstantSplat per-timestep for 4D reconstruction")
    parser.add_argument("--input", type=str, default="instantsplat_input",
                        help="Directory with t_00001/ ... t_00080/ folders")
    parser.add_argument("--output", type=str, default="instantsplat_output",
                        help="Directory for output PLY files")
    parser.add_argument("--instantsplat-dir", type=str, default="/workspace/InstantSplat",
                        help="Path to cloned InstantSplat repository")
    parser.add_argument("--gpu", type=int, default=0,
                        help="GPU device ID")
    parser.add_argument("--start", type=int, default=1,
                        help="First timestep to process (1-indexed)")
    parser.add_argument("--end", type=int, default=None,
                        help="Last timestep to process (default: all)")
    parser.add_argument("--train-iter", type=int, default=GS_TRAIN_ITER,
                        help=f"Gaussian training iterations per timestep (default: {GS_TRAIN_ITER})")
    parser.add_argument("--max-quality", action="store_true",
                        help="Max quality: 7000 iterations, full densification, 30min timeout")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-process even if output PLY already exists")
    args = parser.parse_args()

    train_iter = args.train_iter
    if args.max_quality:
        train_iter = GS_TRAIN_ITER_MAX
        print(f"[MAX QUALITY] {train_iter} iters, timeout {TIMEOUT_SECONDS_MAX}s")

    timeout = TIMEOUT_SECONDS_MAX if args.max_quality else TIMEOUT_SECONDS

    run_all(
        input_dir=args.input,
        output_dir=args.output,
        instantsplat_dir=args.instantsplat_dir,
        gpu_id=args.gpu,
        start=args.start,
        end=args.end,
        skip_existing=not args.no_skip,
        train_iter=train_iter,
        timeout=timeout,
    )


if __name__ == "__main__":
    main()
