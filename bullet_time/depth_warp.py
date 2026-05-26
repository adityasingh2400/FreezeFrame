"""Depth-based view warping for geometric frame interpolation.

Uses MiDaS monocular depth estimation + forward warping to create
geometrically correct intermediate views between two cameras.
The warped frames have holes (disoccluded regions) that get filled
by Nano Banana Pro in the cleanup pass.
"""

import numpy as np
import cv2
import torch

# ── Depth Estimation ───────────────────────────────────────────────────

_depth_pipe = None


def _load_depth_model():
    """Load Depth Anything V2 small via transformers pipeline."""
    global _depth_pipe
    if _depth_pipe is not None:
        return

    from transformers import pipeline

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  Loading Depth Anything V2 (small) on {device}...")
    _depth_pipe = pipeline(
        task="depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=device,
    )
    print("  Depth model loaded.")


def estimate_depth(image: np.ndarray) -> np.ndarray:
    """Estimate relative depth map for an image.

    Args:
        image: (H, W, 3) uint8 RGB image.

    Returns:
        depth: (H, W) float32, normalized [0,1], higher = farther.
    """
    _load_depth_model()
    from PIL import Image as PILImage

    pil_img = PILImage.fromarray(image)
    result = _depth_pipe(pil_img)
    depth_pil = result["depth"]

    # Convert to numpy, resize to match input
    depth = np.array(depth_pil.resize((image.shape[1], image.shape[0])), dtype=np.float32)

    # Normalize to [0, 1]
    depth = depth - depth.min()
    if depth.max() > 0:
        depth = depth / depth.max()

    return depth


# ── Forward Warping ────────────────────────────────────────────────────


def forward_warp(
    image: np.ndarray,
    depth: np.ndarray,
    rotation_deg: float,
    focal_length_factor: float = 0.8,
) -> tuple[np.ndarray, np.ndarray]:
    """Warp an image to simulate a camera rotation using depth.

    Simulates moving the camera along a circular arc by `rotation_deg` degrees.
    Near objects shift more than far objects (parallax).

    Args:
        image: (H, W, 3) uint8.
        depth: (H, W) float32, normalized [0,1], higher=farther.
        rotation_deg: Degrees to rotate (positive = camera moves right,
                      so image content shifts left).
        focal_length_factor: Approximate focal length as fraction of image width.

    Returns:
        warped: (H, W, 3) uint8, warped image with black holes.
        valid_mask: (H, W) bool, True where pixels have valid data.
    """
    H, W = image.shape[:2]
    f = focal_length_factor * W  # Approximate focal length in pixels

    # Convert rotation to radians
    theta = np.radians(rotation_deg)

    # Compute per-pixel horizontal shift based on depth.
    # Key insight: closer objects (low depth) shift more, far objects shift less.
    # Shift = f * tan(theta) * (1 / (depth_scale + epsilon))
    # We use inverse depth for parallax: shift ∝ 1/depth
    # But depth is already normalized [0,1] where 0=close, 1=far.
    # So inverse_depth ∝ 1/(depth + 0.1) — close objects get large shift.

    inverse_depth = 1.0 / (depth + 0.2)  # Avoid division by zero
    inverse_depth = inverse_depth / inverse_depth.max()  # Normalize to [0, 1]

    # Maximum shift for closest objects
    max_shift = f * np.tan(theta)
    # Minimum shift for farthest objects (background still moves, just less)
    min_shift = max_shift * 0.3

    shift = min_shift + (max_shift - min_shift) * inverse_depth

    # Create output image
    warped = np.zeros_like(image)
    valid_mask = np.zeros((H, W), dtype=bool)

    # Z-buffer for handling occlusions
    z_buffer = np.full((H, W), -np.inf, dtype=np.float32)

    # Source pixel coordinates
    ys, xs = np.mgrid[0:H, 0:W]

    # Compute target x coordinates
    target_x = (xs - shift).astype(np.int32)

    # Flatten for vectorized processing
    target_x_flat = target_x.ravel()
    ys_flat = ys.ravel()
    xs_flat = xs.ravel()
    depth_flat = depth.ravel()

    # Filter valid targets
    valid = (target_x_flat >= 0) & (target_x_flat < W)
    target_x_valid = target_x_flat[valid]
    ys_valid = ys_flat[valid]
    xs_valid = xs_flat[valid]
    depth_valid = depth_flat[valid]

    # Apply with z-buffer (closer objects overwrite farther ones)
    # Process back-to-front: sort by depth descending so close objects write last
    sort_idx = np.argsort(-depth_valid)
    for idx in sort_idx:
        ty, tx = ys_valid[idx], target_x_valid[idx]
        warped[ty, tx] = image[ys_valid[idx], xs_valid[idx]]
        valid_mask[ty, tx] = True

    return warped, valid_mask


