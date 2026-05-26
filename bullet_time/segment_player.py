"""Extract player foreground mask using depth thresholding.

The player is the closest large object in the scene. We use the depth
map to separate foreground (player) from background (court, walls, trees).
"""

import numpy as np
import cv2


def segment_player(depth: np.ndarray, min_area: int = 5000) -> np.ndarray:
    """Extract a binary player mask from a depth map.

    Args:
        depth: (H,W) float32, [0,1], 0=close, 1=far.
        min_area: Minimum connected component area to be considered the player.

    Returns:
        player_mask: (H,W) bool, True where player is.
    """
    # The player is close to camera (low depth values).
    # Use Otsu's threshold on the depth map to find the foreground cutoff.
    depth_u8 = (depth * 255).astype(np.uint8)
    _, fg_mask = cv2.threshold(depth_u8, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Clean up with morphological operations
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # Keep only the largest connected component(s) above min_area
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask)
    player_mask = np.zeros_like(fg_mask)
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            player_mask[labels == i] = 255

    # Slight dilation to include edges
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    player_mask = cv2.dilate(player_mask, dilate_kernel, iterations=1)

    return player_mask > 0


def build_silhouette_ring(player_mask: np.ndarray, ring_width: int = 12) -> np.ndarray:
    """Build a risk ring around the player silhouette boundary.

    Args:
        player_mask: (H,W) bool.
        ring_width: Pixels to dilate outward from the boundary.

    Returns:
        ring: (H,W) float32, [0,1], 1.0 at the boundary, fading outward.
    """
    mask_u8 = player_mask.astype(np.uint8) * 255

    # Dilate and erode to get the boundary ring
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ring_width, ring_width))
    dilated = cv2.dilate(mask_u8, kernel, iterations=1)
    eroded = cv2.erode(mask_u8, kernel, iterations=1)

    # Ring = dilated XOR eroded (the boundary zone)
    ring = ((dilated > 0) & ~(eroded > 0)).astype(np.float32)

    # Smooth the ring for a gradual falloff
    ring = cv2.GaussianBlur(ring, (ring_width * 2 + 1, ring_width * 2 + 1), 0)
    ring = np.clip(ring / (ring.max() + 1e-8), 0, 1)

    return ring
