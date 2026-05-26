"""Mild exposure and white-balance normalization across cameras.

Prevents brightness pops at transitions between real and synthetic frames.
"""

import numpy as np
import cv2


def harmonize_exposure(frames: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Normalize exposure across all camera frames to their mean.

    Adjusts brightness and color balance mildly — not a restyle.

    Args:
        frames: {cam_name: (H,W,3) uint8 RGB}

    Returns:
        Harmonized frames, same keys.
    """
    if len(frames) < 2:
        return frames

    # Compute mean brightness per frame (in LAB space for perceptual accuracy)
    labs = {}
    means = []
    for name, img in frames.items():
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
        labs[name] = lab
        means.append(lab[:, :, 0].mean())

    target_mean = np.mean(means)

    result = {}
    for name, lab in labs.items():
        current_mean = lab[:, :, 0].mean()
        if current_mean > 0:
            # Scale L channel to match target mean
            scale = target_mean / current_mean
            # Clamp scale to avoid aggressive changes
            scale = np.clip(scale, 0.85, 1.15)
            lab[:, :, 0] = np.clip(lab[:, :, 0] * scale, 0, 255)

        result[name] = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    return result
