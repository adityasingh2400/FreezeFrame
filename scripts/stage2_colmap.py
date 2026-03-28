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

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    import pycolmap
except ImportError:
    print("ERROR: pycolmap not installed. Run: pip install pycolmap")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def collect_images_for_colmap(images_dir: Path, strategy: str = "one_per_cam") -> list[Path]:
    """Collect images for COLMAP processing.

    Args:
        images_dir: scene/images/ containing cam00/, cam01/, etc.
        strategy: "one_per_cam" uses frame_00000 from each camera (fast, recommended).
                  "all" feeds every frame (slow, only if one_per_cam fails).

    Returns list of image paths sorted by camera then frame.
    """
    cam_dirs = sorted(p for p in images_dir.iterdir() if p.is_dir() and p.name.startswith("cam"))
    if not cam_dirs:
        print(f"FAIL: no cam* directories found in {images_dir}")
        sys.exit(1)

    images = []
    if strategy == "one_per_cam":
        for cam_dir in cam_dirs:
            frames = sorted(cam_dir.glob("frame_*.png"))
            if not frames:
                print(f"FAIL: no frames in {cam_dir}")
                sys.exit(1)
            images.append(frames[0])
    else:  # "all"
        for cam_dir in cam_dirs:
            images.extend(sorted(cam_dir.glob("frame_*.png")))

    print(f"  Collected {len(images)} images ({strategy} strategy)")
    return images


def run_colmap_feature_extraction(image_list: list[Path], database_path: Path, image_root: Path):
    """Run COLMAP feature extraction on the image list.

    Writes features into database_path. image_root must be the common ancestor
    of all image paths (used as the COLMAP image root for relative path tracking).
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)

    print("  Running feature extraction...")
    pycolmap.extract_features(
        database_path=database_path,
        image_path=image_root,
        image_names=[str(p.relative_to(image_root)) for p in image_list],
        device=pycolmap.Device.auto,
    )
    print("  Feature extraction done.")


def run_colmap_matching(database_path: Path):
    """Run COLMAP exhaustive matching via the binary.

    Uses the colmap binary instead of pycolmap — pycolmap's match_exhaustive
    crashes on large image sets when writing matches to the database.
    Falls back to pycolmap only if the binary is not on PATH.
    """
    colmap_bin = shutil.which("colmap")

    if colmap_bin:
        print("  Running exhaustive feature matching (colmap binary)...")
        cmd = [
            colmap_bin, "exhaustive_matcher",
            "--database_path", str(database_path),
            "--SiftMatching.use_gpu", "1",
        ]
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            print(f"  WARNING: colmap binary matcher exited {result.returncode}, trying pycolmap fallback...")
            pycolmap.match_exhaustive(database_path=database_path, device=pycolmap.Device.auto)
    else:
        print("  Running exhaustive feature matching (pycolmap fallback — binary not found)...")
        pycolmap.match_exhaustive(database_path=database_path, device=pycolmap.Device.auto)

    print("  Matching done.")


def run_colmap_mapper(database_path: Path, image_root: Path, output_dir: Path):
    """Run COLMAP sparse mapper to recover camera poses.

    Output: cameras.bin, images.bin, points3D.bin in output_dir/0/
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    mapper_options = pycolmap.IncrementalPipelineOptions()
    mapper_options.min_num_matches = 15  # relax slightly for small camera counts

    print("  Running COLMAP sparse mapper (this may take a few minutes)...")
    reconstructions = pycolmap.incremental_mapping(
        database_path=str(database_path),
        image_path=str(image_root),
        output_path=str(output_dir),
        options=mapper_options,
    )

    if not reconstructions:
        print("FAIL: COLMAP mapper produced no reconstructions.")
        print("  Try: fewer frames, better lighting, or wider camera spread.")
        sys.exit(1)

    # COLMAP may produce multiple reconstructions — pick the largest
    best = max(reconstructions.values(), key=lambda r: r.num_reg_images())
    best_id = max(reconstructions, key=lambda k: reconstructions[k].num_reg_images())
    print(f"  Mapper done. Best reconstruction: {best.num_reg_images()} registered images.")
    return best_id, best


def verify_poses(reconstruction, expected_cameras: int) -> bool:
    """Check that COLMAP recovered poses for all expected cameras.

    Returns True if all cameras have poses, False otherwise.
    """
    registered = reconstruction.num_reg_images()
    if registered < expected_cameras:
        print(f"  WARNING: expected {expected_cameras} cameras, COLMAP only recovered {registered}.")
        print("  Missing cameras will have no pose. Consider re-running with strategy='all'.")
        return False
    print(f"  Verification passed: {registered}/{expected_cameras} cameras have poses.")
    return True


