"""Synthetic view generation via Nano Banana Pro (gemini-3.1-flash-image-preview).

Fills angular gaps between real cameras using recursive edge-inward generation.
Each synthetic frame uses up to 14 reference images for maximum context.
"""

import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image
from google import genai
from google.genai import types


# ── Config ─────────────────────────────────────────────────────────────

NANO_BANANA_PRO = "gemini-3-pro-image-preview"
MAX_WORKERS = 6  # Concurrent API calls


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY")
    return genai.Client(api_key=api_key)


def _img_to_bytes(img: np.ndarray | Image.Image, quality: int = 92) -> bytes:
    """Convert image to JPEG bytes."""
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _bytes_to_img(data: bytes) -> np.ndarray:
    """Convert bytes to numpy (H,W,3) uint8."""
    return np.array(Image.open(io.BytesIO(data)).convert("RGB"))


def _extract_image_from_response(response) -> np.ndarray | None:
    """Extract generated image from Gemini response."""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data is not None:
            return _bytes_to_img(part.inline_data.data)
    return None


# ── Single View Generation ─────────────────────────────────────────────


def generate_single_view(
    reference_images: list[np.ndarray],
    cam_labels: list[str],
    target_description: str,
    client=None,
) -> np.ndarray:
    """Generate one synthetic view using Nano Banana Pro with reference images.

    Args:
        reference_images: List of reference images (up to 14). First images are
                         the 4 real camera frames, additional are synthetic.
        cam_labels: Human-readable labels for each reference image.
        target_description: Description of the target viewpoint.
        client: Gemini client (created if None).

    Returns:
        Generated image as (H,W,3) uint8.
    """
    client = client or _get_client()

    ref_description = "\n".join(
        f"- Image {i+1}: {label}" for i, label in enumerate(cam_labels)
    )

    prompt = (
        "I have 4 real cameras arranged in a semicircle, evenly spaced ~35 degrees "
        "apart, all pointed at the same person at the same frozen moment in time. "
        "Camera 1 is the leftmost, Camera 4 is the rightmost.\n\n"
        "As you go from Camera 1 to Camera 4 (left to right), the visual effect is:\n"
        "- The person ROTATES clockwise (you see more of their right side)\n"
        "- The background shifts to the LEFT\n"
        "- The person stays in the CENTER of the frame, same size\n"
        "- The person's POSE does NOT change — same arms, same legs, same expression\n"
        "- Only the VIEWING ANGLE changes, nothing else\n\n"
        f"Reference images provided:\n{ref_description}\n\n"
        f"TARGET: {target_description}\n\n"
        "CRITICAL RULES:\n"
        "- The person's body must appear ROTATED compared to the neighboring cameras — "
        "this is the MOST important thing. If Camera 1 shows the front of the person "
        "and Camera 2 shows slightly more of their right side, a view between them "
        "must show an intermediate rotation.\n"
        "- Do NOT just copy one of the reference images. The whole point is that the "
        "viewing angle is DIFFERENT from any reference camera.\n"
        "- Keep the person's pose IDENTICAL — same arm position, same leg position. "
        "Only the camera angle around them changes.\n"
        "- Background elements shift LEFT as the camera moves RIGHT.\n"
        "- Match lighting, colors, exposure, and zoom level of the reference cameras.\n"
        "- Output a single image at the same resolution as the references."
    )

    contents = [prompt]
    for img in reference_images[:14]:  # Hard limit at 14
        contents.append(
            types.Part.from_bytes(data=_img_to_bytes(img), mime_type="image/jpeg")
        )

    response = client.models.generate_content(
        model=NANO_BANANA_PRO,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )

    result = _extract_image_from_response(response)
    if result is None:
        raise RuntimeError("Nano Banana Pro returned no image")

    # Resize to match reference if needed
    ref_h, ref_w = reference_images[0].shape[:2]
    if result.shape[:2] != (ref_h, ref_w):
        result = np.array(
            Image.fromarray(result).resize((ref_w, ref_h), Image.LANCZOS)
        )

    return result


