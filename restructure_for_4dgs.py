#!/usr/bin/env python3
"""Restructure Divij's COLMAP output into the 4DGS MultipleView format.

Divij ran COLMAP with multi-frame input (15 frames × 4 cameras = 48 images).
The 4DGS MultipleView loader expects ONE image per camera named `imageN.jpg`,
where N is the camera number. The loader then reads all frames from `camNN/`
directories using frame counts from disk.

This script:
  1. Reads images.bin, filters out poorly-registered cameras (cam01 has 0.04%
     match rate — it's noise, not signal), deduplicates to one entry per
     good camera (picks the image with the most 2D point observations)
  2. Rewrites images.bin with `imageN.jpg` naming and sequential camera IDs
  3. Rewrites cameras.bin with matching sequential camera IDs starting at 1
  4. Converts dense fused.ply → points3D_multipleview.ply (downsampled to <50k)
     Falls back to sparse points3D.bin if dense cloud unavailable
  5. Copies poses_bounds.npy → poses_bounds_multipleview.npy
  6. Creates the final directory layout

Input:  scene/dense/fused.ply + scene/sparse/0/{cameras,images}.bin +
        scene/poses_bounds.npy
Output: data/multipleview/replay/ with the 4DGS-expected structure
"""

import argparse
import collections
import os
import shutil
import struct
import sys
from pathlib import Path

import numpy as np


# ── COLMAP binary readers ────────────────────────────────────────────────────

def read_images_binary(path):
    images = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            image_id = struct.unpack("<I", f.read(4))[0]
            qvec = struct.unpack("<4d", f.read(32))
            tvec = struct.unpack("<3d", f.read(24))
            camera_id = struct.unpack("<I", f.read(4))[0]
            name = b""
            while True:
                c = f.read(1)
                if c == b"\x00":
                    break
                name += c
            num_points2D = struct.unpack("<Q", f.read(8))[0]
            xys = []
            point3D_ids = []
            for _ in range(num_points2D):
                xy = struct.unpack("<2d", f.read(16))
                pid = struct.unpack("<q", f.read(8))[0]
                xys.append(xy)
                point3D_ids.append(pid)
            images[image_id] = {
                "qvec": qvec,
                "tvec": tvec,
                "camera_id": camera_id,
                "name": name.decode("utf-8"),
                "xys": xys,
                "point3D_ids": point3D_ids,
            }
    return images


def read_cameras_binary(path):
    cameras = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            camera_id = struct.unpack("<I", f.read(4))[0]
            model_id = struct.unpack("<i", f.read(4))[0]
            width = struct.unpack("<Q", f.read(8))[0]
            height = struct.unpack("<Q", f.read(8))[0]
            num_params = {0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 12}[model_id]
            params = struct.unpack(f"<{num_params}d", f.read(num_params * 8))
            cameras[camera_id] = {
                "model_id": model_id,
                "width": width,
                "height": height,
                "params": params,
            }
    return cameras


def read_points3D_binary(path):
    points = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            pid = struct.unpack("<Q", f.read(8))[0]
            xyz = struct.unpack("<3d", f.read(24))
            rgb = struct.unpack("<3B", f.read(3))
            error = struct.unpack("<d", f.read(8))[0]
            track_len = struct.unpack("<Q", f.read(8))[0]
            f.read(track_len * 8)  # skip track entries (image_id + point2D_idx)
            points[pid] = {"xyz": xyz, "rgb": rgb, "error": error}
    return points


# ── COLMAP binary writers ────────────────────────────────────────────────────

def write_images_binary(images, path):
    """Write images dict in COLMAP binary format."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for image_id, img in sorted(images.items()):
            f.write(struct.pack("<I", image_id))
            f.write(struct.pack("<4d", *img["qvec"]))
            f.write(struct.pack("<3d", *img["tvec"]))
            f.write(struct.pack("<I", img["camera_id"]))
            f.write(img["name"].encode("utf-8") + b"\x00")
            f.write(struct.pack("<Q", len(img["xys"])))
            for xy, pid in zip(img["xys"], img["point3D_ids"]):
                f.write(struct.pack("<2d", *xy))
                f.write(struct.pack("<q", pid))


def write_cameras_binary(cameras, path):
    """Write cameras dict in COLMAP binary format."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(cameras)))
        for camera_id, cam in sorted(cameras.items()):
            f.write(struct.pack("<I", camera_id))
            f.write(struct.pack("<i", cam["model_id"]))
            f.write(struct.pack("<Q", cam["width"]))
            f.write(struct.pack("<Q", cam["height"]))
            f.write(struct.pack(f"<{len(cam['params'])}d", *cam["params"]))