def convert_colmap_to_llff(reconstruction, output_path: Path):
    """Convert COLMAP sparse output to LLFF poses_bounds.npy.

    Output: poses_bounds.npy with shape (N_cameras, 17)
    Each row: [3x5 pose matrix flattened (15) + near_bound + far_bound]

    The 3x5 pose matrix is [R | t | hwf_col], where:
      - R is the 3x3 camera-to-world rotation
      - t is the 3x1 camera-to-world translation
      - hwf_col is [height, width, focal_length] as the 5th column
    """
    cameras = reconstruction.cameras
    images = reconstruction.images
    points = reconstruction.points3D

    if not images:
        print("FAIL: reconstruction has no registered images.")
        sys.exit(1)

    # Compute scene bounds from sparse point cloud for near/far
    if points:
        pts_world = np.array([p.xyz for p in points.values()])  # (N, 3)
    else:
        pts_world = np.zeros((1, 3))

    poses_bounds = []
    for image in sorted(images.values(), key=lambda im: im.name):
        cam = cameras[image.camera_id]

        # Extrinsics: world-to-camera → invert to camera-to-world
        R_w2c = image.rotation_matrix()          # (3, 3)
        t_w2c = image.tvec                        # (3,)
        R_c2w = R_w2c.T
        t_c2w = -R_c2w @ t_w2c                   # camera center in world

        # Intrinsics: focal length (assume SIMPLE_RADIAL or PINHOLE)
        focal = cam.focal_length if hasattr(cam, "focal_length") else cam.params[0]
        h, w = cam.height, cam.width

        # LLFF convention: swap y/z axes (OpenCV → OpenGL/NeRF convention)
        # COLMAP: x right, y down, z forward
        # LLFF:   x right, y up,   z backward  →  multiply cols 1,2 by -1
        pose_c2w = np.column_stack([R_c2w, t_c2w])  # (3, 4)
        pose_c2w[:, 1:3] *= -1                        # flip y and z

        hwf = np.array([[h], [w], [focal]])            # (3, 1)
        pose_3x5 = np.hstack([pose_c2w, hwf])          # (3, 5)

        # Near/far: project all 3D points into this camera, take 5th/95th percentile
        if pts_world.shape[0] > 1:
            pts_cam = (R_w2c @ pts_world.T).T + t_w2c  # (N, 3)
            depths = pts_cam[:, 2]
            depths = depths[depths > 0]
            near = float(np.percentile(depths, 5)) if len(depths) else 0.1
            far = float(np.percentile(depths, 95)) if len(depths) else 100.0
        else:
            near, far = 0.1, 100.0

        row = np.append(pose_3x5.flatten(), [near, far])  # (17,)
        poses_bounds.append(row)

    poses_bounds = np.array(poses_bounds)  # (N_cameras, 17)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(output_path), poses_bounds)
    print(f"  LLFF poses_bounds.npy saved: shape {poses_bounds.shape} → {output_path}")


def run_dense_reconstruction(image_root: Path, sparse_src: Path, dense_dir: Path):
    """Run COLMAP dense reconstruction: undistort → patch_match_stereo → stereo_fusion.

    Requires the COLMAP binary (colmap / colmap.exe) on PATH.
    Produces dense_dir/fused.ply — the dense point cloud 4DGS wants.

    Skip on Windows with --sparse-only; run on the cloud box where GPU is available.
    """
    colmap_bin = shutil.which("colmap")
    if colmap_bin is None:
        print("FAIL: 'colmap' binary not found on PATH.")
        print("  Linux:   apt install colmap")
        print("  Windows: download from github.com/colmap/colmap/releases and add to PATH")
        sys.exit(1)

    dense_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        # Undistort images into MVS-friendly layout
        [
            colmap_bin, "image_undistorter",
            "--image_path", str(image_root),
            "--input_path", str(sparse_src),
            "--output_path", str(dense_dir),
            "--output_type", "COLMAP",
        ],
        # Dense stereo matching (GPU required for reasonable speed)
        [
            colmap_bin, "patch_match_stereo",
            "--workspace_path", str(dense_dir),
            "--workspace_format", "COLMAP",
            "--PatchMatchStereo.geom_consistency", "true",
        ],
        # Fuse depth maps into a single point cloud
        [
            colmap_bin, "stereo_fusion",
            "--workspace_path", str(dense_dir),
            "--workspace_format", "COLMAP",
            "--input_type", "geometric",
            "--output_path", str(dense_dir / "fused.ply"),
        ],
    ]

    step_names = ["image_undistorter", "patch_match_stereo", "stereo_fusion"]
    for name, cmd in zip(step_names, steps):
        print(f"  Running {name}...")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            print(f"FAIL: {name} exited with code {result.returncode}")
            sys.exit(1)

    fused = dense_dir / "fused.ply"
    if fused.exists():
        size_mb = fused.stat().st_size / 1e6
        print(f"  Dense point cloud: {fused}  ({size_mb:.1f} MB)")
    else:
        print("FAIL: fused.ply not produced by stereo_fusion.")
        sys.exit(1)