# ── Bidirectional Warp + Blend ─────────────────────────────────────────


def warp_between_views(
    img_left: np.ndarray,
    depth_left: np.ndarray,
    img_right: np.ndarray,
    depth_right: np.ndarray,
    t: float,
    gap_degrees: float = 35.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Create an intermediate view by warping both neighbors and blending.

    Args:
        img_left: Left camera image.
        depth_left: Left camera depth map.
        img_right: Right camera image.
        depth_right: Right camera depth map.
        t: Interpolation factor [0, 1]. 0=left camera, 1=right camera.
        gap_degrees: Angular gap between cameras.

    Returns:
        blended: (H, W, 3) uint8, blended warped image.
        hole_mask: (H, W) bool, True where NEITHER warp has data (needs inpainting).
    """
    # Warp left image forward (camera moves right)
    warp_l, mask_l = forward_warp(img_left, depth_left, rotation_deg=t * gap_degrees)

    # Warp right image backward (camera moves left)
    warp_r, mask_r = forward_warp(img_right, depth_right, rotation_deg=-(1 - t) * gap_degrees)

    H, W = img_left.shape[:2]
    blended = np.zeros((H, W, 3), dtype=np.float32)
    count = np.zeros((H, W, 1), dtype=np.float32)

    # Weight by proximity: left warp gets weight (1-t), right warp gets weight t
    if mask_l.any():
        blended[mask_l] += warp_l[mask_l].astype(np.float32) * (1 - t)
        count[mask_l] += (1 - t)

    if mask_r.any():
        blended[mask_r] += warp_r[mask_r].astype(np.float32) * t
        count[mask_r] += t

    # Normalize where we have data
    has_data = count.squeeze() > 0
    blended[has_data] /= count[has_data]

    # Where neither warp has data = holes
    hole_mask = ~has_data

    return blended.astype(np.uint8), hole_mask


# ── High-Level API ─────────────────────────────────────────────────────


def generate_warped_strip(
    img_left: np.ndarray,
    img_right: np.ndarray,
    num_synth: int = 3,
    gap_degrees: float = 35.0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate geometrically warped intermediate views for one gap.

    Args:
        img_left: Left real camera frame.
        img_right: Right real camera frame.
        num_synth: Number of synthetic views.
        gap_degrees: Angular gap between cameras.

    Returns:
        List of (warped_image, hole_mask) tuples, ordered left to right.
    """
    print("    Estimating depth (left)...")
    depth_left = estimate_depth(img_left)
    print("    Estimating depth (right)...")
    depth_right = estimate_depth(img_right)

    results = []
    for i in range(num_synth):
        t = (i + 1) / (num_synth + 1)
        deg = round(t * gap_degrees)
        print(f"    Warping view at ~{deg}° (t={t:.2f})...")
        warped, holes = warp_between_views(
            img_left, depth_left, img_right, depth_right,
            t=t, gap_degrees=gap_degrees,
        )
        hole_pct = holes.sum() / holes.size * 100
        print(f"      {hole_pct:.1f}% holes")
        results.append((warped, holes))

    return results
