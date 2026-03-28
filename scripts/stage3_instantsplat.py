"""Stage 3 (InstantSplat): Per-timestep 3D Gaussian Splatting

Replaces the 4DGS approach with per-timestep InstantSplat reconstruction.
Each of the 80 timesteps gets an independent 3DGS reconstruction from all 4
camera images, producing one .ply per timestep — exactly what the viewer needs.

INPUT:  scene/images/cam01..cam04/frame_00001.jpg .. frame_00080.jpg
OUTPUT: output/frames/frame_00000.ply .. frame_00079.ply
        output/output_meta.json

USAGE:
  # Full run (all 80 frames):
  python scripts/stage3_instantsplat.py

  # Subset (for testing):
  python scripts/stage3_instantsplat.py --start 1 --end 5

  # Resume (skips frames whose .ply already exists):
  python scripts/stage3_instantsplat.py  # idempotent by default

  # Dry run (print commands without executing):
  python scripts/stage3_instantsplat.py --dry-run

INSTANTSPLAT SETUP (on RunPod):
  git clone https://github.com/NVlabs/InstantSplat /workspace/InstantSplat
  cd /workspace/InstantSplat && pip install -e .
  # Download MASt3R checkpoint (InstantSplat README has the link)

ENVIRONMENT:
  Set INSTANTSPLAT_DIR to override the default repo location.
  Default search order:
    1. $INSTANTSPLAT_DIR
    2. /workspace/InstantSplat
    3. ~/InstantSplat
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


# InstantSplat training iterations — 3000 is fast (~40s on A100) and good enough.
# Increase to 7000 for higher quality if time permits.
DEFAULT_ITERATIONS = 3000


def find_instantsplat_dir() -> Path:
    """Locate the InstantSplat repo directory."""
    candidates = [
        os.environ.get("INSTANTSPLAT_DIR"),
        "/workspace/InstantSplat",
        os.path.expanduser("~/InstantSplat"),
    ]
    for c in candidates:
        if c and Path(c).is_dir() and (Path(c) / "train.py").exists():
            return Path(c)
    print("ERROR: InstantSplat repo not found. Tried:")
    for c in candidates:
        if c:
            print(f"  {c}")
    print("\nSet INSTANTSPLAT_DIR or clone to /workspace/InstantSplat:")
    print("  git clone https://github.com/NVlabs/InstantSplat /workspace/InstantSplat")
    sys.exit(1)


def find_output_ply(model_dir: Path, iterations: int) -> Path | None:
    """Find the output PLY from an InstantSplat run.

    InstantSplat saves to: <model_dir>/point_cloud/iteration_<N>/point_cloud.ply
    Falls back to searching for any point_cloud.ply in the model dir tree.
    """
    # Primary location
    primary = model_dir / "point_cloud" / f"iteration_{iterations}" / "point_cloud.ply"
    if primary.exists():
        return primary

    # Search for any point_cloud.ply (handles different iteration counts)
    matches = sorted(model_dir.rglob("point_cloud.ply"))
    if matches:
        # Pick the one with the highest iteration number
        return matches[-1]

    return None


def prepare_timestep_dir(workspace: Path, frame_idx: int, cam_dirs: list[Path]) -> Path:
    """Create a per-timestep input directory for InstantSplat.

    InstantSplat expects: <timestep_dir>/images/<image files>

    Args:
        workspace: Root workspace dir (scene/instantsplat_workspace/)
        frame_idx: 1-indexed frame number (1..80)
        cam_dirs: List of camera directories in order

    Returns: Path to the timestep source dir
    """
    t_dir = workspace / f"t_{frame_idx:05d}" / "images"
    t_dir.mkdir(parents=True, exist_ok=True)

    frame_name = f"frame_{frame_idx:05d}.jpg"
    for cam_dir in cam_dirs:
        src = cam_dir / frame_name
        if not src.exists():
            print(f"  WARNING: Missing {src} — skipping this camera for t={frame_idx}")
            continue
        dst = t_dir / f"{cam_dir.name}.jpg"
        if not dst.exists():
            shutil.copy2(src, dst)

    copied = len(list(t_dir.glob("*.jpg")))
    return t_dir.parent, copied


def run_instantsplat(
    instantsplat_dir: Path,
    source_dir: Path,
    model_dir: Path,
    n_views: int,
    iterations: int,
    dry_run: bool,
) -> bool:
    """Run InstantSplat for a single timestep: init_geo.py then train.py.

    Returns True on success, False on failure.
    """
    # Step 1: MASt3R geometry initialization (generates camera poses + confidence maps)
    init_cmd = [
        "python", "-W", "ignore", "init_geo.py",
        "-s", str(source_dir),
        "-m", str(model_dir),
        "--n_views", str(n_views),
        "--focal_avg",
        "--co_vis_dsp",
        "--conf_aware_ranking",
        "--infer_video",
    ]

    # Step 2: Gaussian splatting training
    train_cmd = [
        "python", "train.py",
        "-s", str(source_dir),
        "-m", str(model_dir),
        "-r", "1",
        "--n_views", str(n_views),
        "--iterations", str(iterations),
        "--pp_optimizer",
        "--optim_pose",
    ]

    if dry_run:
        print(f"  DRY RUN init:  {' '.join(init_cmd)}")
        print(f"  DRY RUN train: {' '.join(train_cmd)}")
        return True

    for label, cmd in [("init_geo", init_cmd), ("train", train_cmd)]:
        result = subprocess.run(
            cmd,
            cwd=str(instantsplat_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  FAILED at {label} (exit {result.returncode})")
            stderr_lines = (result.stderr + result.stdout).strip().splitlines()
            for line in stderr_lines[-10:]:
                print(f"    {line}")
            return False

    return True


def run(args):
    cfg = load_config()
    images_dir = resolve_path(cfg["stage1"]["images_dir"])
    export_dir = resolve_path(cfg["stage3"]["export_dir"])
    meta_path = resolve_path(cfg["stage3"]["output_meta_path"])
    fps = cfg["stage1"]["target_fps"]

    # Load scene metadata
    scene_meta_path = resolve_path(cfg["stage1"]["metadata_path"])
    with open(scene_meta_path) as f:
        scene_meta = json.load(f)

    num_frames = scene_meta["num_frames"]  # 80
    num_cameras = scene_meta["num_cameras"]  # 4

    # Resolve frame range
    start = max(1, args.start)
    end = min(num_frames, args.end if args.end else num_frames)
    iterations = args.iterations

    # Find InstantSplat
    instantsplat_dir = find_instantsplat_dir()
    print(f"InstantSplat: {instantsplat_dir}")

    # Camera dirs
    cam_dirs = sorted([d for d in images_dir.iterdir() if d.is_dir() and d.name.startswith("cam")])
    if len(cam_dirs) != num_cameras:
        print(f"ERROR: Expected {num_cameras} camera dirs, found {len(cam_dirs)}")
        sys.exit(1)

    # Workspace dirs
    workspace = resolve_path("scene/instantsplat_workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    print(f"Processing frames {start}..{end} ({end - start + 1} total), {iterations} iterations each")
    print(f"Camera count: {num_cameras}")
    print(f"Output: {export_dir}")
    if args.dry_run:
        print("DRY RUN mode — no commands will be executed")
    print()

    succeeded = 0
    skipped = 0
    failed = 0
    failed_frames = []
    t_total_start = time.time()

    for frame_idx in range(start, end + 1):
        # Output is 0-indexed (viewer expects frame_00000.ply for t=1)
        out_idx = frame_idx - 1
        out_ply = export_dir / f"frame_{out_idx:05d}.ply"

        if out_ply.exists() and not args.force:
            skipped += 1
            continue

        t_start = time.time()
        print(f"[{frame_idx:3d}/{end}] t={frame_idx}", end="  ", flush=True)

        # Prepare input dir
        source_dir, n_copied = prepare_timestep_dir(workspace, frame_idx, cam_dirs)
        if n_copied < 2:
            print(f"SKIP — only {n_copied} images found (need >= 2)")
            failed += 1
            failed_frames.append(frame_idx)
            continue

        if n_copied < num_cameras:
            print(f"WARN: only {n_copied}/{num_cameras} cameras — proceeding")

        # Model output dir for this timestep
        model_dir = workspace / f"model_{frame_idx:05d}"
        model_dir.mkdir(parents=True, exist_ok=True)

        # Run InstantSplat
        ok = run_instantsplat(
            instantsplat_dir=instantsplat_dir,
            source_dir=source_dir,
            model_dir=model_dir,
            n_views=n_copied,
            iterations=iterations,
            dry_run=args.dry_run,
        )

        if not ok:
            failed += 1
            failed_frames.append(frame_idx)
            elapsed = time.time() - t_start
            print(f"FAILED  ({elapsed:.0f}s)")
            continue

        # Find and copy the output PLY
        if not args.dry_run:
            ply = find_output_ply(model_dir, iterations)
            if ply is None:
                print(f"FAILED — PLY not found in {model_dir}")
                failed += 1
                failed_frames.append(frame_idx)
                continue
            shutil.copy2(ply, out_ply)

        elapsed = time.time() - t_start
        print(f"OK  ({elapsed:.0f}s)")
        succeeded += 1

    # Write output_meta.json
    ply_count = len(list(export_dir.glob("frame_*.ply")))
    if ply_count > 0 and not args.dry_run:
        meta = {
            "num_frames": ply_count,
            "fps": fps,
            "format": "ply",
            "coordinate_system": "opencv",
            "method": "instantsplat",
            "iterations_per_frame": iterations,
            "hero_frame": 0,
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"\nWrote {meta_path}")

    # Summary
    total_elapsed = time.time() - t_total_start
    print(f"\n{'='*50}")
    print(f"Done in {total_elapsed/60:.1f} min")
    print(f"  Succeeded: {succeeded}")
    print(f"  Skipped:   {skipped} (already done)")
    print(f"  Failed:    {failed}")
    if failed_frames:
        print(f"  Failed frames: {failed_frames}")
    print(f"  Total PLY files: {ply_count}")

    if failed > 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Stage 3: Per-timestep InstantSplat reconstruction")
    parser.add_argument("--start", type=int, default=1, help="First frame to process (1-indexed, default: 1)")
    parser.add_argument("--end", type=int, default=None, help="Last frame to process (1-indexed, default: last frame)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS, help=f"InstantSplat training iterations (default: {DEFAULT_ITERATIONS})")
    parser.add_argument("--force", action="store_true", help="Re-run even if output PLY already exists")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