def run():
    parser = argparse.ArgumentParser(description="Stage 2: COLMAP Pose Recovery")
    parser.add_argument(
        "--sparse-only",
        action="store_true",
        help="Skip dense reconstruction (patch_match_stereo + stereo_fusion). "
             "Use on Windows or CPU-only machines. Dense step requires COLMAP binary + GPU.",
    )
    parser.add_argument(
        "--strategy",
        choices=["one_per_cam", "all"],
        default="one_per_cam",
        help="Image collection strategy. 'one_per_cam' uses only frame_00000 per camera (default, fast). "
             "'all' feeds every frame (slower, use if one_per_cam fails to reconstruct).",
    )
    args = parser.parse_args()

    cfg = load_config()
    images_dir = resolve_path(cfg["stage2"]["images_dir"])
    sparse_dir = resolve_path(cfg["stage2"]["sparse_dir"])
    poses_path = resolve_path(cfg["stage2"]["poses_bounds_path"])

    print("Stage 2: COLMAP Pose Recovery")
    print(f"  Images:        {images_dir}")
    print(f"  COLMAP output: {sparse_dir}")
    print(f"  LLFF output:   {poses_path}")
    if args.sparse_only:
        print("  Mode:          sparse only (--sparse-only)")

    # Load metadata for expected camera count
    metadata_path = images_dir.parent / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
        num_cameras = metadata["num_cameras"]
    else:
        num_cameras = len([p for p in images_dir.iterdir() if p.is_dir() and p.name.startswith("cam")])
        print(f"  WARNING: metadata.json not found, counted {num_cameras} cameras from directories.")

    # Collect images
    image_list = collect_images_for_colmap(images_dir, strategy=args.strategy)

    # Working dirs
    work_dir = sparse_dir.parent.parent / "colmap_workspace"
    work_dir.mkdir(parents=True, exist_ok=True)
    database_path = work_dir / "database.db"
    mapper_output = work_dir / "sparse"
    image_root = images_dir

    # Sparse pipeline (pycolmap — no binary needed)
    run_colmap_feature_extraction(image_list, database_path, image_root)
    run_colmap_matching(database_path)
    best_id, reconstruction = run_colmap_mapper(database_path, image_root, mapper_output)

    verify_poses(reconstruction, num_cameras)

    # Copy sparse output to Contract B location (scene/sparse/0/)
    src = mapper_output / str(best_id)
    sparse_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["cameras.bin", "images.bin", "points3D.bin"]:
        src_file = src / fname
        if src_file.exists():
            shutil.copy2(src_file, sparse_dir / fname)
    print(f"  COLMAP binaries copied to {sparse_dir}")

    # LLFF export
    convert_colmap_to_llff(reconstruction, poses_path)

    # Dense reconstruction (cloud box only — needs COLMAP binary + GPU)
    if not args.sparse_only:
        dense_dir = sparse_dir.parent.parent / "dense"
        run_dense_reconstruction(image_root, src, dense_dir)
        # Copy fused.ply to output location Aditya expects
        fused_dest = sparse_dir.parent.parent / "output" / "fused.ply"
        fused_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dense_dir / "fused.ply", fused_dest)
        print(f"  Dense point cloud: {fused_dest}")

    print()
    print("Stage 2 complete.")
    print(f"  COLMAP sparse: {sparse_dir}/{{cameras,images,points3D}}.bin")
    print(f"  LLFF:          {poses_path}")
    if not args.sparse_only:
        print(f"  Dense PLY:     output/fused.ply")
    print("  Run 'make validate-b' to verify Contract B.")


if __name__ == "__main__":
    run()
