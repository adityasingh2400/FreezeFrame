#!/usr/bin/env python3
"""Run VGGT + Gaussian Splatting on each timestep for 4D reconstruction.

Replaces run_instantsplat.py — uses VGGT instead of MASt3R for ~225x faster init.
VGGT (CVPR 2025 Best Paper) processes all N views in a single forward pass,
producing camera poses, depth maps, and point clouds. No pairwise matching.

Modes:
  quality: VGGT init -> Gaussian Splatting training -> PLY (default)
  fast:    VGGT init -> direct Gaussian PLY (no training, ~12s for 80 frames)

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
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# ── Constants ────────────────────────────────────────────────────────────
GS_TRAIN_ITER = 200          # Default keyframe iterations (was 500)
WARMSTART_ITER = 100          # Iterations for warm-started frames
KEYFRAME_INTERVAL = 10        # Every Nth frame is a full keyframe
TIMEOUT_SECONDS = 600
MAX_INIT_POINTS = 80_000
CONF_PERCENTILE = 50
WARP_VIEWS_PER_GAP = 2         # Synthetic views to generate between each camera pair


# ═════════════════════════════════════════════════════════════════════════
#  COLMAP Binary Format Writers
# ═════════════════════════════════════════════════════════════════════════

def rotmat_to_qvec(R):
    """Convert 3x3 rotation matrix to quaternion (w, x, y, z) for COLMAP."""
    tr = np.trace(R)
    if tr > 0:
        s = 0.5 / np.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return np.array([w, x, y, z])


def write_cameras_bin(path, cameras):
    """Write COLMAP cameras.bin.

    cameras: list of dicts {id, width, height, fx, fy, cx, cy}
    """
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(cameras)))
        for cam in cameras:
            f.write(struct.pack("<I", cam["id"]))
            f.write(struct.pack("<i", 1))  # PINHOLE model
            f.write(struct.pack("<Q", cam["width"]))
            f.write(struct.pack("<Q", cam["height"]))
            f.write(struct.pack("<dddd", cam["fx"], cam["fy"], cam["cx"], cam["cy"]))


def write_cameras_txt(path, cameras):
    """Write COLMAP cameras.txt (InstantSplat reads text format)."""
    with open(path, "w") as f:
        f.write(f"# Camera list with one line of data per camera:\n")
        f.write(f"#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"# Number of cameras: {len(cameras)}\n")
        for cam in cameras:
            f.write(f"{cam['id']} PINHOLE {cam['width']} {cam['height']} "
                    f"{cam['fx']} {cam['fy']} {cam['cx']} {cam['cy']}\n")


def write_images_bin(path, images):
    """Write COLMAP images.bin.

    images: list of dicts {id, qvec (4,), tvec (3,), camera_id, name}
    """
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for img in images:
            f.write(struct.pack("<I", img["id"]))
            for q in img["qvec"]:
                f.write(struct.pack("<d", float(q)))
            for t in img["tvec"]:
                f.write(struct.pack("<d", float(t)))
            f.write(struct.pack("<I", img["camera_id"]))
            f.write(img["name"].encode("utf-8") + b"\x00")
            f.write(struct.pack("<Q", 0))  # num_points2D = 0


def write_images_txt(path, images):
    """Write COLMAP images.txt (InstantSplat reads text format).

    Format: two lines per image — header line then empty POINTS2D line.
    """
    with open(path, "w") as f:
        f.write(f"# Image list with two lines of data per image:\n")
        f.write(f"#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write(f"#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        f.write(f"# Number of images: {len(images)}\n")
        for img in images:
            q = img["qvec"]
            t = img["tvec"]
            f.write(f"{img['id']} {float(q[0])} {float(q[1])} {float(q[2])} {float(q[3])} "
                    f"{float(t[0])} {float(t[1])} {float(t[2])} "
                    f"{img['camera_id']} {img['name']}\n")
            f.write("\n")  # empty POINTS2D line


def write_points3D_bin(path, xyz, rgb_uint8):
    """Write COLMAP points3D.bin.

    xyz:       (N, 3) float64
    rgb_uint8: (N, 3) uint8
    """
    N = len(xyz)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", N))
        for i in range(N):
            f.write(struct.pack(
                "<Q3d3BdQ",
                i + 1,
                float(xyz[i, 0]), float(xyz[i, 1]), float(xyz[i, 2]),
                int(rgb_uint8[i, 0]), int(rgb_uint8[i, 1]), int(rgb_uint8[i, 2]),
                0.0,  # reprojection error
                0,     # track_length
            ))


# ═════════════════════════════════════════════════════════════════════════
#  Gaussian PLY Writer (fast mode — no training needed)
# ═════════════════════════════════════════════════════════════════════════

SH_C0 = 0.28209479177387814


def compute_adaptive_scale(xyz):
    """Estimate Gaussian scale from scene geometry."""
    extent = np.max(xyz, axis=0) - np.min(xyz, axis=0)
    scene_size = np.linalg.norm(extent)
    avg_spacing = scene_size / (len(xyz) ** (1.0 / 3.0))
    return avg_spacing * 0.4


def write_gaussian_ply(path, xyz, rgb_float, scale=None):
    """Write VGGT point cloud as compact 3DGS-compatible Gaussian PLY.

    Outputs SH degree 0 only (no f_rest) — 17 floats/vertex instead of 62.
    This cuts file size by ~72% with no visual difference for fast mode
    (f_rest would be all zeros anyway without training).

    xyz:       (N, 3) float  — world-space positions
    rgb_float: (N, 3) float  — colors in [0, 1]
    scale:     Gaussian scale (auto-computed from scene if None)
    """
    N = len(xyz)
    if scale is None:
        scale = compute_adaptive_scale(xyz)

    log_scale = np.float32(np.log(max(scale, 1e-7)))

    # Compact format: position + normal + DC color + opacity + scale + rotation
    # 17 floats = 68 bytes/vertex (vs 248 bytes with full SH)
    props = [
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4"),
        ("f_dc_0", "<f4"), ("f_dc_1", "<f4"), ("f_dc_2", "<f4"),
        ("opacity", "<f4"),
        ("scale_0", "<f4"), ("scale_1", "<f4"), ("scale_2", "<f4"),
        ("rot_0", "<f4"), ("rot_1", "<f4"), ("rot_2", "<f4"), ("rot_3", "<f4"),
    ]

    data = np.zeros(N, dtype=props)
    data["x"] = xyz[:, 0].astype(np.float32)
    data["y"] = xyz[:, 1].astype(np.float32)
    data["z"] = xyz[:, 2].astype(np.float32)

    # Convert RGB [0,1] to SH DC coefficients
    sh_dc = (rgb_float - 0.5) / SH_C0
    data["f_dc_0"] = sh_dc[:, 0].astype(np.float32)
    data["f_dc_1"] = sh_dc[:, 1].astype(np.float32)
    data["f_dc_2"] = sh_dc[:, 2].astype(np.float32)

    # Gaussian parameters
    data["opacity"] = np.float32(2.0)             # inverse_sigmoid(~0.88)
    data["scale_0"] = log_scale
    data["scale_1"] = log_scale
    data["scale_2"] = log_scale
    data["rot_0"] = np.float32(1.0)               # identity quaternion

    # Write PLY
    header_lines = [
        "ply",
        "format binary_little_endian 1.0",
        f"element vertex {N}",
    ]
    for name, _ in props:
        header_lines.append(f"property float {name}")
    header_lines.append("end_header")
    header = "\n".join(header_lines) + "\n"

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())


# ═════════════════════════════════════════════════════════════════════════
#  Warm-Start: Read Trained PLY for Previous-Frame Initialization
# ═════════════════════════════════════════════════════════════════════════

def read_gaussian_ply_positions(ply_path):
    """Extract positions and colors from a trained Gaussian Splat PLY file.

    Reads just the XYZ + SH DC coefficients (converted back to RGB).
    Used to warm-start the next frame's training from the previous frame's
    optimized Gaussian positions.

    Returns:
        xyz:       (N, 3) float64  — Gaussian positions
        rgb_uint8: (N, 3) uint8    — colors derived from SH DC
    """
    ply_path = Path(ply_path)
    with open(ply_path, "rb") as f:
        # Parse PLY header
        header_lines = []
        while True:
            line = f.readline().decode("ascii").strip()
            header_lines.append(line)
            if line == "end_header":
                break

        # Extract vertex count and property names
        n_vertices = 0
        properties = []
        for line in header_lines:
            if line.startswith("element vertex"):
                n_vertices = int(line.split()[-1])
            elif line.startswith("property") and not line.startswith("property list"):
                parts = line.split()
                if len(parts) >= 3:
                    properties.append((parts[2], parts[1]))  # (name, type)

        # Build numpy dtype from properties
        type_map = {"float": "<f4", "double": "<f8", "uchar": "<u1",
                     "int": "<i4", "uint": "<u4", "short": "<i2", "ushort": "<u2"}
        dt = [(name, type_map.get(ptype, "<f4")) for name, ptype in properties]

        data = np.frombuffer(f.read(n_vertices * np.dtype(dt).itemsize), dtype=dt)

    # Extract positions
    for f in ["x", "y", "z"]:
        if f not in data.dtype.names:
            raise ValueError(f"PLY missing required field '{f}': {ply_path}")
    xyz = np.column_stack([data["x"].astype(np.float64),
                           data["y"].astype(np.float64),
                           data["z"].astype(np.float64)])

    # Extract colors from SH DC coefficients (reverse of RGB→SH conversion)
    if all(f in data.dtype.names for f in ["f_dc_0", "f_dc_1", "f_dc_2"]):
        sh_dc = np.column_stack([data["f_dc_0"], data["f_dc_1"], data["f_dc_2"]])
        rgb_float = np.clip(sh_dc * SH_C0 + 0.5, 0, 1)
        rgb_uint8 = (rgb_float * 255).astype(np.uint8)
    else:
        # Fallback: gray
        rgb_uint8 = np.full((len(xyz), 3), 128, dtype=np.uint8)

    return xyz, rgb_uint8


# ═════════════════════════════════════════════════════════════════════════
#  VGGT Model
# ═════════════════════════════════════════════════════════════════════════

def load_vggt(device="cuda", vggt_dir=None):
    """Load VGGT model. Downloads weights from HuggingFace on first run."""
    import torch

    # Ensure VGGT is importable
    if vggt_dir:
        sys.path.insert(0, str(vggt_dir))
    try:
        from vggt.models.vggt import VGGT
    except ImportError:
        # Try common install locations
        for p in ["/workspace/vggt", os.path.expanduser("~/vggt")]:
            if Path(p).exists():
                sys.path.insert(0, p)
                break
        from vggt.models.vggt import VGGT

    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16

    print("  Loading VGGT-1B model (first run downloads ~2GB)...")
    model = VGGT.from_pretrained("facebook/VGGT-1B").to(device)
    model.eval()
    print(f"  [OK] VGGT loaded on {device} (dtype={dtype})")
    return model, dtype


def run_vggt(model, dtype, image_paths, device="cuda"):
    """Run VGGT on a set of images. Returns cameras + point cloud.

    Returns dict with:
        extrinsic: (N, 3, 4) — [R|t] camera-from-world (OpenCV convention)
        intrinsic: (N, 3, 3) — camera intrinsic matrices
        point_map: (N, H, W, 3) — world-space 3D points per pixel
        depth_conf: (N, H, W) — depth confidence scores
        proc_hw: (H, W) — preprocessed image dimensions
    """
    import torch
    from vggt.utils.load_fn import load_and_preprocess_images
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri
    from vggt.utils.geometry import unproject_depth_map_to_point_map

    images = load_and_preprocess_images([str(p) for p in image_paths]).to(device)
    proc_h, proc_w = images.shape[-2], images.shape[-1]

    with torch.no_grad():
        # Aggregator runs with mixed precision (heavy compute)
        with torch.cuda.amp.autocast(dtype=dtype):
            images_batch = images[None]  # add batch dim: [1, N, C, H, W]
            aggregated_tokens_list, ps_idx = model.aggregator(images_batch)

        # Heads run in full precision for accuracy (matches VGGT README pattern)
        pose_enc = model.camera_head(aggregated_tokens_list)[-1]
        extrinsic, intrinsic = pose_encoding_to_extri_intri(
            pose_enc, images_batch.shape[-2:]
        )

        depth_map, depth_conf = model.depth_head(
            aggregated_tokens_list, images_batch, ps_idx
        )

        # World-space point cloud from depth unprojection
        # (more accurate than point_map head per VGGT docs)
        point_map = unproject_depth_map_to_point_map(
            depth_map.squeeze(0), extrinsic.squeeze(0), intrinsic.squeeze(0)
        )

    # Helper to convert tensor or ndarray to numpy
    def to_np(x):
        if hasattr(x, 'cpu'):
            return x.cpu().numpy()
        return np.array(x) if not isinstance(x, np.ndarray) else x

    # Normalize shapes — handle both (N,3,4) and (N,4,4) extrinsics
    ext = to_np(extrinsic.squeeze(0))
    if ext.ndim == 3 and ext.shape[-2] == 4:
        ext = ext[:, :3, :]  # [N, 3, 4]

    # Normalize depth_conf — handle possible trailing dim (N,H,W,1)
    conf = to_np(depth_conf.squeeze(0))
    while conf.ndim > 3:
        conf = conf.squeeze(-1)

    pm = to_np(point_map)

    return {
        "extrinsic": ext,                                  # (N, 3, 4)
        "intrinsic": to_np(intrinsic.squeeze(0)),          # (N, 3, 3)
        "point_map": pm,                                   # (N, H, W, 3)
        "depth_conf": conf,                                # (N, H, W)
        "proc_hw": (proc_h, proc_w),
    }


# ═════════════════════════════════════════════════════════════════════════
#  Point Cloud Extraction
# ═════════════════════════════════════════════════════════════════════════

def extract_point_cloud(vggt_out, image_paths, max_points=MAX_INIT_POINTS):
    """Extract colored point cloud from VGGT output.

    Returns:
        xyz:       (M, 3) float64  — world-space positions
        rgb_uint8: (M, 3) uint8    — colors
        rgb_float: (M, 3) float32  — colors in [0, 1]
    """
    from PIL import Image

    point_map = vggt_out["point_map"]   # (N, H, W, 3)
    depth_conf = vggt_out["depth_conf"] # (N, H, W)
    N, H, W = point_map.shape[:3]

    # Load original images resized to VGGT resolution for color extraction
    colors = np.zeros((N, H, W, 3), dtype=np.uint8)
    for i, path in enumerate(image_paths):
        img = Image.open(path).convert("RGB").resize((W, H), Image.BILINEAR)
        colors[i] = np.array(img)

    # Flatten all views
    all_xyz = point_map.reshape(-1, 3)
    all_rgb = colors.reshape(-1, 3)
    all_conf = depth_conf.reshape(-1)

    # Filter by confidence
    if CONF_PERCENTILE > 0:
        threshold = np.percentile(all_conf, CONF_PERCENTILE)
        mask = all_conf >= threshold
        all_xyz = all_xyz[mask]
        all_rgb = all_rgb[mask]

    # Filter invalid points (NaN, Inf, extremely far)
    valid = np.isfinite(all_xyz).all(axis=1)
    if valid.sum() > 0:
        dists = np.linalg.norm(all_xyz[valid], axis=1)
        dist_limit = np.percentile(dists, 99) * 2
        valid &= np.linalg.norm(all_xyz, axis=1) < dist_limit
    all_xyz = all_xyz[valid]
    all_rgb = all_rgb[valid]

    # Subsample if too many points
    if len(all_xyz) > max_points:
        idx = np.random.choice(len(all_xyz), max_points, replace=False)
        all_xyz = all_xyz[idx]
        all_rgb = all_rgb[idx]

    return all_xyz, all_rgb, all_rgb.astype(np.float32) / 255.0


# ═════════════════════════════════════════════════════════════════════════
#  Depth-Warp View Augmentation
# ═════════════════════════════════════════════════════════════════════════

def interpolate_cameras(ext_a, K_a, ext_b, K_b, t):
    """Interpolate between two camera poses at ratio t ∈ [0, 1].

    Uses linear interpolation for translation and SLERP-like interpolation
    for rotation (via rotation matrix blending + re-orthogonalization).

    Returns (ext_interp, K_interp) — both in the same format as inputs.
    """
    R_a, t_a = ext_a[:3, :3], ext_a[:3, 3]
    R_b, t_b = ext_b[:3, :3], ext_b[:3, 3]

    # Interpolate translation linearly
    t_interp = (1 - t) * t_a + t * t_b

    # Interpolate rotation: blend + SVD re-orthogonalize
    R_blend = (1 - t) * R_a + t * R_b
    U, _, Vt = np.linalg.svd(R_blend)
    R_interp = U @ Vt
    # Ensure proper rotation (det = +1)
    if np.linalg.det(R_interp) < 0:
        U[:, -1] *= -1
        R_interp = U @ Vt

    ext_interp = np.zeros((3, 4), dtype=np.float64)
    ext_interp[:3, :3] = R_interp
    ext_interp[:3, 3] = t_interp

    # Interpolate intrinsics linearly
    K_interp = (1 - t) * K_a + t * K_b

    return ext_interp, K_interp


def depth_warp_view(source_img, point_map, depth_conf, target_ext, target_K,
                    target_hw):
    """Warp a source camera's image to a target viewpoint using its point map.

    For each pixel in the source image:
      1. Look up its world-space 3D position from point_map
      2. Project that 3D point into the target camera using target_ext + target_K
      3. Paint the source pixel's color at the projected location

    Returns:
      warped_img: (H, W, 3) uint8 — the warped image (0 where no data)
      valid_mask: (H, W) bool — which pixels have valid data
    """
    H_t, W_t = target_hw
    H_s, W_s = point_map.shape[:2]

    # World-space points for every source pixel
    pts_world = point_map.reshape(-1, 3)  # (H*W, 3)

    # Filter valid points
    valid = np.isfinite(pts_world).all(axis=1)
    if depth_conf is not None:
        conf_flat = depth_conf.reshape(-1)
        valid &= conf_flat > np.percentile(conf_flat[valid], 20)

    pts_valid = pts_world[valid]

    # Project into target camera: p_cam = R @ p_world + t
    R_t = target_ext[:3, :3]
    t_t = target_ext[:3, 3]
    pts_cam = (R_t @ pts_valid.T).T + t_t  # (M, 3)

    # Filter points behind camera
    in_front = pts_cam[:, 2] > 0.01
    pts_cam = pts_cam[in_front]
    valid_indices = np.where(valid)[0][in_front]

    # Project to pixel coordinates
    fx, fy = target_K[0, 0], target_K[1, 1]
    cx, cy = target_K[0, 2], target_K[1, 2]
    px = (fx * pts_cam[:, 0] / pts_cam[:, 2] + cx).astype(np.int32)
    py = (fy * pts_cam[:, 1] / pts_cam[:, 2] + cy).astype(np.int32)

    # Scale from VGGT resolution to target resolution
    scale_x = W_t / W_s
    scale_y = H_t / H_s
    px = (px * scale_x).astype(np.int32)
    py = (py * scale_y).astype(np.int32)

    # Clip to image bounds
    in_bounds = (px >= 0) & (px < W_t) & (py >= 0) & (py < H_t)
    px, py = px[in_bounds], py[in_bounds]
    valid_indices = valid_indices[in_bounds]
    depths = pts_cam[:, 2][in_bounds]

    # Get source pixel colors (at original resolution, indexed from VGGT grid)
    src_y = valid_indices // W_s
    src_x = valid_indices % W_s
    # Scale source indices to original image resolution
    src_y_orig = np.clip((src_y * (source_img.shape[0] / H_s)).astype(np.int32), 0, source_img.shape[0] - 1)
    src_x_orig = np.clip((src_x * (source_img.shape[1] / W_s)).astype(np.int32), 0, source_img.shape[1] - 1)
    colors = source_img[src_y_orig, src_x_orig]

    # Z-buffer: for overlapping projections, keep the closest
    warped = np.zeros((H_t, W_t, 3), dtype=np.uint8)
    z_buf = np.full((H_t, W_t), np.inf, dtype=np.float32)
    valid_mask = np.zeros((H_t, W_t), dtype=bool)

    for i in range(len(px)):
        if depths[i] < z_buf[py[i], px[i]]:
            z_buf[py[i], px[i]] = depths[i]
            warped[py[i], px[i]] = colors[i]
            valid_mask[py[i], px[i]] = True

    return warped, valid_mask


def generate_warped_views(vggt_out, image_paths, views_per_gap=WARP_VIEWS_PER_GAP,
                          use_gemini=False):
    """Generate synthetic intermediate views between each camera pair.

    For each adjacent camera pair (i, i+1), generates `views_per_gap`
    intermediate views by depth-warping both cameras and blending.

    If use_gemini=True, enhances each synthetic view with Imagen 3 (hole
    filling) + Gemini Flash Image (photorealistic cleanup).

    Returns:
        synth_images: list of (H, W, 3) uint8 arrays
        synth_extrinsics: list of (3, 4) arrays
        synth_intrinsics: list of (3, 3) arrays
        synth_names: list of filename strings
    """
    from PIL import Image

    ext = vggt_out["extrinsic"]    # (N, 3, 4)
    K = vggt_out["intrinsic"]      # (N, 3, 3)
    point_map = vggt_out["point_map"]  # (N, H, W, 3)
    depth_conf = vggt_out["depth_conf"]  # (N, H, W)
    N = len(ext)

    # Load original images
    orig_images = []
    for p in image_paths:
        img = np.array(Image.open(p).convert("RGB"))
        orig_images.append(img)
    H_orig, W_orig = orig_images[0].shape[:2]

    synth_images = []
    synth_extrinsics = []
    synth_intrinsics = []
    synth_names = []
    hole_masks = []  # for Gemini enhancement

    for i in range(N - 1):
        for v in range(views_per_gap):
            t = (v + 1) / (views_per_gap + 1)

            # Interpolated camera pose
            ext_mid, K_mid = interpolate_cameras(ext[i], K[i], ext[i + 1], K[i + 1], t)

            # Scale intrinsics from VGGT resolution to original resolution
            proc_h, proc_w = vggt_out["proc_hw"]
            K_mid_scaled = K_mid.copy()
            K_mid_scaled[0, :] *= W_orig / proc_w
            K_mid_scaled[1, :] *= H_orig / proc_h

            # Warp both neighboring cameras to the intermediate viewpoint
            warp_a, mask_a = depth_warp_view(
                orig_images[i], point_map[i], depth_conf[i],
                ext_mid, K_mid, (H_orig, W_orig))
            warp_b, mask_b = depth_warp_view(
                orig_images[i + 1], point_map[i + 1], depth_conf[i + 1],
                ext_mid, K_mid, (H_orig, W_orig))

            # Blend: where both have data, weight by proximity to source camera
            blended = np.zeros((H_orig, W_orig, 3), dtype=np.float32)
            weight_sum = np.zeros((H_orig, W_orig, 1), dtype=np.float32)

            w_a = 1.0 - t
            w_b = t

            if mask_a.any():
                blended[mask_a] += warp_a[mask_a].astype(np.float32) * w_a
                weight_sum[mask_a] += w_a
            if mask_b.any():
                blended[mask_b] += warp_b[mask_b].astype(np.float32) * w_b
                weight_sum[mask_b] += w_b

            # Normalize blended regions
            valid = weight_sum.squeeze(-1) > 0
            blended[valid] /= weight_sum[valid]
            result = blended.clip(0, 255).astype(np.uint8)

            # Track holes before fallback fill
            hole_mask = ~valid

            # Fill remaining holes with nearest neighbor (baseline fallback)
            if not valid.all():
                fallback = orig_images[i] if t < 0.5 else orig_images[i + 1]
                result[~valid] = fallback[~valid]

            synth_images.append(result)
            synth_extrinsics.append(ext_mid)
            synth_intrinsics.append(K_mid)
            synth_names.append(f"synth_{i}_{i+1}_{v:02d}.jpg")
            hole_masks.append(hole_mask)

    # ── Gemini enhancement pass ─────────────────────────────────────
    if use_gemini and synth_images:
        try:
            from synth_views import enhance_batch
            print(f"    Enhancing {len(synth_images)} synthetic views with Gemini...")
            t0 = time.time()
            synth_images = enhance_batch(synth_images, hole_masks, max_workers=4)
            elapsed = time.time() - t0
            print(f"    [OK] Gemini enhancement done ({elapsed:.1f}s)")
        except Exception as e:
            print(f"    [WARN] Gemini enhancement unavailable: {e}")
            print(f"    Using depth-warp only (still {len(synth_images)} views)")

    return synth_images, synth_extrinsics, synth_intrinsics, synth_names


# ═════════════════════════════════════════════════════════════════════════
#  COLMAP Scene Writer
# ═════════════════════════════════════════════════════════════════════════

def write_colmap_scene(scene_dir, vggt_out, image_paths, image_names,
                       warm_start_ply=None, n_views=4, augment_views=True,
                       use_gemini=False):
    """Write VGGT output as COLMAP scene for InstantSplat's Gaussian training.

    If augment_views=True, generates depth-warped intermediate views between
    each camera pair, boosting training from 4 views to ~10-13 views. This
    dramatically improves reconstruction quality for sparse camera setups.

    InstantSplat expects files under sparse_{total_views}/0/.
    """
    from PIL import Image

    scene_dir = Path(scene_dir)
    image_dir = scene_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    ext = vggt_out["extrinsic"]   # (N, 3, 4)
    K = vggt_out["intrinsic"]     # (N, 3, 3)
    proc_h, proc_w = vggt_out["proc_hw"]
    N = len(ext)

    # Get original image dimensions and copy images
    orig_img = Image.open(image_paths[0])
    W_orig, H_orig = orig_img.size
    scale_x = W_orig / proc_w
    scale_y = H_orig / proc_h

    for src in image_paths:
        shutil.copy2(str(src), str(image_dir / Path(src).name))

    # Start with real camera entries
    cameras = []
    images = []
    for i in range(N):
        cameras.append({
            "id": i + 1,
            "width": W_orig,
            "height": H_orig,
            "fx": float(K[i, 0, 0] * scale_x),
            "fy": float(K[i, 1, 1] * scale_y),
            "cx": float(K[i, 0, 2] * scale_x),
            "cy": float(K[i, 1, 2] * scale_y),
        })
        R = ext[i, :3, :3]
        t = ext[i, :3, 3]
        images.append({
            "id": i + 1,
            "qvec": rotmat_to_qvec(R),
            "tvec": t,
            "camera_id": i + 1,
            "name": image_names[i],
        })

    # Generate and add synthetic warped views
    if augment_views and N >= 2:
        synth_imgs, synth_exts, synth_Ks, synth_names = generate_warped_views(
            vggt_out, image_paths, views_per_gap=WARP_VIEWS_PER_GAP,
            use_gemini=use_gemini)

        for j, (simg, sext, sK, sname) in enumerate(
                zip(synth_imgs, synth_exts, synth_Ks, synth_names)):
            idx = N + j + 1
            # Save synthetic image
            Image.fromarray(simg).save(str(image_dir / sname), quality=95)

            # Scale intrinsics to original resolution
            cameras.append({
                "id": idx,
                "width": W_orig,
                "height": H_orig,
                "fx": float(sK[0, 0] * scale_x),
                "fy": float(sK[1, 1] * scale_y),
                "cx": float(sK[0, 2] * scale_x),
                "cy": float(sK[1, 2] * scale_y),
            })
            images.append({
                "id": idx,
                "qvec": rotmat_to_qvec(sext[:3, :3]),
                "tvec": sext[:3, 3],
                "camera_id": idx,
                "name": sname,
            })

    total_views = len(cameras)
    sparse_dir = scene_dir / f"sparse_{total_views}" / "0"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    # Point cloud: warm-start from previous frame or fresh from VGGT
    if warm_start_ply and Path(warm_start_ply).exists():
        xyz, rgb_uint8 = read_gaussian_ply_positions(warm_start_ply)
        if len(xyz) > MAX_INIT_POINTS:
            idx = np.random.choice(len(xyz), MAX_INIT_POINTS, replace=False)
            xyz, rgb_uint8 = xyz[idx], rgb_uint8[idx]
    else:
        xyz, rgb_uint8, _ = extract_point_cloud(vggt_out, image_paths)

    # Write COLMAP files
    write_cameras_txt(str(sparse_dir / "cameras.txt"), cameras)
    write_images_txt(str(sparse_dir / "images.txt"), images)
    write_points3D_bin(str(sparse_dir / "points3D.bin"), xyz, rgb_uint8)

    confidence = np.zeros(len(xyz), dtype=np.float32)
    np.save(str(sparse_dir / "confidence_dsp.npy"), confidence)

    return len(xyz), total_views


# ═════════════════════════════════════════════════════════════════════════
#  Per-Timestep Processing
# ═════════════════════════════════════════════════════════════════════════

def find_output_ply(model_path):
    """Find best output PLY from Gaussian training output."""
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


def run_timestep(model, dtype, timestep_dir, output_ply_path, mode="quality",
                 trainer_dir=None, train_iter=GS_TRAIN_ITER,
                 work_dir=None, gpu_id=0, device="cuda",
                 warm_start_ply=None, use_gemini=False):
    """Process a single timestep with VGGT + optional Gaussian training.

    If warm_start_ply is provided, initializes Gaussians from the previous
    frame's trained output instead of from VGGT's raw point cloud. This
    dramatically reduces required iterations (200→100) since the optimizer
    starts near the solution.
    """
    timestep_dir = Path(timestep_dir)
    output_ply_path = Path(output_ply_path)

    image_files = sorted(
        list(timestep_dir.glob("images/*.jpg")) + list(timestep_dir.glob("images/*.png"))
    )
    if not image_files:
        print(f"\n  [SKIP] No images in {timestep_dir}")
        return False

    image_names = [f.name for f in image_files]
    timestep_name = timestep_dir.name
    n_views = len(image_files)

    # ── VGGT Initialization (~0.1s for 4 views) ─────────────────────
    vggt_out = run_vggt(model, dtype, image_files, device=device)

    if mode == "fast":
        # Direct point cloud -> Gaussian PLY (no training)
        xyz, _, rgb_float = extract_point_cloud(vggt_out, image_files)
        if len(xyz) < 100:
            print(f"\n  [FAIL] Too few points ({len(xyz)})")
            return False

        output_ply_path.parent.mkdir(parents=True, exist_ok=True)
        write_gaussian_ply(str(output_ply_path), xyz, rgb_float)
        size_kb = output_ply_path.stat().st_size / 1024
        print(f"[OK] {output_ply_path.name} ({size_kb:.0f} KB, {len(xyz)} pts)")
        return True

    # ── Quality mode: COLMAP output + Gaussian training ─────────────
    work_dir = Path(work_dir or "vggt_work").resolve()
    scene_dir = work_dir / "scenes" / timestep_name
    model_path = work_dir / "models" / timestep_name

    if scene_dir.exists():
        shutil.rmtree(str(scene_dir))
    model_path.mkdir(parents=True, exist_ok=True)

    n_pts, total_views = write_colmap_scene(
        scene_dir, vggt_out, image_files, image_names,
        warm_start_ply=warm_start_ply, use_gemini=use_gemini)

    # ── Gaussian Splatting Training ─────────────────────────────────
    trainer_dir = Path(trainer_dir)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    train_cmd = [
        sys.executable, "./train.py",
        "-s", str(scene_dir),
        "-m", str(model_path),
        "-r", "1",
        "--n_views", str(total_views),
        "--iterations", str(train_iter),
    ]

    try:
        result = subprocess.run(
            train_cmd,
            cwd=str(trainer_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-800:]
            print(f"\n  [FAIL] train.py returned {result.returncode}")
            if stderr_tail:
                print(f"  stderr: ...{stderr_tail}")

            # Fallback: try without InstantSplat-specific flags
            print("  Retrying with vanilla 3DGS flags...")
            train_cmd_vanilla = [
                sys.executable, "./train.py",
                "-s", str(scene_dir),
                "-m", str(model_path),
                "-r", "1",
                "--iterations", str(train_iter),
            ]
            result = subprocess.run(
                train_cmd_vanilla,
                cwd=str(trainer_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr or "")[-800:]
                print(f"\n  [FAIL] train.py (vanilla) returned {result.returncode}")
                if stderr_tail:
                    print(f"  stderr: ...{stderr_tail}")
                return False

    except subprocess.TimeoutExpired:
        print(f"\n  [FAIL] train.py timed out after {TIMEOUT_SECONDS}s")
        return False

    # ── Collect output PLY ──────────────────────────────────────────
    out_ply = find_output_ply(model_path)
    if out_ply is None:
        print(f"\n  [FAIL] No PLY in {model_path}")
        return False

    output_ply_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(out_ply), str(output_ply_path))
    size_kb = out_ply.stat().st_size / 1024
    ws_tag = "warm" if warm_start_ply else "key"
    print(f"[OK] {output_ply_path.name} ({size_kb:.0f} KB, {n_pts} pts, {total_views}v, {ws_tag})")

    # ── Cleanup ─────────────────────────────────────────────────────
    if scene_dir.exists():
        shutil.rmtree(str(scene_dir), ignore_errors=True)
    if model_path.exists():
        shutil.rmtree(str(model_path), ignore_errors=True)

    return True


# ═════════════════════════════════════════════════════════════════════════
#  Main Loop
# ═════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════
#  Multi-GPU Worker
# ═════════════════════════════════════════════════════════════════════════

def _gpu_worker(gpu_id, ts_indices, input_dir, output_dir, mode, trainer_dir,
                keyframe_iter, warmstart_iter, keyframe_interval,
                vggt_dir, work_dir, use_gemini=False):
    """Process a contiguous chunk of timesteps on a single GPU.

    Each chunk's first frame is always a keyframe. Subsequent frames
    warm-start from the previous frame's output.
    """
    import torch
    device = f"cuda:{gpu_id}"
    model, dtype = load_vggt(device=device, vggt_dir=vggt_dir)

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    succeeded = 0
    failed = 0
    prev_ply = None

    for i, ts_num in enumerate(ts_indices):
        ts_dir = input_dir / f"t_{ts_num:05d}"
        out_name = f"time_{ts_num - 1:05d}.ply"
        out_path = output_dir / out_name

        is_keyframe = (i == 0) or (i % keyframe_interval == 0)
        iters = keyframe_iter if is_keyframe else warmstart_iter
        warm_ply = None if is_keyframe else prev_ply
        tag = "KEY" if is_keyframe else "warm"

        print(f"  [GPU {gpu_id}] [{ts_num:3d}] {ts_dir.name} ({tag}, {iters} iter)... ",
              end="", flush=True)
        step_start = time.time()

        ok = run_timestep(
            model, dtype, ts_dir, out_path,
            mode=mode, trainer_dir=trainer_dir, train_iter=iters,
            work_dir=f"{work_dir}_gpu{gpu_id}", gpu_id=gpu_id, device=device,
            warm_start_ply=warm_ply, use_gemini=use_gemini,
        )
        if ok:
            succeeded += 1
            prev_ply = str(out_path)
            step_elapsed = time.time() - step_start
            print(f" ({step_elapsed:.1f}s)")
        else:
            failed += 1
            prev_ply = None  # Reset warm-start chain on failure

    # Free GPU memory
    del model
    torch.cuda.empty_cache()
    return succeeded, failed


def run_all(input_dir, output_dir, mode="quality", trainer_dir=None,
            gpu_id=0, start=1, end=None, skip_existing=True,
            train_iter=GS_TRAIN_ITER, vggt_dir=None, work_dir=None,
            multi_gpu=False, keyframe_interval=KEYFRAME_INTERVAL,
            keyframe_iter=None, warmstart_iter=WARMSTART_ITER,
            use_gemini=False):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if keyframe_iter is None:
        keyframe_iter = train_iter

    timestep_dirs = sorted([
        d for d in input_dir.iterdir()
        if d.is_dir() and d.name.startswith("t_")
    ])
    if not timestep_dirs:
        print(f"[FAIL] No t_* directories in {input_dir}")
        raise SystemExit(1)

    if end is None:
        end = len(timestep_dirs)

    if mode == "quality" and trainer_dir:
        trainer_path = Path(trainer_dir)
        if not (trainer_path / "train.py").exists():
            print(f"[FAIL] train.py not found in {trainer_dir}")
            print(f"       Set --trainer-dir to your InstantSplat or 3DGS clone")
            raise SystemExit(1)

    # Build list of timestep numbers to process
    ts_nums = []
    for ts_dir in timestep_dirs:
        ts_num = int(ts_dir.name.split("_")[1])
        if ts_num < start or ts_num > end:
            continue
        out_name = f"time_{ts_num - 1:05d}.ply"
        out_path = output_dir / out_name
        if skip_existing and out_path.exists() and out_path.stat().st_size > 1000:
            continue
        ts_nums.append(ts_num)

    if not ts_nums:
        print("All timesteps already processed. Nothing to do.")
        return 0, 0

    # ── Detect GPUs and choose strategy ─────────────────────────────
    import torch
    n_gpus = torch.cuda.device_count() if multi_gpu else 1

    n_keyframes = len(range(0, len(ts_nums), keyframe_interval))
    n_warmstart = len(ts_nums) - n_keyframes

    print(f"\nProcessing {len(ts_nums)} timesteps ({start}-{end})")
    print(f"Mode: {mode}")
    if mode == "quality":
        print(f"Trainer: {trainer_dir}")
        print(f"Keyframes: {n_keyframes} × {keyframe_iter} iter")
        print(f"Warm-start: {n_warmstart} × {warmstart_iter} iter")
        print(f"Keyframe interval: every {keyframe_interval} frames")
        print(f"GPUs: {n_gpus}")
    print(f"Output: {output_dir}")
    print()

    total_start = time.time()

    if n_gpus > 1 and mode == "quality":
        # ── Multi-GPU: split timesteps into contiguous chunks ───────
        import concurrent.futures
        import multiprocessing

        chunks = np.array_split(ts_nums, n_gpus)
        chunks = [c.tolist() for c in chunks if len(c) > 0]
        actual_gpus = len(chunks)

        print(f"Multi-GPU: splitting {len(ts_nums)} timesteps across {actual_gpus} GPUs")
        for i, chunk in enumerate(chunks):
            print(f"  GPU {i}: timesteps {chunk[0]}-{chunk[-1]} ({len(chunk)} frames)")
        print()

        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=actual_gpus, mp_context=ctx
        ) as pool:
            futures = []
            for i, chunk in enumerate(chunks):
                f = pool.submit(
                    _gpu_worker, i, chunk, str(input_dir), str(output_dir),
                    mode, str(trainer_dir), keyframe_iter, warmstart_iter,
                    keyframe_interval, vggt_dir, work_dir or "vggt_work",
                    use_gemini,
                )
                futures.append(f)

            succeeded = 0
            failed = 0
            for f in concurrent.futures.as_completed(futures):
                s, fa = f.result()
                succeeded += s
                failed += fa
    else:
        # ── Single-GPU: sequential with warm-starting ───────────────
        device = f"cuda:{gpu_id}" if gpu_id >= 0 else "cpu"
        print("Loading VGGT model...")
        model, dtype = load_vggt(device=device, vggt_dir=vggt_dir)

        succeeded = 0
        failed = 0
        prev_ply = None

        for i, ts_num in enumerate(ts_nums):
            ts_dir = input_dir / f"t_{ts_num:05d}"
            out_name = f"time_{ts_num - 1:05d}.ply"
            out_path = output_dir / out_name

            is_keyframe = (i == 0) or (i % keyframe_interval == 0)
            iters = keyframe_iter if is_keyframe else warmstart_iter
            warm_ply = None if is_keyframe else prev_ply
            tag = "KEY" if is_keyframe else "warm"

            elapsed_so_far = time.time() - total_start
            avg = elapsed_so_far / max(succeeded, 1) if succeeded > 0 else 0
            remaining = (len(ts_nums) - i) * avg if avg > 0 else 0
            eta = f" ETA {int(remaining // 60)}m{int(remaining % 60)}s" if avg > 0 else ""

            print(f"[{ts_num:3d}/{end}] {ts_dir.name} ({tag}, {iters} iter)... ",
                  end="", flush=True)
            step_start = time.time()

            ok = run_timestep(
                model, dtype, ts_dir, out_path,
                mode=mode, trainer_dir=trainer_dir, train_iter=iters,
                work_dir=work_dir, gpu_id=gpu_id, device=device,
                warm_start_ply=warm_ply, use_gemini=use_gemini,
            )
            if ok:
                succeeded += 1
                prev_ply = str(out_path)
                step_elapsed = time.time() - step_start
                print(f" ({step_elapsed:.1f}s){eta}")
            else:
                failed += 1
                prev_ply = None  # Reset warm-start chain on failure

    total_elapsed = time.time() - total_start
    mins = int(total_elapsed // 60)
    secs = int(total_elapsed % 60)

    print(f"\n{'='*60}")
    print(f"  DONE: {succeeded} OK, {failed} failed")
    print(f"  Time: {mins}m {secs}s")
    print(f"  Output: {output_dir}")
    if succeeded > 0:
        print(f"  Avg per timestep: {total_elapsed / succeeded:.1f}s")
        if n_gpus > 1:
            print(f"  GPUs used: {n_gpus}")
    print(f"{'='*60}")

    return succeeded, failed


def main():
    parser = argparse.ArgumentParser(
        description="VGGT + Gaussian Splatting per-timestep 4D reconstruction")
    parser.add_argument("--input", type=str, default="instantsplat_input",
                        help="Directory with t_00001/ ... t_00080/ folders")
    parser.add_argument("--output", type=str, default="instantsplat_output",
                        help="Directory for output PLY files")
    parser.add_argument("--mode", choices=["quality", "fast"], default="quality",
                        help="quality: VGGT+GS training (default), fast: VGGT-only PLY")
    parser.add_argument("--trainer-dir", type=str, default="/workspace/InstantSplat",
                        help="Path to InstantSplat or 3DGS clone (for quality mode)")
    parser.add_argument("--vggt-dir", type=str, default=None,
                        help="Path to VGGT repo (if not pip-installed)")
    parser.add_argument("--work-dir", type=str, default="vggt_work",
                        help="Working directory for intermediate files")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--train-iter", type=int, default=GS_TRAIN_ITER,
                        help=f"Keyframe training iterations (default: {GS_TRAIN_ITER})")
    parser.add_argument("--warmstart-iter", type=int, default=WARMSTART_ITER,
                        help=f"Warm-started frame iterations (default: {WARMSTART_ITER})")
    parser.add_argument("--keyframe-interval", type=int, default=KEYFRAME_INTERVAL,
                        help=f"Full re-init every N frames (default: {KEYFRAME_INTERVAL})")
    parser.add_argument("--multi-gpu", action="store_true",
                        help="Use all available GPUs in parallel")
    parser.add_argument("--gemini", action="store_true",
                        help="Use Gemini to enhance synthetic views (needs GEMINI_API_KEY)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-process even if output PLY already exists")
    args = parser.parse_args()

    run_all(
        input_dir=args.input,
        output_dir=args.output,
        mode=args.mode,
        trainer_dir=args.trainer_dir,
        gpu_id=args.gpu,
        start=args.start,
        end=args.end,
        skip_existing=not args.no_skip,
        train_iter=args.train_iter,
        vggt_dir=args.vggt_dir,
        work_dir=args.work_dir,
        multi_gpu=args.multi_gpu,
        keyframe_interval=args.keyframe_interval,
        keyframe_iter=args.train_iter,
        warmstart_iter=args.warmstart_iter,
        use_gemini=args.gemini,
    )


if __name__ == "__main__":
    main()
