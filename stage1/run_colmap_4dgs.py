"""
Replacement for multipleviewprogress.sh that works on headless GPU servers.
Uses pycolmap (CPU mode) instead of the apt COLMAP binary which requires OpenGL.

Usage (on cloud box):
    cd /workspace/4DGaussians
    python run_colmap_4dgs.py --dataset replay

Output (what 4DGS multipleview loader needs):
    data/multipleview/replay/
        sparse_/
            cameras.bin
            images.bin
            points3D.bin
        points3D_multipleview.ply
        poses_bounds_multipleview.npy
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    import pycolmap
except ImportError:
    print("ERROR: pip install pycolmap")
    sys.exit(1)


def find_colmap_bin() -> str:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    c = shutil.which("colmap") or "/usr/bin/colmap"
    if not Path(c).exists():
        print("ERROR: colmap binary not found. Run: apt install colmap")
        sys.exit(1)
    return c


def prepare_images(dataset_dir: Path, work_dir: Path):
    """Symlink all cam*/frame_*.jpg into a flat images/ folder for COLMAP."""
    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for cam_dir in sorted(dataset_dir.iterdir()):
        if not cam_dir.is_dir() or not cam_dir.name.startswith("cam"):
            continue
        frames = sorted(cam_dir.glob("frame_*.jpg")) or sorted(cam_dir.glob("frame_*.png"))
        if not frames:
            continue
        # Use 5 evenly spaced frames per camera for better overlap detection
        n = min(5, len(frames))
        indices = [int(i * (len(frames) - 1) / (n - 1)) for i in range(n)] if n > 1 else [0]
        for idx, fi in enumerate(indices):
            dest = images_dir / f"{cam_dir.name}_f{idx:02d}.jpg"
            shutil.copy2(frames[fi], dest)
            count += 1
        print(f"  Copied {cam_dir.name} -> {n} frames")

    print(f"  {count} camera images ready")
    return images_dir


def run_feature_extraction(work_dir: Path, images_dir: Path):
    """Run COLMAP feature extraction (binary, CPU SIFT)."""
    colmap = find_colmap_bin()
    db = work_dir / "database.db"

    print("Running feature extraction (CPU SIFT)...")
    cmd = [
        colmap, "feature_extractor",
        "--database_path", str(db),
        "--image_path", str(images_dir),
        "--ImageReader.single_camera_per_folder", "1",
        "--SiftExtraction.use_gpu", "0",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL: feature_extractor")
        print(result.stderr[-2000:])
        sys.exit(1)
    print("  Feature extraction done.")
    return db


def run_matching(db: Path):
    """Run exhaustive matching via pycolmap CPU — no OpenGL needed."""
    print("Running exhaustive matching (pycolmap CPU)...")
    pycolmap.match_exhaustive(
        database_path=db,
        device=pycolmap.Device.cpu,
    )
    print("  Matching done.")


def run_mapper(db: Path, images_dir: Path, work_dir: Path) -> Path:
    """Run COLMAP sparse mapper."""
    colmap = find_colmap_bin()
    sparse_out = work_dir / "sparse"
    sparse_out.mkdir(parents=True, exist_ok=True)

    print("Running sparse mapper...")
    cmd = [
        colmap, "mapper",
        "--database_path", str(db),
        "--image_path", str(images_dir),
        "--output_path", str(sparse_out),
        "--Mapper.min_num_matches", "5",
        "--Mapper.init_min_num_inliers", "5",
        "--Mapper.init_min_tri_angle", "1",
        "--Mapper.abs_pose_min_num_inliers", "5",
        "--Mapper.abs_pose_min_inlier_ratio", "0.02",
        "--Mapper.max_reg_trials", "5",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL: mapper")
        print(result.stderr[-2000:])
        sys.exit(1)

    # Pick best reconstruction folder
    recon_dirs = [p for p in sparse_out.iterdir() if p.is_dir() and p.name.isdigit()]
    if not recon_dirs:
        print("FAIL: mapper produced no reconstruction. Try recording with more overlap between cameras.")
        sys.exit(1)

    best = max(recon_dirs, key=lambda p: (p / "images.bin").stat().st_size if (p / "images.bin").exists() else 0)
    recon = pycolmap.Reconstruction(str(best))
    print(f"  Mapper done: {recon.num_reg_images()} cameras registered.")
    return best, recon


def export_sparse(recon_dir: Path, dataset_dir: Path):
    """Copy cameras.bin, images.bin, points3D.bin to dataset_dir/sparse_/"""
    sparse_dest = dataset_dir / "sparse_"
    sparse_dest.mkdir(exist_ok=True)
    for f in ["cameras.bin", "images.bin", "points3D.bin"]:
        src = recon_dir / f
        if src.exists():
            shutil.copy2(src, sparse_dest / f)
    print(f"  Sparse binaries -> {sparse_dest}")


def export_ply(recon, dataset_dir: Path):
    """Export points3D as PLY for 4DGS."""
    try:
        import open3d as o3d
        pts = np.array([p.xyz for p in recon.points3D.values()])
        colors = np.array([p.color / 255.0 for p in recon.points3D.values()])
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        pcd.colors = o3d.utility.Vector3dVector(colors)
        ply_path = dataset_dir / "points3D_multipleview.ply"
        o3d.io.write_point_cloud(str(ply_path), pcd)
        print(f"  PLY -> {ply_path} ({len(pts)} points)")
    except ImportError:
        print("  SKIP PLY export (pip install open3d) — 4DGS will use random init")


def export_poses_bounds(recon, dataset_dir: Path):
    """Export LLFF poses_bounds_multipleview.npy for 4DGS."""
    images = recon.images
    cameras = recon.cameras
    points = recon.points3D

    pts_world = np.array([p.xyz for p in points.values()]) if points else np.zeros((1, 3))

    poses_bounds = []
    for image in sorted(images.values(), key=lambda im: im.name):
        cam = cameras[image.camera_id]
        xform = image.cam_from_world()
        R_w2c = xform.rotation.matrix()
        t_w2c = xform.translation
        R_c2w = R_w2c.T
        t_c2w = -R_c2w @ t_w2c

        focal = cam.focal_length if hasattr(cam, "focal_length") else cam.params[0]
        h, w = cam.height, cam.width

        pose_c2w = np.column_stack([R_c2w, t_c2w])
        pose_c2w[:, 1:3] *= -1  # COLMAP -> LLFF convention
        hwf = np.array([[h], [w], [focal]])
        pose_3x5 = np.hstack([pose_c2w, hwf])

        if pts_world.shape[0] > 1:
            pts_cam = (R_w2c @ pts_world.T).T + t_w2c
            depths = pts_cam[:, 2]
            depths = depths[depths > 0]
            near = float(np.percentile(depths, 5)) if len(depths) else 0.1
            far = float(np.percentile(depths, 95)) if len(depths) else 100.0
        else:
            near, far = 0.1, 100.0

        poses_bounds.append(np.append(pose_3x5.flatten(), [near, far]))

    poses_bounds = np.array(poses_bounds)
    out = dataset_dir / "poses_bounds_multipleview.npy"
    np.save(str(out), poses_bounds)
    print(f"  poses_bounds -> {out}  shape={poses_bounds.shape}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="Dataset name under data/multipleview/")
    parser.add_argument("--base", default="data/multipleview", help="Base data directory")
    args = parser.parse_args()

    dataset_dir = Path(args.base) / args.dataset
    work_dir = Path("colmap_tmp_py") / args.dataset
    work_dir.mkdir(parents=True, exist_ok=True)

    if not dataset_dir.exists():
        print(f"ERROR: {dataset_dir} not found")
        sys.exit(1)

    print(f"Dataset: {dataset_dir}")

    images_dir = prepare_images(dataset_dir, work_dir)
    db = run_feature_extraction(work_dir, images_dir)
    run_matching(db)
    recon_dir, recon = run_mapper(db, images_dir, work_dir)
    export_sparse(recon_dir, dataset_dir)
    export_ply(recon, dataset_dir)
    export_poses_bounds(recon, dataset_dir)

    print()
    print("=" * 50)
    print(f"DONE. {dataset_dir} is ready for 4DGS training.")
    print("Next:")
    print(f"  Create arguments/multipleview/{args.dataset}.py (copy from another multipleview config)")
    print(f"  python train.py -s data/multipleview/{args.dataset} --port 6017 --expname multipleview/{args.dataset} --configs arguments/multipleview/{args.dataset}.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