# ── PLY writer ───────────────────────────────────────────────────────────────

def write_ply(xyz, rgb, path):
    """Write a simple PLY point cloud."""
    n = len(xyz)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        for i in range(n):
            f.write(struct.pack("<3f", *xyz[i]))
            f.write(struct.pack("<3B", *rgb[i]))


def downsample_points(xyz, rgb, max_points=50000):
    """Voxel downsample to at most max_points via increasing voxel size."""
    if len(xyz) <= max_points:
        return xyz, rgb
    voxel_size = 0.02
    cur_xyz, cur_rgb = xyz, rgb
    while len(cur_xyz) > max_points:
        voxel_keys = np.floor(cur_xyz / voxel_size).astype(np.int64)
        _, unique_idx = np.unique(voxel_keys, axis=0, return_index=True)
        cur_xyz = cur_xyz[unique_idx]
        cur_rgb = cur_rgb[unique_idx]
        print(f"  Downsampled to {len(cur_xyz)} points (voxel_size={voxel_size:.3f})")
        voxel_size *= 1.5
    return cur_xyz, cur_rgb


# ── Main restructure logic ───────────────────────────────────────────────────

def extract_cam_number(name):
    """Extract camera number from COLMAP image name like 'cam03/frame_00051.jpg'."""
    parts = name.split("/")
    if len(parts) >= 2 and parts[0].startswith("cam"):
        return int(parts[0][3:])
    return None


MIN_MATCH_RATE = 0.005  # 0.5% — cameras below this are unreliable


def pick_best_per_camera(images):
    """Select one image per camera — the one with the most matched 3D points.
    
    Filters out cameras with fewer than MIN_MATCH_RATE of their 2D features
    matched to 3D points, as those have unreliable poses.
    """
    by_cam = collections.defaultdict(list)
    for image_id, img in images.items():
        cam_num = extract_cam_number(img["name"])
        if cam_num is None:
            print(f"  [WARN] Could not parse camera number from '{img['name']}', skipping")
            continue
        n_matched = sum(1 for p in img["point3D_ids"] if p >= 0)
        n_total = len(img["point3D_ids"])
        by_cam[cam_num].append((n_matched, n_total, image_id, img))

    best = {}
    rejected = {}
    for cam_num, entries in sorted(by_cam.items()):
        entries.sort(reverse=True)
        best_matched, best_total, best_id, best_img = entries[0]
        match_rate = best_matched / best_total if best_total > 0 else 0

        if match_rate < MIN_MATCH_RATE:
            rejected[cam_num] = (match_rate, len(entries))
            print(f"  cam{cam_num:02d}: REJECTED — best match rate {match_rate:.4f} "
                  f"({best_matched}/{best_total}), {len(entries)} frames registered. "
                  f"Pose is unreliable.")
            continue

        print(f"  cam{cam_num:02d}: picked image_id={best_id} "
              f"('{best_img['name']}', {best_matched} matched pts, "
              f"match rate {match_rate:.3f}, {len(entries)} candidates)")
        best[cam_num] = best_img

    if rejected:
        print(f"\n  Rejected {len(rejected)} camera(s) with unreliable poses: "
              f"{['cam'+str(c).zfill(2) for c in rejected.keys()]}")
    if len(best) < 2:
        print("[FAIL] Need at least 2 cameras with reliable poses")
        sys.exit(1)

    return best


def read_dense_ply(path):
    """Read a COLMAP fused.ply (binary little-endian, x/y/z/nx/ny/nz/r/g/b)."""
    import struct as _struct
    with open(path, "rb") as f:
        n_vertices = None
        while True:
            line = f.readline().decode("ascii", errors="replace").strip()
            if line.startswith("element vertex"):
                n_vertices = int(line.split()[-1])
            if line == "end_header":
                break
        if n_vertices is None:
            print(f"[FAIL] Could not parse vertex count from {path}")
            sys.exit(1)

        vertex_size = 3 * 4 + 3 * 4 + 3 * 1  # 3 float xyz + 3 float normal + 3 uint8 rgb
        data = f.read(n_vertices * vertex_size)

    xyz = np.zeros((n_vertices, 3), dtype=np.float32)
    rgb = np.zeros((n_vertices, 3), dtype=np.uint8)
    for i in range(n_vertices):
        offset = i * vertex_size
        xyz[i] = _struct.unpack_from("<3f", data, offset)
        rgb[i] = _struct.unpack_from("<3B", data, offset + 24)

    mask = ~(np.isnan(xyz).any(axis=1) | np.isinf(xyz).any(axis=1))
    if mask.sum() < len(xyz):
        print(f"  Removed {len(xyz) - mask.sum()} NaN/Inf points")
        xyz, rgb = xyz[mask], rgb[mask]

    return xyz, rgb


