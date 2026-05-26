"""Stage 3: 4DGaussians Training + PLY Export — Owner: Aditya

INPUT:  Contract B — scene/sparse/0/*.bin OR scene/poses_bounds.npy + scene/images/ + synced_videos/
OUTPUT: Contract C — see below

CONTRACT C OUTPUT:
  Per-timestep:  output/frames/frame_00000.ply, frame_00001.ply, ...
  Metadata:      output/output_meta.json

DATA FORMAT AUTO-DETECTION:
  1. Check COLMAP path: sparse/0/ has cameras.bin + images.bin + points3D.bin
  2. If all three exist → use COLMAP path: python train.py -s scene/ --source_type colmap
  3. Else check LLFF path: poses_bounds.npy exists
  4. If exists → use DyNeRF path: python train.py -s scene/ --source_type n3d
  5. If neither → exit with error listing which files are missing

PLY EXPORT:
  4DGS stores a deformation field on a canonical Gaussian set.
  Use export_perframe_3DGS.py (from the 4DGS repo) to evaluate the deformation
  at each timestep and dump per-frame .ply files.
  Cap at max_export_frames from config (default 50 for MVP).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def detect_data_format(scene_dir: Path) -> str:
    """Detect which data format is available.

    Returns "colmap", "dynerf", or exits with error.
    """
    sparse_dir = scene_dir / "sparse" / "0"
    colmap_files = ["cameras.bin", "images.bin", "points3D.bin"]
    has_colmap = all((sparse_dir / f).exists() for f in colmap_files)

    poses_path = scene_dir / "poses_bounds.npy"
    has_llff = poses_path.exists()

    if has_colmap:
        print(f"  Detected: COLMAP format (sparse/0/ has all .bin files)")
        return "colmap"
    elif has_llff:
        print(f"  Detected: DyNeRF/LLFF format (poses_bounds.npy found)")
        return "dynerf"
    else:
        missing = []
        for f in colmap_files:
            if not (sparse_dir / f).exists():
                missing.append(f"sparse/0/{f}")
        if not has_llff:
            missing.append("poses_bounds.npy")
        print(f"ERROR: No valid data format found. Missing files:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)


def launch_training(scene_dir: Path, source_type: str, iterations: int, resolution_scale: int):
    """Launch 4DGS training.

    Args:
        scene_dir: Path to scene/ directory
        source_type: "colmap" or "n3d"
        iterations: Number of training iterations
        resolution_scale: Downsample factor (2 = half resolution)
    """
    raise NotImplementedError("Aditya: implement this — call 4DGS train.py")


def export_per_frame_ply(checkpoint_dir: Path, export_dir: Path, max_frames: int):
    """Export per-timestep .ply files from trained 4DGS model.

    Uses 4DGS's export_perframe_3DGS.py or equivalent to evaluate the
    deformation network at each timestep and dump deformed Gaussians.

    Output: export_dir/frame_00000.ply, frame_00001.ply, ...
    """
    raise NotImplementedError("Aditya: implement this — adapt export_perframe_3DGS.py")


def write_output_meta(
    output_path: Path,
    num_frames: int,
    fps: int,
    checkpoint_dir: Path,
    hero_frame: int = 0,
):
    """Write output/output_meta.json."""
    meta = {
        "num_frames": num_frames,
        "fps": fps,
        "format": "ply",
        "coordinate_system": "opencv",
        "training_iterations": 10000,
        "source_checkpoint": str(checkpoint_dir),
        "hero_frame": hero_frame,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Wrote {output_path}")


def run():
    cfg = load_config()
    scene_dir = resolve_path(cfg["scene_dir"])
    checkpoint_dir = resolve_path(cfg["stage3"]["checkpoint_dir"])
    export_dir = resolve_path(cfg["stage3"]["export_dir"])
    meta_path = resolve_path(cfg["stage3"]["output_meta_path"])
    iterations = cfg["stage3"]["training_iterations"]
    res_scale = cfg["stage3"]["resolution_scale"]
    max_frames = cfg["stage3"]["max_export_frames"]
    fmt = cfg["stage3"]["data_format"]

    print(f"Stage 3: 4DGaussians Training")
    print(f"  Scene:      {scene_dir}")
    print(f"  Config:     {iterations} iterations, {res_scale}x downsample")
    print(f"  Max frames: {max_frames}")

    if fmt == "auto":
        source_type = detect_data_format(scene_dir)
    elif fmt == "colmap":
        source_type = "colmap"
    else:
        source_type = "n3d"

    source_flag = "colmap" if source_type == "colmap" else "n3d"
    print(f"  Source type: {source_flag}")

    # TODO: implement training + export
    raise NotImplementedError("Aditya: implement run()")


if __name__ == "__main__":
    run()
