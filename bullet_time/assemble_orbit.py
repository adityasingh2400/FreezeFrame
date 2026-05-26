"""Assemble a full orbit strip for one frozen moment.

Orchestrates: depth → warp → confidence → mask → repair → composite → output.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .estimate_depth import estimate_depth
from .warp_pair_to_target import warp_pair_to_target, warp_midpoint_biased
from .build_confidence_and_mask import build_confidence_and_mask
from .repair_with_nano import repair_frame
from .color_harmonize import harmonize_exposure


def assemble_orbit(
    real_frames: dict[str, np.ndarray],
    output_dir: Path,
    views_per_gap: int = 4,
    gap_degrees: float = 35.0,
    use_pro: bool = False,
    debug: bool = False,
) -> list[str]:
    """Build the full orbit strip: real + synthetic frames.

    Args:
        real_frames: {cam_name: (H,W,3) uint8 RGB}, ordered by position.
        output_dir: Where to write output images.
        views_per_gap: Synthetic views between each camera pair (4-6 recommended).
        gap_degrees: Angular gap between cameras.
        use_pro: Use Nano Banana Pro (slow, highest quality) vs Flash (fast).
        debug: Save intermediate artifacts (warps, masks, confidence maps).

    Returns:
        List of output filenames in strip order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "debug" if debug else None
    if debug_dir:
        debug_dir.mkdir(exist_ok=True)

    cam_names = sorted(real_frames.keys())
    num_gaps = len(cam_names) - 1
    t_start = time.time()

    # ── Step 1: Color harmonization ────────────────────────────────────
    print("\n  [1/5] Color harmonization...")
    real_frames = harmonize_exposure(real_frames)

    # ── Step 2: Depth estimation (all cameras in parallel) ─────────────
    print("  [2/5] Depth estimation...")
    t0 = time.time()
    depths = {}
    for cam in cam_names:
        print(f"    {cam}...")
        depths[cam] = estimate_depth(real_frames[cam])
    print(f"    Done in {time.time()-t0:.1f}s")

    # ── Step 3: Warp + confidence + mask for ALL target angles ─────────
    print(f"  [3/5] Warping {num_gaps} gaps × {views_per_gap} views...")
    t0 = time.time()

    # Structure: targets[gap_idx] = list of (alpha, warp_result, conf_result)
    targets = {}

    for gi in range(num_gaps):
        cam_l = cam_names[gi]
        cam_r = cam_names[gi + 1]
        targets[gi] = []

        for vi in range(views_per_gap):
            alpha = (vi + 1) / (views_per_gap + 1)
            deg = round(alpha * gap_degrees)

            # Detect if this is the midpoint frame
            is_midpoint = (views_per_gap >= 3 and vi == views_per_gap // 2)

            if is_midpoint and abs(alpha - 0.5) < 0.15:
                # Special midpoint: two biased drafts merged
                warp_result = warp_midpoint_biased(
                    real_frames[cam_l], depths[cam_l],
                    real_frames[cam_r], depths[cam_r],
                    gap_degrees=gap_degrees,
                )
            else:
                warp_result = warp_pair_to_target(
                    real_frames[cam_l], depths[cam_l],
                    real_frames[cam_r], depths[cam_r],
                    alpha=alpha, gap_degrees=gap_degrees,
                )

            conf_result = build_confidence_and_mask(
                warp_result, depths[cam_l], depths[cam_r],
                is_midpoint=is_midpoint,
            )

            targets[gi].append({
                "alpha": alpha,
                "deg": deg,
                "draft": warp_result["fused_draft"],
                "hole_mask": warp_result["hole_mask"],
                "edit_mask": conf_result["edit_mask"],
                "mask_pct": conf_result["mask_area_pct"],
                "confidence": conf_result["confidence"],
                "is_midpoint": is_midpoint,
            })

            pct = conf_result["mask_area_pct"]
            holes = warp_result["hole_mask"].sum() / warp_result["hole_mask"].size * 100
            mid_tag = " [MIDPOINT]" if is_midpoint else ""
            ghost_pct = warp_result["ghost_zone"].sum() / warp_result["ghost_zone"].size * 100
            print(f"    Gap {gi+1}, view {vi+1}/{views_per_gap}: "
                  f"~{deg}° | holes={holes:.1f}% | ghost={ghost_pct:.1f}% | "
                  f"edit_mask={pct:.1f}%{mid_tag}")

            if debug_dir:
                tag = f"g{gi+1}_v{vi+1}"
                Image.fromarray(warp_result["fused_draft"]).save(debug_dir / f"{tag}_draft.jpg", quality=95)
                cv2.imwrite(str(debug_dir / f"{tag}_holes.png"), warp_result["hole_mask"].astype(np.uint8) * 255)
                cv2.imwrite(str(debug_dir / f"{tag}_edit_mask.png"), conf_result["edit_mask"].astype(np.uint8) * 255)
                cv2.imwrite(str(debug_dir / f"{tag}_confidence.png"), (conf_result["confidence"] * 255).astype(np.uint8))

    print(f"    Warping done in {time.time()-t0:.1f}s")

    # ── Step 4: Repair all frames (concurrent API calls) ───────────────
    print(f"  [4/5] Repairing with Nano Banana ({'Pro' if use_pro else 'Flash'})...")
    t0 = time.time()

    repaired = {}  # (gi, vi) → repaired image

    def _repair_one(gi, vi):
        t = targets[gi][vi]
        cam_l = cam_names[gi]
        cam_r = cam_names[gi + 1]

        # Gather other real cameras as support refs
        others = [
            real_frames[c] for c in cam_names
            if c != cam_l and c != cam_r
        ]

        result, strategy = repair_frame(
            draft=t["draft"],
            edit_mask=t["edit_mask"],
            mask_area_pct=t["mask_pct"],
            real_left=real_frames[cam_l],
            real_right=real_frames[cam_r],
            real_others=others,
            use_pro=use_pro,
        )
        print(f"    Gap {gi+1}, view {vi+1}: {strategy} (mask={t['mask_pct']:.1f}%)")
        return (gi, vi), result

    # Fire all repairs concurrently
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = []
        for gi in range(num_gaps):
            for vi in range(views_per_gap):
                futures.append(pool.submit(_repair_one, gi, vi))

        for f in as_completed(futures):
            key, result = f.result()
            repaired[key] = result

    print(f"    Repair done in {time.time()-t0:.1f}s")

    # ── Step 5: Assemble strip and write ─────────────────────────────
    print("  [5/5] Writing strip...")
    filenames = []

    for i, cam in enumerate(cam_names):
        fname = f"{cam}.jpg"
        Image.fromarray(real_frames[cam]).save(str(output_dir / fname), quality=92)
        filenames.append(fname)

        if i < num_gaps:
            next_cam = cam_names[i + 1]
            for vi in range(views_per_gap):
                fname = f"synth_{cam}_{next_cam}_{chr(97+vi)}.jpg"
                img = repaired[(i, vi)]
                # Clamp extreme black/white to nearest color
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                extremes = (gray < 12) | (gray > 243)
                if extremes.any():
                    blurred = cv2.GaussianBlur(img, (21, 21), 0)
                    img[extremes] = blurred[extremes]
                Image.fromarray(img).save(str(output_dir / fname), quality=92)
                filenames.append(fname)

    elapsed = time.time() - t_start
    total = len(filenames)
    real_count = len(cam_names)
    synth_count = total - real_count
    print(f"\n  Strip complete: {total} frames ({real_count} real + {synth_count} synthetic) in {elapsed:.1f}s")

    return filenames


def write_manifest(
    filenames: list[str],
    output_dir: Path,
    manifest_path: Path,
    moment_label: str = "Bullet Time",
    moment_desc: str = "",
    base_dir: str = "/bullet-time/",
):
    """Write viewer manifest."""
    manifest = {
        "name": "Replay — Bullet Time",
        "mode": "image-strip",
        "frames": filenames,
        "baseDir": base_dir,
        "total_frames": len(filenames),
        "moment": {
            "label": moment_label,
            "description": moment_desc,
        },
        "pipeline": "bullet-time-v2",
        "generated_at": datetime.now().isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  Manifest written to {manifest_path}")
