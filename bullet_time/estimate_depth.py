"""Monocular depth estimation via Depth Anything V2.

Outputs per camera:
  - relative depth map (float32, 0=close, 1=far)
  - depth confidence proxy (from local smoothness)
  - depth edge map (large depth gradients)
"""

import numpy as np
import cv2
import torch

_depth_pipe = None


def _load_model():
    global _depth_pipe
    if _depth_pipe is not None:
        return
    from transformers import pipeline
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  [depth] Loading Depth Anything V2 (small) on {device}...")
    _depth_pipe = pipeline(
        task="depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=device,
    )
    print("  [depth] Ready.")


def estimate_depth(image: np.ndarray) -> dict:
    """Estimate depth for a single RGB image.

    Returns dict with:
      depth: (H,W) float32, normalized [0,1], 0=close, 1=far
      confidence: (H,W) float32, [0,1], proxy from local smoothness
      edges: (H,W) float32, [0,1], magnitude of depth gradients
    """
    _load_model()
    from PIL import Image as PILImage

    H, W = image.shape[:2]
    pil_img = PILImage.fromarray(image)
    result = _depth_pipe(pil_img)
    depth_pil = result["depth"]

    depth = np.array(depth_pil.resize((W, H)), dtype=np.float32)
    depth = depth - depth.min()
    if depth.max() > 0:
        depth = depth / depth.max()

    # Depth confidence proxy: inverse of local depth variance
    # Smooth areas = high confidence, noisy/edge areas = low confidence
    blur = cv2.GaussianBlur(depth, (7, 7), 0)
    local_var = cv2.GaussianBlur((depth - blur) ** 2, (7, 7), 0)
    confidence = 1.0 - np.clip(local_var / (local_var.max() + 1e-8), 0, 1)
    confidence = confidence.astype(np.float32)

    # Depth edge map: Sobel on depth
    dx = cv2.Sobel(depth, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(depth, cv2.CV_32F, 0, 1, ksize=3)
    edges = np.sqrt(dx ** 2 + dy ** 2)
    edges = np.clip(edges / (edges.max() + 1e-8), 0, 1).astype(np.float32)

    return {"depth": depth, "confidence": confidence, "edges": edges}
