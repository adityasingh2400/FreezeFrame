"""Visibility-aware forward warping with foreground/background separation.

Key principle: do NOT blend two human silhouettes. For foreground (player)
pixels, pick ONE winning source. For background, soft blending is OK.

For each target angle:
  1. Forward-warp left image → warped_left
  2. Forward-warp right image → warped_right
  3. Segment player in both warps
  4. For foreground: single-source ownership (nearest camera wins)
  5. For background: angular proximity blend
  6. Composite fg over bg
"""

import numpy as np
import cv2
from .segment_player import segment_player


def forward_warp(
    image: np.ndarray,
    depth: np.ndarray,
    rotation_deg: float,
    focal_factor: float = 0.8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Warp an image by simulating camera rotation using depth parallax.

    Returns:
        warped: (H,W,3) uint8.
        valid_mask: (H,W) bool.
        depth_out: (H,W) float32, depth at warped positions.
    """
    H, W = image.shape[:2]
    f = focal_factor * W
    theta = np.radians(rotation_deg)

    inv_depth = 1.0 / (depth + 0.15)
    inv_depth = inv_depth / inv_depth.max()

    max_shift = f * np.tan(theta)
    min_shift = max_shift * 0.25
    shift = min_shift + (max_shift - min_shift) * inv_depth

    ys, xs = np.mgrid[0:H, 0:W]
    target_x = np.round(xs - shift).astype(np.int32)

    warped = np.zeros((H, W, 3), dtype=np.uint8)
    valid_mask = np.zeros((H, W), dtype=bool)
    depth_out = np.full((H, W), np.inf, dtype=np.float32)

    tx = target_x.ravel()
    sy = ys.ravel()
    sx = xs.ravel()
    d = depth.ravel()

    valid_idx = (tx >= 0) & (tx < W)
    tx, sy, sx, d = tx[valid_idx], sy[valid_idx], sx[valid_idx], d[valid_idx]

    # Sort back-to-front: far pixels paint first, close overwrite (z-buffer)
    order = np.argsort(-d)
    tx, sy, sx, d = tx[order], sy[order], sx[order], d[order]

    warped[sy, tx] = image[sy, sx]
    valid_mask[sy, tx] = True
    depth_out[sy, tx] = d

    return warped, valid_mask, depth_out


def warp_pair_to_target(
    img_left: np.ndarray,
    depth_left: dict,
    img_right: np.ndarray,
    depth_right: dict,
    alpha: float,
    gap_degrees: float = 35.0,
) -> dict:
    """Warp both cameras to target angle with fg/bg separation.

    The critical difference from naive blending: foreground (player) pixels
    use single-source ownership, not averaging. This prevents ghost bodies.

    Args:
        img_left, img_right: (H,W,3) uint8 RGB.
        depth_left, depth_right: Depth dicts from estimate_depth.
        alpha: [0,1], interpolation factor. 0=left, 1=right.
        gap_degrees: Angular gap between cameras.

    Returns dict with all warp artifacts.
    """
    target_deg = alpha * gap_degrees
    H, W = img_left.shape[:2]

    # ── Forward warp both sources ──────────────────────────────────────
    warp_l, mask_l, zdepth_l = forward_warp(
        img_left, depth_left["depth"], rotation_deg=target_deg
    )
    warp_r, mask_r, zdepth_r = forward_warp(
        img_right, depth_right["depth"], rotation_deg=-(gap_degrees - target_deg)
    )

    # ── Segment player in both warped views ────────────────────────────
    # Use depth from the warped views to find foreground
    # Approximate: warp the source depth maps too
    fg_left = np.zeros((H, W), dtype=bool)
    fg_right = np.zeros((H, W), dtype=bool)

    if mask_l.any():
        # Segment player in left warp using warped depth
        depth_l_norm = zdepth_l.copy()
        depth_l_norm[~mask_l] = 1.0  # Far for invalid pixels
        fg_left = segment_player(depth_l_norm) & mask_l

    if mask_r.any():
        depth_r_norm = zdepth_r.copy()
        depth_r_norm[~mask_r] = 1.0
        fg_right = segment_player(depth_r_norm) & mask_r

    # ── Build fused draft with fg/bg separation ────────────────────────

    # Background draft: blend both sources with angular weights
    w_left = 1.0 - alpha
    w_right = alpha

    bg_draft = np.zeros((H, W, 3), dtype=np.float32)
    bg_weight = np.zeros((H, W, 1), dtype=np.float32)

    # Background = valid pixels that are NOT foreground
    bg_l = mask_l & ~fg_left
    bg_r = mask_r & ~fg_right

    if bg_l.any():
        bg_draft[bg_l] += warp_l[bg_l].astype(np.float32) * w_left
        bg_weight[bg_l] += w_left
    if bg_r.any():
        bg_draft[bg_r] += warp_r[bg_r].astype(np.float32) * w_right
        bg_weight[bg_r] += w_right

    has_bg = bg_weight.squeeze() > 0
    bg_draft[has_bg] /= bg_weight[has_bg]
    bg_draft = np.clip(bg_draft, 0, 255).astype(np.uint8)

    # Foreground draft: single-source ownership — nearest camera wins
    fg_draft = np.zeros((H, W, 3), dtype=np.uint8)
    fg_mask_combined = np.zeros((H, W), dtype=bool)

    if alpha <= 0.5:
        # Left camera is closer → left owns foreground, right fills gaps
        fg_draft[fg_left] = warp_l[fg_left]
        fg_mask_combined[fg_left] = True
        # Right fg fills only where left fg is missing
        right_only_fg = fg_right & ~fg_left
        fg_draft[right_only_fg] = warp_r[right_only_fg]
        fg_mask_combined[right_only_fg] = True
    else:
        # Right camera is closer → right owns foreground
        fg_draft[fg_right] = warp_r[fg_right]
        fg_mask_combined[fg_right] = True
        left_only_fg = fg_left & ~fg_right
        fg_draft[left_only_fg] = warp_l[left_only_fg]
        fg_mask_combined[left_only_fg] = True

    # ── Composite fg over bg ───────────────────────────────────────────
    fused_draft = bg_draft.copy()
    fused_draft[fg_mask_combined] = fg_draft[fg_mask_combined]

    # Also fill any remaining gaps: if a pixel has data from either source
    # but wasn't classified as fg or bg, use whatever we have
    leftover_l = mask_l & ~has_bg & ~fg_mask_combined
    leftover_r = mask_r & ~has_bg & ~fg_mask_combined
    fused_draft[leftover_l] = warp_l[leftover_l]
    fused_draft[leftover_r] = warp_r[leftover_r]

    # ── Hole mask and source support ───────────────────────────────────
    any_data = mask_l | mask_r
    hole_mask = ~any_data
    source_support = mask_l.astype(np.uint8) + mask_r.astype(np.uint8)

    # ── Ghost detection: pixels where BOTH sources put foreground ──────
    ghost_zone = fg_left & fg_right  # Both warps claim foreground here

    return {
        "fused_draft": fused_draft,
        "warped_left": warp_l,
        "warped_right": warp_r,
        "mask_left": mask_l,
        "mask_right": mask_r,
        "fg_left": fg_left,
        "fg_right": fg_right,
        "fg_mask": fg_mask_combined,
        "bg_mask": has_bg,
        "hole_mask": hole_mask,
        "ghost_zone": ghost_zone,
        "source_support": source_support,
        "alpha": alpha,
        "target_deg": target_deg,
    }


def warp_midpoint_biased(
    img_left: np.ndarray,
    depth_left: dict,
    img_right: np.ndarray,
    depth_right: dict,
    gap_degrees: float = 35.0,
) -> dict:
    """Special midpoint handling: two biased drafts merged.

    Instead of one muddy 50/50 composite, build:
      - left-biased draft (alpha=0.4, left camera dominates)
      - right-biased draft (alpha=0.6, right camera dominates)
    Then composite: left-biased fg for left half, right-biased fg for right half.
    """
    H, W = img_left.shape[:2]

    # Two biased warps
    left_biased = warp_pair_to_target(
        img_left, depth_left, img_right, depth_right,
        alpha=0.40, gap_degrees=gap_degrees,
    )
    right_biased = warp_pair_to_target(
        img_left, depth_left, img_right, depth_right,
        alpha=0.60, gap_degrees=gap_degrees,
    )

    # Merge: use left-biased for left half of frame, right-biased for right half
    # But smarter: use left-biased foreground where alpha < 0.5, right-biased otherwise
    mid_x = W // 2
    fused = left_biased["fused_draft"].copy()
    fused[:, mid_x:] = right_biased["fused_draft"][:, mid_x:]

    # Blend a narrow seam at the center (16px wide)
    seam = 16
    if mid_x > seam:
        for dx in range(seam):
            t = dx / seam
            col = mid_x - seam // 2 + dx
            if 0 <= col < W:
                fused[:, col] = (
                    (1 - t) * left_biased["fused_draft"][:, col].astype(np.float32) +
                    t * right_biased["fused_draft"][:, col].astype(np.float32)
                ).astype(np.uint8)

    # Combine masks
    hole_mask = left_biased["hole_mask"] & right_biased["hole_mask"]
    ghost_zone = left_biased["ghost_zone"] | right_biased["ghost_zone"]
    source_support = np.maximum(
        left_biased["source_support"], right_biased["source_support"]
    )

    return {
        "fused_draft": fused,
        "warped_left": left_biased["warped_left"],
        "warped_right": right_biased["warped_right"],
        "mask_left": left_biased["mask_left"] | right_biased["mask_left"],
        "mask_right": left_biased["mask_right"] | right_biased["mask_right"],
        "fg_left": left_biased["fg_left"],
        "fg_right": right_biased["fg_right"],
        "fg_mask": left_biased["fg_mask"] | right_biased["fg_mask"],
        "bg_mask": left_biased["bg_mask"] | right_biased["bg_mask"],
        "hole_mask": hole_mask,
        "ghost_zone": ghost_zone,
        "source_support": source_support,
        "alpha": 0.5,
        "target_deg": 0.5 * gap_degrees,
        "_is_midpoint": True,
    }