def restructure(scene_dir, output_dir, image_source_dir=None):
    scene_dir = Path(scene_dir)
    output_dir = Path(output_dir)

    sparse_in = scene_dir / "sparse" / "0"
    assert (sparse_in / "images.bin").exists(), f"Missing {sparse_in / 'images.bin'}"
    assert (sparse_in / "cameras.bin").exists(), f"Missing {sparse_in / 'cameras.bin'}"

    dense_ply = scene_dir / "dense" / "fused.ply"
    sparse_pts = sparse_in / "points3D.bin"

    # ── Step 1: Read COLMAP output ───────────────────────────────────────
    print("\n[1/6] Reading COLMAP binary files...")
    images = read_images_binary(str(sparse_in / "images.bin"))
    cameras = read_cameras_binary(str(sparse_in / "cameras.bin"))
    print(f"  {len(images)} registered images, {len(cameras)} camera models")

    # ── Step 2: Pick one best image per camera (filters bad ones) ────────
    print("\n[2/6] Selecting best pose per camera (filtering unreliable cameras)...")
    best = pick_best_per_camera(images)
    registered_cams = sorted(best.keys())
    print(f"  Using cameras: {['cam'+str(c).zfill(2) for c in registered_cams]}")

    # ── Step 3: Rewrite images.bin with imageN.jpg naming ────────────────
    print("\n[3/6] Rewriting images.bin with 4DGS-compatible naming...")
    new_images = {}
    old_cam_to_new = {}
    for new_id, cam_num in enumerate(registered_cams, start=1):
        img = best[cam_num]
        old_cam_id = img["camera_id"]
        old_cam_to_new[old_cam_id] = new_id
        new_images[new_id] = {
            "qvec": img["qvec"],
            "tvec": img["tvec"],
            "camera_id": new_id,
            "name": f"image{cam_num}.jpg",
            "xys": img["xys"],
            "point3D_ids": img["point3D_ids"],
        }
        print(f"  image_id={new_id}: '{img['name']}' → 'image{cam_num}.jpg' "
              f"(cam_id {old_cam_id} → {new_id})")

    # ── Step 4: Rewrite cameras.bin with sequential IDs ──────────────────
    print("\n[4/6] Rewriting cameras.bin with sequential IDs...")
    new_cameras = {}
    for old_id, new_id in sorted(old_cam_to_new.items(), key=lambda x: x[1]):
        cam = cameras[old_id]
        new_cameras[new_id] = cam
        print(f"  camera_id {old_id} → {new_id} "
              f"({cam['width']}x{cam['height']}, focal={cam['params'][0]:.1f})")

    # ── Step 5: Load point cloud (dense preferred, sparse fallback) ──────
    if dense_ply.exists():
        print(f"\n[5/6] Loading DENSE point cloud from {dense_ply}...")
        xyz, rgb = read_dense_ply(str(dense_ply))
        print(f"  Loaded {len(xyz)} dense points")
        xyz, rgb = downsample_points(xyz, rgb, max_points=50000)
    elif sparse_pts.exists():
        print(f"\n[5/6] WARNING: Dense cloud not found, falling back to SPARSE "
              f"points3D.bin (expect poor results)...")
        points = read_points3D_binary(str(sparse_pts))
        xyz = np.array([p["xyz"] for p in points.values()])
        rgb = np.array([p["rgb"] for p in points.values()], dtype=np.uint8)
        xyz, rgb = downsample_points(xyz, rgb, max_points=50000)
    else:
        print("[FAIL] No point cloud found (need dense/fused.ply or sparse/0/points3D.bin)")
        sys.exit(1)
    print(f"  Final point count: {len(xyz)}")

    # ── Step 6: Write output ─────────────────────────────────────────────
    print(f"\n[6/6] Writing output to {output_dir}...")

    sparse_out = output_dir / "sparse_"
    sparse_out.mkdir(parents=True, exist_ok=True)

    write_images_binary(new_images, str(sparse_out / "images.bin"))
    write_cameras_binary(new_cameras, str(sparse_out / "cameras.bin"))
    print(f"  Wrote {sparse_out / 'images.bin'} ({len(new_images)} images)")
    print(f"  Wrote {sparse_out / 'cameras.bin'} ({len(new_cameras)} cameras)")

    ply_path = output_dir / "points3D_multipleview.ply"
    write_ply(xyz, rgb, str(ply_path))
    print(f"  Wrote {ply_path} ({len(xyz)} points)")

    poses_src = scene_dir / "poses_bounds.npy"
    poses_dst = output_dir / "poses_bounds_multipleview.npy"
    if poses_src.exists():
        shutil.copy2(str(poses_src), str(poses_dst))
        arr = np.load(str(poses_src))
        print(f"  Copied poses_bounds → {poses_dst} (shape {arr.shape})")
    else:
        print(f"  [WARN] {poses_src} not found — video render path won't work")

    # Symlink camera frame directories (only for accepted cameras)
    img_src = image_source_dir or scene_dir / "images"
    img_src = Path(img_src)
    first_cam = None
    for cam_num in registered_cams:
        cam_dir_name = f"cam{cam_num:02d}"
        src = img_src / cam_dir_name
        dst = output_dir / cam_dir_name
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink():
                dst.unlink()
            else:
                shutil.rmtree(str(dst))
        if src.exists():
            os.symlink(str(src.resolve()), str(dst))
            n_frames = len(list(src.glob("frame_*.jpg")))
            print(f"  Symlinked {dst} → {src} ({n_frames} frames)")
            if first_cam is None:
                first_cam = cam_dir_name
        else:
            print(f"  [WARN] Source frames not found at {src}")

    # The 4DGS loader hardcodes cam01 for frame counting (line 32 of
    # multipleview_dataset.py). Create a cam01 symlink pointing to the
    # first real camera so it can count frames without crashing.
    cam01_dst = output_dir / "cam01"
    if first_cam and first_cam != "cam01":
        first_cam_src = img_src / first_cam
        if cam01_dst.exists() or cam01_dst.is_symlink():
            if cam01_dst.is_symlink():
                cam01_dst.unlink()
            else:
                shutil.rmtree(str(cam01_dst))
        os.symlink(str(first_cam_src.resolve()), str(cam01_dst))
        print(f"  Symlinked cam01 → {first_cam_src} (compatibility shim for 4DGS loader)")

    # ── Verification ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  VERIFICATION")
    print("=" * 60)
    ok = True
    for f in ["sparse_/images.bin", "sparse_/cameras.bin", "points3D_multipleview.ply"]:
        p = output_dir / f
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        status = "OK" if exists and size > 0 else "MISSING"
        print(f"  [{status}] {f} ({size:,} bytes)")
        if not exists or size == 0:
            ok = False

    for cam_num in registered_cams:
        d = output_dir / f"cam{cam_num:02d}"
        if d.exists():
            n = len(list(d.glob("frame_*.jpg")))
            print(f"  [OK] cam{cam_num:02d}/ ({n} frames)")
        else:
            print(f"  [MISSING] cam{cam_num:02d}/")
            ok = False

    cam01_exists = (output_dir / "cam01").exists()
    print(f"  [{'OK' if cam01_exists else 'MISSING'}] cam01/ (loader compatibility)")

    if ok:
        print(f"\n  ALL CHECKS PASSED — ready for 4DGS training")
        print(f"  Cameras: {len(registered_cams)} ({', '.join('cam'+str(c).zfill(2) for c in registered_cams)})")
        print(f"  Point cloud: {len(xyz)} points ({'dense' if dense_ply.exists() else 'sparse'})")
        print(f"  Train with: -s {output_dir}")
    else:
        print("\n  SOME CHECKS FAILED — review warnings above")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Restructure COLMAP output for 4DGS MultipleView format")
    parser.add_argument("--scene-dir", type=str, default="scene",
                        help="Path to scene/ directory with Divij's COLMAP output")
    parser.add_argument("--output-dir", type=str,
                        default="4DGaussians/data/multipleview/replay",
                        help="Output directory for 4DGS MultipleView format")
    parser.add_argument("--image-dir", type=str, default=None,
                        help="Override path to camera frame directories")
    args = parser.parse_args()
    restructure(args.scene_dir, args.output_dir, args.image_dir)


if __name__ == "__main__":
    main()
