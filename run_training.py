#!/usr/bin/env python3
"""Stage 3: End-to-end 4DGS training + export pipeline.

Prepares data, trains 4D Gaussian Splatting, exports per-frame .ply files,
renders a preview video, and generates the viewer manifest.

Usage:
    # Fast test run (~5 min on A100)
    python run_training.py --fast

    # Quality run (~15-20 min on A100)
    python run_training.py

    # Export only (skip training, use existing checkpoint)
    python run_training.py --export-only

    # Specify custom data path
    python run_training.py --data-dir /workspace/replay/data/multipleview/replay
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

FOURDGS_DIR = Path(__file__).resolve().parent / "4DGaussians"
SCENE_DIR = Path(__file__).resolve().parent / "scene"
VIEWER_DIR = Path(__file__).resolve().parent / "viewer"

CONFIG_FAST = "arguments/multipleview/replay_fast.py"
CONFIG_QUALITY = "arguments/multipleview/replay.py"
DEFAULT_PORT = 6017


def run_cmd(cmd, cwd=None, env=None):
    """Run a shell command, stream output, and exit on failure."""
    print(f"\n{'='*60}")
    print(f"  CMD: {' '.join(str(c) for c in cmd)}")
    print(f"{'='*60}\n")
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=cwd, env=merged_env)
    if result.returncode != 0:
        print(f"\n[FAIL] Command exited with code {result.returncode}")
        sys.exit(result.returncode)


def check_prerequisites():
    """Verify all required files and tools exist before starting."""
    errors = []

    if not FOURDGS_DIR.exists():
        errors.append(f"4DGaussians repo not found at {FOURDGS_DIR}")

    train_py = FOURDGS_DIR / "train.py"
    if not train_py.exists():
        errors.append(f"train.py not found at {train_py}")

    try:
        subprocess.run([sys.executable, "-c", "import torch; assert torch.cuda.is_available()"],
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        errors.append("PyTorch with CUDA not available (torch.cuda.is_available() == False)")

    if errors:
        print("[ERROR] Prerequisites check failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("[OK] Prerequisites check passed")


def validate_data(data_dir):
    """Check the data directory has everything 4DGS MultipleView loader needs."""
    data_dir = Path(data_dir)
    errors = []
    warnings = []

    cam_dirs = sorted(data_dir.glob("cam*/"))
    if len(cam_dirs) == 0:
        errors.append(f"No camera folders (cam01/, cam02/, ...) found in {data_dir}")
    else:
        frame_counts = {}
        for cd in cam_dirs:
            frames = sorted(cd.glob("frame_*.jpg"))
            frame_counts[cd.name] = len(frames)

        counts = list(frame_counts.values())
        if len(set(counts)) > 1:
            errors.append(f"Frame count mismatch: {frame_counts}")
        elif counts[0] == 0:
            errors.append("Camera folders exist but contain no frame_*.jpg files")
        else:
            print(f"[OK] {len(cam_dirs)} cameras, {counts[0]} frames each")

    sparse = data_dir / "sparse_"
    required_sparse = ["cameras.bin", "images.bin"]
    for f in required_sparse:
        if not (sparse / f).exists():
            errors.append(f"Missing {sparse / f} (COLMAP output)")

    ply = data_dir / "points3D_multipleview.ply"
    if not ply.exists():
        errors.append(f"Missing {ply} (downsampled point cloud)")

    npy = data_dir / "poses_bounds_multipleview.npy"
    if not npy.exists():
        warnings.append(f"Missing {npy} (LLFF poses — needed for video render path)")

    if warnings:
        for w in warnings:
            print(f"[WARN] {w}")

    if errors:
        print("[ERROR] Data validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("[OK] Data validation passed")
    return counts[0], len(cam_dirs)


def symlink_data(data_dir):
    """Create a symlink so 4DGS can find the data at its expected path."""
    target = FOURDGS_DIR / "data" / "multipleview" / "replay"
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(Path(data_dir).resolve()), str(target))
    print(f"[OK] Symlinked {target} -> {data_dir}")
    return target


def train(config, port=DEFAULT_PORT):
    """Run 4DGS training."""
    print("\n" + "="*60)
    print("  STAGE 3A: 4DGS TRAINING")
    print("="*60)

    start = time.time()
    run_cmd([
        sys.executable, "train.py",
        "-s", "data/multipleview/replay",
        "--port", str(port),
        "--expname", "multipleview/replay",
        "--configs", config,
    ], cwd=FOURDGS_DIR)

    elapsed = time.time() - start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    print(f"\n[OK] Training completed in {mins}m {secs}s")


def render_video(config):
    """Render novel view video from trained model."""
    print("\n" + "="*60)
    print("  STAGE 3B: RENDER VIDEO")
    print("="*60)

    model_path = FOURDGS_DIR / "output" / "multipleview" / "replay"
    if not model_path.exists():
        print(f"[WARN] Model path not found at {model_path}, skipping render")
        return

    run_cmd([
        sys.executable, "render.py",
        "--model_path", str(model_path),
        "--skip_train",
        "--configs", config,
    ], cwd=FOURDGS_DIR)

    video_candidates = list(model_path.rglob("video_rgb.mp4"))
    if video_candidates:
        print(f"[OK] Video rendered: {video_candidates[0]}")
    else:
        print("[WARN] No video_rgb.mp4 found after render")


def find_best_iteration():
    """Find the highest iteration checkpoint in the output."""
    pc_dir = FOURDGS_DIR / "output" / "multipleview" / "replay" / "point_cloud"
    if not pc_dir.exists():
        print(f"[ERROR] No point_cloud directory at {pc_dir}")
        sys.exit(1)

    iterations = []
    for d in pc_dir.iterdir():
        if d.is_dir() and d.name.startswith("iteration_"):
            try:
                iterations.append(int(d.name.split("_")[1]))
            except (ValueError, IndexError):
                pass

    if not iterations:
        coarse = [d for d in pc_dir.iterdir() if d.is_dir() and "coarse" in d.name]
        if coarse:
            print("[WARN] Only coarse checkpoints found — training may not have completed fine stage")
        print(f"[ERROR] No iteration checkpoints found in {pc_dir}")
        sys.exit(1)

    best = max(iterations)
    print(f"[OK] Best checkpoint: iteration_{best}")
    return best


def export_perframe(config, iteration):
    """Export per-timestamp .ply files for the viewer."""
    print("\n" + "="*60)
    print("  STAGE 3C: EXPORT PER-FRAME PLY")
    print("="*60)

    model_path = FOURDGS_DIR / "output" / "multipleview" / "replay"
    run_cmd([
        sys.executable, "export_perframe_3DGS.py",
        "--iteration", str(iteration),
        "--configs", config,
        "--model_path", str(model_path),
    ], cwd=FOURDGS_DIR)

    export_dir = model_path / "gaussian_pertimestamp"
    if not export_dir.exists():
        print(f"[ERROR] Export directory not found at {export_dir}")
        sys.exit(1)

    ply_files = sorted(export_dir.glob("time_*.ply"))
    print(f"[OK] Exported {len(ply_files)} per-frame .ply files")
    return export_dir, ply_files


def generate_manifest(ply_files, fps=30):
    """Generate manifest.json for the web viewer and copy .ply files."""
    print("\n" + "="*60)
    print("  STAGE 3D: GENERATE VIEWER MANIFEST")
    print("="*60)

    frames_dir = VIEWER_DIR / "public" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    filenames = []
    for ply in ply_files:
        dest = frames_dir / ply.name
        shutil.copy2(ply, dest)
        filenames.append(ply.name)

    hero_idx = len(filenames) // 3
    manifest = {
        "frames": filenames,
        "fps": fps,
        "baseDir": "/frames/",
        "hero_frame": hero_idx,
        "total_frames": len(filenames),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    manifest_path = VIEWER_DIR / "public" / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"[OK] Copied {len(filenames)} .ply files to {frames_dir}")
    print(f"[OK] Manifest written to {manifest_path}")
    print(f"[OK] Hero frame: {hero_idx} (first third — likely pre-jump)")

    output_meta_path = Path(__file__).resolve().parent / "output" / "output_meta.json"
    output_meta_path.parent.mkdir(parents=True, exist_ok=True)
    output_meta = {
        "num_frames": len(filenames),
        "fps": fps,
        "format": "ply",
        "coordinate_system": "opencv",
        "source_checkpoint": str(FOURDGS_DIR / "output" / "multipleview" / "replay"),
        "hero_frame": hero_idx,
    }
    with open(output_meta_path, "w") as f:
        json.dump(output_meta, f, indent=2)
    print(f"[OK] Output metadata written to {output_meta_path}")


def print_summary(num_frames, elapsed):
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    print("\n" + "="*60)
    print("  PIPELINE COMPLETE")
    print("="*60)
    print(f"  Total time:    {mins}m {secs}s")
    print(f"  Frames:        {num_frames}")
    print(f"  Viewer ready:  cd viewer && npm run dev")
    print(f"  Model output:  4DGaussians/output/multipleview/replay/")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Replay Stage 3: 4DGS training + export")
    parser.add_argument("--fast", action="store_true",
                        help="Use fast config (~5 min, lower quality)")
    parser.add_argument("--export-only", action="store_true",
                        help="Skip training, export from existing checkpoint")
    parser.add_argument("--render-video", action="store_true",
                        help="Render a novel-view video after training")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Path to dataset (default: scene/images parent)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="GUI server port for 4DGS (default: 6017)")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip data directory validation")
    args = parser.parse_args()

    pipeline_start = time.time()
    config = CONFIG_FAST if args.fast else CONFIG_QUALITY
    mode = "FAST" if args.fast else "QUALITY"

    print("\n" + "="*60)
    print(f"  REPLAY — Stage 3 Pipeline ({mode})")
    print(f"  Config: {config}")
    print("="*60)

    if not args.export_only:
        check_prerequisites()

    data_dir = args.data_dir
    if data_dir is None:
        candidate = SCENE_DIR / "images"
        if candidate.exists():
            data_dir = str(SCENE_DIR)
        else:
            data_dir = str(FOURDGS_DIR / "data" / "multipleview" / "replay")

    if not args.skip_validation and not args.export_only:
        num_frames, num_cams = validate_data(data_dir)
    else:
        num_frames = 80

    if not args.export_only:
        data_link = symlink_data(data_dir)
        train(config, port=args.port)

    iteration = find_best_iteration()

    if args.render_video:
        render_video(config)

    export_dir, ply_files = export_perframe(config, iteration)
    generate_manifest(ply_files, fps=30)

    print_summary(len(ply_files), time.time() - pipeline_start)


if __name__ == "__main__":
    main()