# ── Recursive Edge-Inward Gap Filling ──────────────────────────────────


def fill_gap(
    real_left: np.ndarray,
    real_right: np.ndarray,
    all_real_frames: list[np.ndarray],
    all_real_labels: list[str],
    gap_label: str,
    num_synth: int = 3,
    client=None,
) -> list[np.ndarray]:
    """Fill one gap between two adjacent cameras with synthetic views.

    Uses recursive edge-inward strategy:
      Round 1: Generate edge synthetics (closest to real frames)
      Round 2: Generate center synthetic (between the edge synthetics)

    Args:
        real_left: Left camera image.
        real_right: Right camera image.
        all_real_frames: All 4 real camera frames (for reference context).
        all_real_labels: Labels for all 4 real cameras.
        gap_label: e.g. "Camera 1 to Camera 2"
        num_synth: Number of synthetic views in this gap (default 3).
        client: Gemini client.

    Returns:
        List of synthetic images ordered left to right.
    """
    client = client or _get_client()

    # Each gap is ~35 degrees. Compute per-step rotation.
    deg_per_step = 35.0 / (num_synth + 1)

    def _rotation_desc(step_num):
        """Describe the visual rotation for step N within this gap."""
        deg = round(deg_per_step * step_num)
        return (
            f"Generate the view from a camera that has moved ~{deg} degrees to the "
            f"RIGHT of the left camera ({gap_label}). Compared to the left camera image, "
            f"the person should appear rotated ~{deg} degrees CLOCKWISE (you see slightly "
            f"more of their right side). The background shifts ~{deg} degrees to the LEFT. "
            f"The person's pose is FROZEN — identical arms, legs, expression. Only the "
            f"viewing angle changes. This view should look like a real photo taken from "
            f"a camera placed between these two positions."
        )

    if num_synth == 1:
        synth = generate_single_view(
            reference_images=all_real_frames,
            cam_labels=all_real_labels,
            target_description=_rotation_desc(1),
            client=client,
        )
        return [synth]

    if num_synth == 2:
        results = [None, None]

        def _gen(idx, step):
            results[idx] = generate_single_view(
                reference_images=all_real_frames,
                cam_labels=all_real_labels,
                target_description=_rotation_desc(step),
                client=client,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_gen, i, s) for i, s in enumerate([1, 2])]
            for f in as_completed(futures):
                f.result()

        return results

    # ── num_synth >= 3: Recursive edge-inward ──────────────────────────

    synth_left = None
    synth_right = None

    def _gen_left():
        nonlocal synth_left
        synth_left = generate_single_view(
            reference_images=all_real_frames,
            cam_labels=all_real_labels,
            target_description=_rotation_desc(1),
            client=client,
        )

    def _gen_right():
        nonlocal synth_right
        synth_right = generate_single_view(
            reference_images=all_real_frames,
            cam_labels=all_real_labels,
            target_description=_rotation_desc(num_synth),
            client=client,
        )

    print(f"    Round 1: Generating edge frames for {gap_label}...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_gen_left), pool.submit(_gen_right)]
        for f in as_completed(futures):
            f.result()

    if num_synth == 3:
        print(f"    Round 2: Generating center frame for {gap_label}...")
        refs = all_real_frames + [synth_left, synth_right]
        labels = all_real_labels + [
            f"Synthetic ~{round(deg_per_step)}° right of left camera ({gap_label})",
            f"Synthetic ~{round(deg_per_step * num_synth)}° right of left camera ({gap_label})",
        ]
        synth_center = generate_single_view(
            reference_images=refs,
            cam_labels=labels,
            target_description=_rotation_desc(2),
            client=client,
        )
        return [synth_left, synth_center, synth_right]

    # For num_synth > 3: generate edges, then fill middle steps sequentially
    middle_count = num_synth - 2
    refs = all_real_frames + [synth_left, synth_right]
    labels = all_real_labels + [
        f"Synthetic ~{round(deg_per_step)}° right of left camera ({gap_label})",
        f"Synthetic ~{round(deg_per_step * num_synth)}° right of left camera ({gap_label})",
    ]

    middle_frames = []
    for i in range(middle_count):
        step = i + 2  # Steps 2, 3, ... (step 1 = synth_left, step num_synth = synth_right)
        frame = generate_single_view(
            reference_images=refs[:11],
            cam_labels=labels[:11],
            target_description=_rotation_desc(step),
            client=client,
        )
        middle_frames.append(frame)
        refs.append(frame)
        labels.append(f"Synthetic ~{round(deg_per_step * step)}° right ({gap_label})")

    return [synth_left] + middle_frames + [synth_right]


# ── Fill All Gaps ──────────────────────────────────────────────────────


def fill_all_gaps(
    real_frames: dict[str, np.ndarray],
    views_per_gap: int = 3,
    client=None,
) -> list[tuple[str, np.ndarray]]:
    """Fill all gaps between cameras with fully concurrent generation.

    Round 1: ALL edge frames across ALL gaps fire concurrently (6 calls).
    Round 2: ALL center frames across ALL gaps fire concurrently (3 calls).
    Total: 2 sequential rounds instead of 6.
    """
    client = client or _get_client()
    import time

    cam_names = sorted(real_frames.keys())
    all_real = [real_frames[c] for c in cam_names]
    all_labels = [f"Camera {i+1} ({c})" for i, c in enumerate(cam_names)]
    num_gaps = len(cam_names) - 1
    deg_per_step = 35.0 / (views_per_gap + 1)

    def _rotation_desc(gap_label, step_num):
        deg = round(deg_per_step * step_num)
        return (
            f"Generate the view from a camera that has moved ~{deg} degrees to the "
            f"RIGHT of the left camera ({gap_label}). Compared to the left camera image, "
            f"the person should appear rotated ~{deg} degrees CLOCKWISE (you see slightly "
            f"more of their right side). The background shifts ~{deg} degrees to the LEFT. "
            f"The person's pose is FROZEN — identical arms, legs, expression. Only the "
            f"viewing angle changes."
        )

    # Build gap info
    gaps = []
    for i in range(num_gaps):
        cam_l, cam_r = cam_names[i], cam_names[i + 1]
        gaps.append({
            "left": cam_l,
            "right": cam_r,
            "label": f"Camera {i+1} ({cam_l}) and Camera {i+2} ({cam_r})",
        })

    # Storage for results: gap_synths[gap_idx] = [left, center, right] (for 3)
    gap_synths = {i: [None] * views_per_gap for i in range(num_gaps)}

    t0 = time.time()

    if views_per_gap >= 3:
        # ── Round 1: ALL edges concurrently ────────────────────────────
        print(f"\n  Round 1: Generating {num_gaps * 2} edge frames concurrently...")

        def _gen_edge(gap_idx, position):
            """Generate one edge frame. position='left' or 'right'."""
            gap = gaps[gap_idx]
            step = 1 if position == "left" else views_per_gap
            slot = 0 if position == "left" else views_per_gap - 1
            result = generate_single_view(
                reference_images=all_real,
                cam_labels=all_labels,
                target_description=_rotation_desc(gap["label"], step),
                client=client,
            )
            gap_synths[gap_idx][slot] = result
            print(f"    [{gap['label']}] {position} edge done")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = []
            for gi in range(num_gaps):
                futures.append(pool.submit(_gen_edge, gi, "left"))
                futures.append(pool.submit(_gen_edge, gi, "right"))
            for f in as_completed(futures):
                f.result()

        print(f"  Round 1 done in {time.time() - t0:.1f}s")

        # ── Round 2: ALL centers concurrently ──────────────────────────
        t1 = time.time()
        print(f"\n  Round 2: Generating {num_gaps} center frames concurrently...")

        if views_per_gap == 3:
            def _gen_center(gap_idx):
                gap = gaps[gap_idx]
                refs = all_real + [gap_synths[gap_idx][0], gap_synths[gap_idx][2]]
                labels = all_labels + [
                    f"Synthetic ~{round(deg_per_step)}° right ({gap['label']})",
                    f"Synthetic ~{round(deg_per_step * views_per_gap)}° right ({gap['label']})",
                ]
                result = generate_single_view(
                    reference_images=refs,
                    cam_labels=labels,
                    target_description=_rotation_desc(gap["label"], 2),
                    client=client,
                )
                gap_synths[gap_idx][1] = result
                print(f"    [{gap['label']}] center done")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(_gen_center, gi) for gi in range(num_gaps)]
                for f in as_completed(futures):
                    f.result()
        else:
            # For views_per_gap > 3, fill middle slots sequentially per gap but gaps in parallel
            def _gen_middle(gap_idx):
                gap = gaps[gap_idx]
                refs = list(all_real) + [gap_synths[gap_idx][0], gap_synths[gap_idx][-1]]
                labels = list(all_labels) + [
                    f"Synthetic left edge ({gap['label']})",
                    f"Synthetic right edge ({gap['label']})",
                ]
                for slot in range(1, views_per_gap - 1):
                    step = slot + 1
                    result = generate_single_view(
                        reference_images=refs[:11],
                        cam_labels=labels[:11],
                        target_description=_rotation_desc(gap["label"], step),
                        client=client,
                    )
                    gap_synths[gap_idx][slot] = result
                    refs.append(result)
                    labels.append(f"Synthetic ~{round(deg_per_step * step)}° ({gap['label']})")
                print(f"    [{gap['label']}] middle frames done")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(_gen_middle, gi) for gi in range(num_gaps)]
                for f in as_completed(futures):
                    f.result()

        print(f"  Round 2 done in {time.time() - t1:.1f}s")

    else:
        # views_per_gap <= 2: all frames in one concurrent round
        print(f"\n  Generating {num_gaps * views_per_gap} frames concurrently...")

        def _gen_simple(gap_idx, slot, step):
            gap = gaps[gap_idx]
            result = generate_single_view(
                reference_images=all_real,
                cam_labels=all_labels,
                target_description=_rotation_desc(gap["label"], step),
                client=client,
            )
            gap_synths[gap_idx][slot] = result
            print(f"    [{gap['label']}] view {slot+1} done")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = []
            for gi in range(num_gaps):
                for slot in range(views_per_gap):
                    futures.append(pool.submit(_gen_simple, gi, slot, slot + 1))
            for f in as_completed(futures):
                f.result()

    elapsed = time.time() - t0
    total_synth = sum(len(v) for v in gap_synths.values())
    print(f"\n  All {total_synth} synthetic frames done in {elapsed:.1f}s")

    # ── Assemble strip ─────────────────────────────────────────────────
    strip = []
    for i, cam in enumerate(cam_names):
        strip.append((cam, real_frames[cam]))
        if i < num_gaps:
            next_cam = cam_names[i + 1]
            for j, sf in enumerate(gap_synths[i]):
                strip.append((f"synth_{cam}_{next_cam}_{chr(97+j)}", sf))

    return strip


# ── Write Strip to Disk ────────────────────────────────────────────────


def write_strip(
    strip: list[tuple[str, np.ndarray]],
    output_dir: Path,
) -> list[str]:
    """Write image strip to disk.

    Returns list of filenames in order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = []

    for label, img in strip:
        fname = f"{label}.jpg"
        path = output_dir / fname
        Image.fromarray(img).save(str(path), quality=95)
        filenames.append(fname)
        print(f"    Saved {fname} ({img.shape[1]}x{img.shape[0]})")

    return filenames
