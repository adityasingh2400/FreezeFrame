"""Stage 2: COLMAP Pose Recovery + LLFF Export — Owner: Divij

INPUT:  Contract A — scene/images/cam00/frame_00000.png, ... + metadata.json
OUTPUT: Contract B — see below

CONTRACT B OUTPUT (both paths):
  COLMAP path:  scene/sparse/0/cameras.bin, images.bin, points3D.bin
  LLFF path:    scene/poses_bounds.npy  (shape: N_cameras x 17)

Divij outputs BOTH formats. Aditya picks whichever 4DGS loads.

COLMAP FAILURE FALLBACK:
  If COLMAP fails on video frames (motion blur), manually select the
  sharpest frame per camera and run COLMAP on just those 4-5 stills.
  This gives a static 3D reconstruction — better than nothing.

ALGORITHM:
  1. Collect all frames (or representative subset) into a flat image list
  2. Run COLMAP feature extraction
  3. Run COLMAP feature matching (exhaustive for small sets)
  4. Run COLMAP sparse reconstruction (mapper)
  5. Verify: did COLMAP recover a pose for every camera?
  6. Convert COLMAP output to LLFF poses_bounds.npy
  7. Validate with: make validate-b
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def collect_images_for_colmap(images_dir: Path, strategy: str = "all") -> list[Path]:
    """Collect images for COLMAP processing.

    Args:
        images_dir: scene/images/ containing cam00/, cam01/, etc.
        strategy: "all" for all frames, "one_per_cam" for just one frame per camera
                  (use "one_per_cam" as fallback if COLMAP fails on full set)

    Returns list of image paths.
    """
    raise NotImplementedError("Divij: implement this")


def run_colmap_feature_extraction(image_list: list[Path], database_path: Path):
    """Run COLMAP feature extraction on the image list."""
    raise NotImplementedError("Divij: implement this")


def run_colmap_matching(database_path: Path):
    """Run COLMAP exhaustive matching."""
    raise NotImplementedError("Divij: implement this")


def run_colmap_mapper(database_path: Path, image_dir: Path, output_dir: Path):
    """Run COLMAP sparse mapper to recover camera poses.

    Output: cameras.bin, images.bin, points3D.bin in output_dir
    """
    raise NotImplementedError("Divij: implement this")


def verify_poses(sparse_dir: Path, expected_cameras: int) -> bool:
    """Check that COLMAP recovered poses for all expected cameras.

    Returns True if all cameras have poses.
    """
    raise NotImplementedError("Divij: implement this")


def convert_colmap_to_llff(sparse_dir: Path, output_path: Path):
    """Convert COLMAP sparse output to LLFF poses_bounds.npy.

    Output: poses_bounds.npy with shape (N_cameras, 17)
    Each row: [3x5 pose matrix flattened (15) + near_bound + far_bound]
    """
    raise NotImplementedError("Divij: implement this — use LLFF's imgs2poses.py as reference")


def run():
    cfg = load_config()
    images_dir = resolve_path(cfg["stage2"]["images_dir"])
    sparse_dir = resolve_path(cfg["stage2"]["sparse_dir"])
    poses_path = resolve_path(cfg["stage2"]["poses_bounds_path"])

    print(f"Stage 2: COLMAP Pose Recovery")
    print(f"  Images:        {images_dir}")
    print(f"  COLMAP output: {sparse_dir}")
    print(f"  LLFF output:   {poses_path}")

    # TODO: implement the pipeline
    raise NotImplementedError("Divij: implement run()")


if __name__ == "__main__":
    run()
