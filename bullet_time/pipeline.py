"""Bullet-time pipeline orchestrator.

Usage:
    # Step 1: Detect moments (uploads videos, analyzes, caches catalog)
    python -m bullet_time.pipeline --detect

    # Step 2: Generate bullet-time strip for a specific moment
    python -m bullet_time.pipeline --query "show me the release"

    # Or both in one shot:
    python -m bullet_time.pipeline --query "show me the release"
    (auto-detects if catalog is missing and runs detection first)
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .moment_detector import (
    detect_moments,
    load_catalog,
    save_catalog,
    select_moment,
    snap_to_sharpest_frames,
    upload_videos,
)
from .gap_filler import fill_all_gaps, write_strip


# ── Defaults ───────────────────────────────────────────────────────────

RAW_VIDEOS_DIR = Path("raw_videos")
SCENE_IMAGES_DIR = Path("scene/images")
OUTPUT_DIR = Path("viewer/public/bullet-time")
CATALOG_CACHE = Path("bullet_time/bullet_time_catalog.json")
VIEWS_PER_GAP = 3


# ── Pipeline Steps ─────────────────────────────────────────────────────


def step_detect(raw_dir: Path, catalog_path: Path) -> dict:
    """Upload videos and detect moments. Returns catalog dict."""
    print("\n=== Step 1: Upload Videos ===")
    video_paths = sorted(raw_dir.glob("*"))
    video_paths = [p for p in video_paths if p.suffix.lower() in {".mov", ".mp4", ".avi", ".mkv"}]
    if not video_paths:
        print(f"  ERROR: No video files found in {raw_dir}/")
        sys.exit(1)

    print(f"  Found {len(video_paths)} videos: {[p.name for p in video_paths]}")
    file_refs = upload_videos(video_paths)

    print("\n=== Step 2: Detect Moments ===")
    catalog = detect_moments(file_refs)
    save_catalog(catalog, catalog_path)

    print(f"\n  Scene: {catalog.scene_description}")
    print(f"  Found {len(catalog.moments)} moments:")
    for i, m in enumerate(catalog.moments):
        print(f"    [{i}] {m.label} @ {m.timestamp_sec:.1f}s (frame {m.frame_number}) "
              f"- {m.description} [{m.action_type}] conf={m.confidence:.2f}")

    return catalog


def step_query(catalog, query: str) -> tuple:
    """Select a moment matching the user's query."""
    print(f'\n=== Step 3: Select Moment for "{query}" ===')
    moment, idx = select_moment(catalog, query)
    print(f"  Selected: [{idx}] {moment.label} @ {moment.timestamp_sec:.1f}s "
          f"(frame {moment.frame_number})")
    print(f"  Reason: matching '{query}' to '{moment.label}'")
    return moment, idx


def step_snap_frames(images_dir: Path, frame_number: int) -> dict[str, np.ndarray]:
    """Snap to sharpest frames around the selected moment."""
    print(f"\n=== Step 4: Snap to Sharpest Frames (target: {frame_number}) ===")
    frame_map = snap_to_sharpest_frames(images_dir, frame_number, window=1)

    real_frames = {}
    for cam, (path, actual_frame) in frame_map.items():
        img = cv2.imread(str(path))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        real_frames[cam] = img

    return real_frames


def step_fill_gaps(real_frames: dict[str, np.ndarray], views_per_gap: int) -> list:
    """Generate synthetic views for all gaps."""
    print(f"\n=== Step 5: Generate Synthetic Views ({views_per_gap} per gap) ===")
    strip = fill_all_gaps(real_frames, views_per_gap=views_per_gap)
    print(f"\n  Strip complete: {len(strip)} total frames "
          f"({len(real_frames)} real + {len(strip) - len(real_frames)} synthetic)")
    return strip


def step_write_manifest(
    strip_filenames: list[str],
    moment,
    output_dir: Path,
) -> Path:
    """Write manifest.json for the viewer."""
    manifest = {
        "name": "Replay — Bullet Time",
        "mode": "image-strip",
        "frames": strip_filenames,
        "baseDir": "/bullet-time/",
        "total_frames": len(strip_filenames),
        "moment": {
            "label": moment.label,
            "description": moment.description,
            "timestamp_sec": moment.timestamp_sec,
            "source_frame": moment.frame_number,
        },
        "pipeline": "bullet-time",
        "generated_at": datetime.now().isoformat(),
    }

    manifest_path = Path("viewer/public/manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Manifest written to {manifest_path}")
    return manifest_path


# ── Main ───────────────────────────────────────────────────────────────


def run(
    raw_dir: Path = RAW_VIDEOS_DIR,
    images_dir: Path = SCENE_IMAGES_DIR,
    output_dir: Path = OUTPUT_DIR,
    catalog_path: Path = CATALOG_CACHE,
    query: str | None = None,
    detect_only: bool = False,
    views_per_gap: int = VIEWS_PER_GAP,
    frame_number: int | None = None,
):
    """Run the full bullet-time pipeline."""
    t_start = time.time()

    # Load or detect catalog
    catalog = load_catalog(catalog_path)
    if catalog is None or detect_only:
        catalog = step_detect(raw_dir, catalog_path)
        if detect_only:
            return

    # Select moment
    if frame_number is not None:
        # Direct frame number — skip query
        from .schemas import Moment
        moment = Moment(
            timestamp_sec=frame_number / 30.0,
            frame_number=frame_number,
            label=f"frame {frame_number}",
            description=f"Manually selected frame {frame_number}",
            action_type="manual",
            confidence=1.0,
        )
    elif query:
        moment, _ = step_query(catalog, query)
    else:
        # Default: pick highest-confidence moment
        moment = max(catalog.moments, key=lambda m: m.confidence)
        print(f"\n  Auto-selected highest confidence moment: {moment.label}")

    # Snap to sharpest frames
    real_frames = step_snap_frames(images_dir, moment.frame_number)

    # Fill gaps
    strip = step_fill_gaps(real_frames, views_per_gap)

    # Write to disk
    print(f"\n=== Step 6: Write Strip ===")
    filenames = write_strip(strip, output_dir)

    # Write manifest
    step_write_manifest(filenames, moment, output_dir)

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  DONE in {elapsed:.1f}s")
    print(f"  {len(filenames)} frames written to {output_dir}/")
    print(f"  Moment: {moment.label} @ {moment.timestamp_sec:.1f}s")
    print(f"\n  To view: cd viewer && npm run dev")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Bullet-time pipeline")
    parser.add_argument("--detect", action="store_true", help="Detect moments only (don't generate strip)")
    parser.add_argument("--query", "-q", type=str, help="Natural language query for moment selection")
    parser.add_argument("--frame", "-f", type=int, help="Direct frame number (skip query)")
    parser.add_argument("--views-per-gap", type=int, default=VIEWS_PER_GAP, help="Synthetic views per camera gap")
    parser.add_argument("--raw-dir", type=Path, default=RAW_VIDEOS_DIR, help="Raw videos directory")
    parser.add_argument("--images-dir", type=Path, default=SCENE_IMAGES_DIR, help="Synced images directory")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory for strip images")
    parser.add_argument("--catalog", type=Path, default=CATALOG_CACHE, help="Path to cached moment catalog")
    args = parser.parse_args()

    run(
        raw_dir=args.raw_dir,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        catalog_path=args.catalog,
        query=args.query,
        detect_only=args.detect,
        views_per_gap=args.views_per_gap,
        frame_number=args.frame,
    )


if __name__ == "__main__":
    main()
