"""Stage 2: COLMAP Pose Recovery — produces 4DGS MultipleView-compatible output.

INPUT:  Contract A — scene/images/cam01/frame_00001.jpg, ... + metadata.json
OUTPUT: 4DGS MultipleView format:
          {data_dir}/sparse_/cameras.bin, images.bin
          {data_dir}/points3D_multipleview.ply    (downsampled <40k points)
          {data_dir}/poses_bounds_multipleview.npy (LLFF format)

Usage:
    # On the cloud box (has GPU for dense reconstruction):
    python3 scripts/stage2_colmap.py

    # Sparse only (no GPU needed, uses sparse points instead of dense):
    python3 scripts/stage2_colmap.py --sparse-only

    # Point at a custom data directory:
    python3 scripts/stage2_colmap.py --data-dir /workspace/Replay/data/multipleview/replay

    # Use fewer frames per camera for faster COLMAP:
    python3 scripts/stage2_colmap.py --n-per-cam 3
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

try:
    import pycolmap
except ImportError:
    print("ERROR: pycolmap not installed. Run: pip install pycolmap")
    sys.exit(1)

ROOT_DIR = Path(__file__).resolve().parent.parent


def collect_images(images_dir, strategy="one_per_cam", n_per_cam=5):
    """Collect images for COLMAP. Returns (flat_dir, image_names).

    The 4DGS multipleview_dataset.py extracts camera numbers from COLMAP
    image names via: number = os.path.basename(extr.name)[5:-4]
    This expects names like 'image1.jpg' → number='1' → cam01.

    So we copy one frame per camera into a flat temp directory as image1.jpg,
    image2.jpg, etc. For n_per_cam strategy, we still only run COLMAP on
    one frame per camera (the middle one) since cameras are static.
    """
    cam_dirs = sorted(
        p for p in images_dir.iterdir()
        if p.is_dir() and p.name.startswith("cam")
    )
    if not cam_dirs:
        print(f"[FAIL] No cam* directories found in {images_dir}")
        sys.exit(1)

    flat_dir = images_dir.parent / "colmap_images"
    if flat_dir.exists():
        shutil.rmtree(flat_dir)
    flat_dir.mkdir()

    image_map = {}
    for cam_dir in cam_dirs:
        frames = sorted(cam_dir.glob("frame_*.jpg")) or sorted(cam_dir.glob("frame_*.png"))
        if not frames:
            print(f"[FAIL] No frames in {cam_dir}")
            sys.exit(1)

        cam_num = cam_dir.name.replace("cam", "")
        if strategy == "one_per_cam":
            src = frames[0]
        elif strategy == "n_per_cam":
            mid = len(frames) // 2
            src = frames[mid]
        else:
            mid = len(frames) // 2
            src = frames[mid]

        dest_name = f"image{cam_num}.jpg"
        shutil.copy2(src, flat_dir / dest_name)
        image_map[dest_name] = cam_dir.name

    print(f"[OK] Prepared {len(image_map)} images for COLMAP: {list(image_map.keys())}")
    return flat_dir, image_map


def find_colmap_bin():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    candidates = [
        shutil.which("colmap"),
        "/usr/bin/colmap",
        "/usr/local/bin/colmap",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    print("[FAIL] colmap binary not found. Install: apt install colmap")
    sys.exit(1)


def run_cmd(cmd, label=""):
    print(f"  Running {label}...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[FAIL] {label} exited with code {result.returncode}")
        sys.exit(1)
    print(f"  {label} done.")


def run_sparse_reconstruction(flat_dir, work_dir):
    """Full COLMAP sparse pipeline: extract → match → map."""
    colmap_bin = find_colmap_bin()
    db_path = work_dir / "database.db"
    sparse_out = work_dir / "sparse"

    if db_path.exists():
        db_path.unlink()

    run_cmd([
        colmap_bin, "feature_extractor",
        "--database_path", str(db_path),
        "--image_path", str(flat_dir),
        "--ImageReader.single_camera_per_folder", "0",
        "--SiftExtraction.use_gpu", "1",
        "--SiftExtraction.max_image_size", "4096",
        "--SiftExtraction.max_num_features", "16384",
        "--SiftExtraction.estimate_affine_shape", "1",
        "--SiftExtraction.domain_size_pooling", "1",
    ], "feature_extractor (GPU SIFT)")

    print("  Running exhaustive matching (pycolmap CPU)...")
    pycolmap.match_exhaustive(database_path=db_path, device=pycolmap.Device.cpu)
    print("  Matching done.")

    sparse_out.mkdir(parents=True, exist_ok=True)
    run_cmd([
        colmap_bin, "mapper",
        "--database_path", str(db_path),
        "--image_path", str(flat_dir),
        "--output_path", str(sparse_out),
        "--Mapper.min_num_matches", "10",
        "--Mapper.init_min_num_inliers", "10",
        "--Mapper.init_min_tri_angle", "2",
        "--Mapper.abs_pose_min_num_inliers", "10",
        "--Mapper.abs_pose_min_inlier_ratio", "0.05",
    ], "mapper")

    recon_dirs = [d for d in sparse_out.iterdir() if d.is_dir() and d.name.isdigit()]
    if not recon_dirs:
        print("[FAIL] COLMAP produced no reconstructions.")
        sys.exit(1)

    best_dir = max(
        recon_dirs,
        key=lambda p: (p / "images.bin").stat().st_size if (p / "images.bin").exists() else 0
    )
    recon = pycolmap.Reconstruction(str(best_dir))
    print(f"[OK] Reconstruction: {recon.num_reg_images()} images registered (folder {best_dir.name})")
    return best_dir, recon


def run_dense_reconstruction(flat_dir, sparse_dir, work_dir):
    """COLMAP dense pipeline: undistort → patch_match → fusion."""
    colmap_bin = find_colmap_bin()
    dense_dir = work_dir / "dense"
    dense_dir.mkdir(parents=True, exist_ok=True)

    run_cmd([
        colmap_bin, "image_undistorter",
        "--image_path", str(flat_dir),
        "--input_path", str(sparse_dir),
        "--output_path", str(dense_dir),
        "--output_type", "COLMAP",
    ], "image_undistorter")

    run_cmd([
        colmap_bin, "patch_match_stereo",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--PatchMatchStereo.geom_consistency", "true",
    ], "patch_match_stereo (GPU)")

    run_cmd([
        colmap_bin, "stereo_fusion",
        "--workspace_path", str(dense_dir),
        "--workspace_format", "COLMAP",
        "--input_type", "geometric",
        "--output_path", str(dense_dir / "fused.ply"),
    ], "stereo_fusion")

    fused = dense_dir / "fused.ply"
    if not fused.exists():
        print("[FAIL] fused.ply not produced")
        sys.exit(1)

    print(f"[OK] Dense point cloud: {fused} ({fused.stat().st_size / 1e6:.1f} MB)")
    return fused


def downsample_ply(input_ply, output_ply, target_points=40000):
    """Voxel-downsample a point cloud to under target_points."""
    try:
        import open3d as o3d
    except ImportError:
        print("[WARN] open3d not installed, copying PLY without downsampling")
        shutil.copy2(input_ply, output_ply)
        return

    pcd = o3d.io.read_point_cloud(str(input_ply))
    original = len(pcd.points)
    print(f"  Original points: {original}")

    if original <= target_points:
        o3d.io.write_point_cloud(str(output_ply), pcd)
        print(f"[OK] Already under {target_points}, no downsampling needed")
        return

    voxel_size = 0.01
    for _ in range(50):
        downsampled = pcd.voxel_down_sample(voxel_size)
        if len(downsampled.points) <= target_points:
            break
        voxel_size *= 1.3

    o3d.io.write_point_cloud(str(output_ply), downsampled)
    print(f"[OK] Downsampled {original} → {len(downsampled.points)} points (voxel={voxel_size:.4f})")


def sparse_points_to_ply(reconstruction, output_ply):
    """Convert COLMAP sparse 3D points to a PLY file (fallback when no dense)."""
    from plyfile import PlyData, PlyElement

    points = reconstruction.points3D
    if not points:
        print("[WARN] No sparse 3D points, generating random initialization")
        xyz = np.random.uniform(-1, 1, (2000, 3)).astype(np.float32)
        rgb = np.random.uniform(0, 255, (2000, 3)).astype(np.float32)
    else:
        xyz = np.array([p.xyz for p in points.values()], dtype=np.float32)
        rgb = np.array([p.color for p in points.values()], dtype=np.float32)

    normals = np.zeros_like(xyz)
    dtype = [
        ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
        ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
        ('red', 'f4'), ('green', 'f4'), ('blue', 'f4'),
    ]
    elements = np.empty(xyz.shape[0], dtype=dtype)
    attributes = np.concatenate([xyz, normals, rgb], axis=1)
    elements[:] = list(map(tuple, attributes))
    el = PlyElement.describe(elements, 'vertex')
    PlyData([el]).write(str(output_ply))
    print(f"[OK] Sparse points PLY: {xyz.shape[0]} points → {output_ply}")


def convert_colmap_to_llff(reconstruction, output_path):
    """Convert COLMAP output to LLFF poses_bounds.npy (N, 17)."""
    cameras = reconstruction.cameras
    images = reconstruction.images
    points = reconstruction.points3D

    if not images:
        print("[FAIL] No registered images in reconstruction")
        sys.exit(1)

    pts_world = np.zeros((1, 3))
    if points:
        pts_world = np.array([p.xyz for p in points.values()], dtype=np.float64)

    poses_bounds = []
    for image in sorted(images.values(), key=lambda im: im.name):
        cam = cameras[image.camera_id]

        cfw = image.cam_from_world()
        R_w2c = cfw.rotation.matrix()
        t_w2c = cfw.translation
        R_c2w = R_w2c.T
        t_c2w = -R_c2w @ t_w2c

        focal = cam.focal_length
        h, w = cam.height, cam.width

        pose_c2w = np.column_stack([R_c2w, t_c2w])
        pose_c2w[:, 1:3] *= -1

        hwf = np.array([[h], [w], [focal]])
        pose_3x5 = np.hstack([pose_c2w, hwf])

        if pts_world.shape[0] > 1:
            pts_cam = (R_w2c @ pts_world.T).T + t_w2c
            depths = pts_cam[:, 2]
            depths = depths[depths > 0]
            near = float(np.percentile(depths, 5)) if len(depths) else 0.1
            far = float(np.percentile(depths, 95)) if len(depths) else 100.0
            near = max(near, 0.01)
        else:
            near, far = 0.1, 100.0

        row = np.append(pose_3x5.flatten(), [near, far])
        poses_bounds.append(row)

    poses_bounds = np.array(poses_bounds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(output_path), poses_bounds)
    print(f"[OK] LLFF poses_bounds: shape {poses_bounds.shape} → {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Stage 2: COLMAP → 4DGS MultipleView format")
    parser.add_argument("--sparse-only", action="store_true",
                        help="Skip dense reconstruction (no GPU needed)")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Path to the dataset directory containing cam01/, cam02/, etc.")
    parser.add_argument("--n-per-cam", type=int, default=1,
                        help="Frames per camera for COLMAP (default: 1, middle frame)")
    parser.add_argument("--strategy", choices=["one_per_cam", "n_per_cam"], default="one_per_cam")
    args = parser.parse_args()

    start = time.time()

    if args.data_dir:
        data_dir = Path(args.data_dir)
        images_dir = data_dir
    else:
        data_dir = ROOT_DIR / "scene"
        images_dir = data_dir / "images"

    if not images_dir.exists():
        print(f"[FAIL] Images directory not found: {images_dir}")
        sys.exit(1)

    metadata_path = data_dir / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            meta = json.load(f)
        num_cameras = meta["num_cameras"]
    else:
        num_cameras = len([p for p in images_dir.iterdir() if p.is_dir() and p.name.startswith("cam")])

    print("=" * 60)
    print("  Stage 2: COLMAP Pose Recovery")
    print("=" * 60)
    print(f"  Data dir:    {data_dir}")
    print(f"  Images:      {images_dir}")
    print(f"  Cameras:     {num_cameras}")
    print(f"  Dense:       {'yes' if not args.sparse_only else 'no (sparse only)'}")
    print()

    # Prepare flat image directory with imageN.jpg naming for 4DGS compatibility
    flat_dir, image_map = collect_images(images_dir, args.strategy, args.n_per_cam)

    # COLMAP workspace
    work_dir = data_dir / "colmap_workspace"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Run sparse reconstruction
    best_dir, recon = run_sparse_reconstruction(flat_dir, work_dir)

    registered = recon.num_reg_images()
    if registered < num_cameras:
        print(f"[WARN] Only {registered}/{num_cameras} cameras recovered poses")
    else:
        print(f"[OK] All {registered} cameras have poses")

    # === OUTPUT: sparse_ directory (4DGS MultipleView expects this) ===
    sparse_out = data_dir / "sparse_"
    if sparse_out.exists():
        shutil.rmtree(sparse_out)
    sparse_out.mkdir()
    for fname in ["cameras.bin", "images.bin", "points3D.bin"]:
        src = best_dir / fname
        if src.exists():
            shutil.copy2(src, sparse_out / fname)
    print(f"[OK] Sparse output → {sparse_out}")

    # === OUTPUT: points3D_multipleview.ply ===
    ply_output = data_dir / "points3D_multipleview.ply"
    if not args.sparse_only:
        fused_ply = run_dense_reconstruction(flat_dir, best_dir, work_dir)
        downsample_ply(fused_ply, ply_output)
    else:
        sparse_points_to_ply(recon, ply_output)

    # === OUTPUT: poses_bounds_multipleview.npy ===
    llff_output = data_dir / "poses_bounds_multipleview.npy"
    convert_colmap_to_llff(recon, llff_output)

    # Cleanup temp flat directory
    shutil.rmtree(flat_dir, ignore_errors=True)

    elapsed = time.time() - start
    print()
    print("=" * 60)
    print("  Stage 2 COMPLETE")
    print("=" * 60)
    print(f"  Time:         {int(elapsed)}s")
    print(f"  sparse_/      {sparse_out}")
    print(f"  PLY:          {ply_output}")
    print(f"  LLFF:         {llff_output}")
    print()
    print("  These files + the cam*/ frame folders = ready for 4DGS training.")
    print("  Next: python3 run_training.py --fast")


if __name__ == "__main__":
    main()
