"""Build per-pixel confidence map and edit mask for a geometric draft.

Now includes:
  - ghost zone detection (both warps claim foreground)
  - player silhouette ring
  - disagreement detection
  - expanded mask around risky zones

The mask tells Nano Banana exactly what it may touch. Everything else is frozen.
"""

import numpy as np
import cv2
from .segment_player import build_silhouette_ring


# ── Tunable weights ───────────────────────────────────────────────────

WEIGHT_COVERAGE = 0.25
WEIGHT_MULTI_VIEW = 0.15
WEIGHT_DEPTH_CONF = 0.15
WEIGHT_AGREEMENT = 0.20
WEIGHT_SILHOUETTE = 0.15
WEIGHT_GHOST = 0.10

CONFIDENCE_THRESHOLD = 0.50
SILHOUETTE_RING_THRESHOLD = 0.40
AGREEMENT_THRESHOLD = 0.30

MIDPOINT_CONFIDENCE_THRESHOLD = 0.60  # More aggressive for midpoints


def build_confidence_and_mask(
    warp_result: dict,
    depth_left: dict,
    depth_right: dict,
    is_midpoint: bool = False,
) -> dict:
    """Build confidence map and edit mask.

    Args:
        warp_result: From warp_pair_to_target().
        depth_left, depth_right: Depth dicts.
        is_midpoint: If True, use more aggressive masking.

    Returns dict with confidence, edit_mask, mask_area_pct, components.
    """
    hole_mask = warp_result["hole_mask"]
    mask_l = warp_result["mask_left"]
    mask_r = warp_result["mask_right"]
    warp_l = warp_result["warped_left"]
    warp_r = warp_result["warped_right"]
    source_support = warp_result["source_support"]
    ghost_zone = warp_result["ghost_zone"]
    fg_mask = warp_result["fg_mask"]
    H, W = hole_mask.shape
    alpha = warp_result["alpha"]

    conf_threshold = MIDPOINT_CONFIDENCE_THRESHOLD if is_midpoint else CONFIDENCE_THRESHOLD

    # ── A. Coverage ────────────────────────────────────────────────────
    coverage = (~hole_mask).astype(np.float32)

    # ── B. Multi-view support ──────────────────────────────────────────
    multi_view = source_support.astype(np.float32) / 2.0

    # ── C. Depth confidence (avg of both cameras) ──────────────────────
    depth_conf = (
        (1 - alpha) * depth_left["confidence"] +
        alpha * depth_right["confidence"]
    )
    if depth_conf.shape != (H, W):
        depth_conf = cv2.resize(depth_conf, (W, H))

    # ── D. Agreement: color consistency where both sources hit ─────────
    both_hit = (source_support == 2)
    agreement = np.zeros((H, W), dtype=np.float32)

    if both_hit.any():
        diff = np.abs(
            warp_l[both_hit].astype(np.float32) -
            warp_r[both_hit].astype(np.float32)
        ).mean(axis=1) / 255.0
        agreement[both_hit] = diff

    agreement[source_support == 1] = 0.25
    agreement[hole_mask] = 1.0

    # ── E. Silhouette risk: ring around player boundary ────────────────
    silhouette_risk = np.zeros((H, W), dtype=np.float32)
    if fg_mask.any():
        silhouette_risk = build_silhouette_ring(fg_mask, ring_width=15)

    # Also add depth edge risk
    edge_map = (
        (1 - alpha) * depth_left["edges"] +
        alpha * depth_right["edges"]
    )
    if edge_map.shape != (H, W):
        edge_map = cv2.resize(edge_map, (W, H))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    edge_dilated = cv2.dilate(edge_map, kernel, iterations=1)
    silhouette_risk = np.maximum(silhouette_risk, edge_dilated * 0.8)

    # ── F. Ghost zone: both warps claim foreground ─────────────────────
    ghost_score = ghost_zone.astype(np.float32)
    # Dilate ghost zone — the boundary around it is also risky
    if ghost_zone.any():
        ghost_dilated = cv2.dilate(
            ghost_zone.astype(np.uint8) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
            iterations=1,
        ) > 0
        ghost_score[ghost_dilated] = np.maximum(ghost_score[ghost_dilated], 0.7)

    # ── Composite confidence ───────────────────────────────────────────
    confidence = (
        WEIGHT_COVERAGE * coverage +
        WEIGHT_MULTI_VIEW * multi_view +
        WEIGHT_DEPTH_CONF * depth_conf +
        WEIGHT_AGREEMENT * (1.0 - agreement) +
        WEIGHT_SILHOUETTE * (1.0 - silhouette_risk) +
        WEIGHT_GHOST * (1.0 - ghost_score)
    )
    confidence = np.clip(confidence, 0, 1).astype(np.float32)

    # ── Edit mask ──────────────────────────────────────────────────────
    edit_mask = (
        hole_mask |
        (confidence < conf_threshold) |
        (silhouette_risk > SILHOUETTE_RING_THRESHOLD) |
        (agreement > AGREEMENT_THRESHOLD) |
        ghost_zone  # Always repair where both warps claim foreground
    )

    # ── Morphological cleanup ──────────────────────────────────────────
    edit_u8 = edit_mask.astype(np.uint8) * 255

    # Close to merge nearby holes
    kern_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    edit_u8 = cv2.morphologyEx(edit_u8, cv2.MORPH_CLOSE, kern_close)

    # Remove tiny isolated specks (< 30 pixels)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(edit_u8)
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] < 30:
            edit_u8[labels == i] = 0

    # Dilate around the player silhouette boundary
    kern_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    edit_u8 = cv2.dilate(edit_u8, kern_dilate, iterations=1)

    edit_mask = edit_u8 > 0
    mask_area_pct = edit_mask.sum() / edit_mask.size * 100

    return {
        "confidence": confidence,
        "edit_mask": edit_mask,
        "mask_area_pct": mask_area_pct,
        "components": {
            "coverage": coverage,
            "multi_view": multi_view,
            "depth_confidence": depth_conf,
            "agreement": agreement,
            "silhouette_risk": silhouette_risk,
            "ghost_score": ghost_score,
        },
    }
