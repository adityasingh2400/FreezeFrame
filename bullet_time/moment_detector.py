"""Moment detection: upload videos, analyze with Gemini, snap to best frames."""

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
from google import genai
from google.genai import types

from .schemas import Moment, MomentCatalog, MomentSelection


def _get_client():
    """Get or create a Gemini API client."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable")
    return genai.Client(api_key=api_key)


# ── Video Upload ───────────────────────────────────────────────────────


def upload_videos(video_paths: list[Path], client=None) -> list:
    """Upload videos via Gemini Files API. Returns file objects."""
    client = client or _get_client()
    files = []
    for path in video_paths:
        print(f"  Uploading {path.name}...")
        f = client.files.upload(file=str(path))
        files.append(f)
        print(f"  -> {f.name} ({f.state})")

    # Wait for processing to complete
    for f in files:
        while f.state.name == "PROCESSING":
            time.sleep(1)
            f = client.files.get(name=f.name)
        if f.state.name != "ACTIVE":
            raise RuntimeError(f"File {f.name} failed processing: {f.state}")

    print(f"  All {len(files)} videos uploaded and ready.")
    return files


# ── Moment Detection ──────────────────────────────────────────────────


def detect_moments(file_refs: list, client=None) -> MomentCatalog:
    """Analyze uploaded videos with Gemini to find key moments."""
    client = client or _get_client()

    prompt = (
        "You are analyzing synchronized multi-camera footage of a sports moment. "
        "There are 4 cameras arranged in a semicircle, approximately 35 degrees apart, "
        "all recording the same action simultaneously.\n\n"
        "Analyze the video(s) and identify 5-10 key moments that would be visually "
        "interesting as a frozen bullet-time shot. Focus on moments with:\n"
        "- Clear, dramatic action (peak of a jump, ball release, contact)\n"
        "- Minimal motion blur across cameras\n"
        "- Interesting body positioning\n\n"
        "For each moment, provide the timestamp in seconds, the nearest frame number "
        "at 30fps, a short label, a description, the action type, and your confidence.\n\n"
        "Use timestamps in MM:SS or SS.S format relative to the video start."
    )

    contents = [prompt] + file_refs

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MomentCatalog.model_json_schema(),
        ),
    )

    catalog = MomentCatalog.model_validate_json(response.text)
    return catalog


# ── Moment Query ──────────────────────────────────────────────────────


def select_moment(catalog: MomentCatalog, query: str, client=None) -> tuple[Moment, int]:
    """Use Gemini to match a natural language query to the best moment."""
    client = client or _get_client()

    moments_json = json.dumps(
        [m.model_dump() for m in catalog.moments], indent=2
    )

    prompt = (
        f"Given these detected moments in a sports video:\n{moments_json}\n\n"
        f'The user is asking: "{query}"\n\n'
        "Select the moment that best matches the user's query. Consider semantic "
        "similarity — for example, 'the flick' matches 'shot_release', "
        "'the dunk' matches a slam dunk moment, etc."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MomentSelection.model_json_schema(),
        ),
    )

    selection = MomentSelection.model_validate_json(response.text)
    idx = selection.selected_index
    if idx < 0 or idx >= len(catalog.moments):
        raise ValueError(f"No matching moment found for query: {query}")

    return catalog.moments[idx], idx


# ── Frame Snapping ────────────────────────────────────────────────────


def _laplacian_sharpness(img_path: Path) -> float:
    """Compute sharpness score via Laplacian variance."""
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return cv2.Laplacian(img, cv2.CV_64F).var()


def snap_to_sharpest_frames(
    images_dir: Path,
    target_frame: int,
    window: int = 1,
    cameras: list[str] | None = None,
) -> dict[str, tuple[Path, int]]:
    """For each camera, pick the sharpest frame in [target-window, target+window].

    Returns {cam_name: (path, actual_frame_number)}.
    """
    if cameras is None:
        cameras = sorted(
            d.name for d in images_dir.iterdir()
            if d.is_dir() and d.name.startswith("cam")
        )

    results = {}
    for cam in cameras:
        cam_dir = images_dir / cam
        best_score = -1.0
        best_path = None
        best_frame = target_frame

        for offset in range(-window, window + 1):
            fn = target_frame + offset
            if fn < 1:
                continue
            frame_path = cam_dir / f"frame_{fn:05d}.jpg"
            if not frame_path.exists():
                # Try .png fallback
                frame_path = cam_dir / f"frame_{fn:05d}.png"
            if not frame_path.exists():
                continue

            score = _laplacian_sharpness(frame_path)
            if score > best_score:
                best_score = score
                best_path = frame_path
                best_frame = fn

        if best_path is None:
            raise FileNotFoundError(f"No frames found for {cam} near frame {target_frame}")

        results[cam] = (best_path, best_frame)
        print(f"  {cam}: frame {best_frame} (sharpness={best_score:.1f})")

    return results


# ── Catalog Caching ───────────────────────────────────────────────────


def save_catalog(catalog: MomentCatalog, path: Path):
    """Save moment catalog to JSON file."""
    path.write_text(catalog.model_dump_json(indent=2))
    print(f"  Catalog saved to {path}")


def load_catalog(path: Path) -> MomentCatalog | None:
    """Load cached moment catalog if it exists."""
    if not path.exists():
        return None
    return MomentCatalog.model_validate_json(path.read_text())
