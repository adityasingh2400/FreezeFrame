"""
Stage 1 — Capture + Sync + Preprocessing
Arshia's pipeline: raw phone videos -> aligned frames in Contract A format

Usage:
    python preprocess.py --input_dir ./raw_videos --output_dir ./scene
    python preprocess.py --input_dir ./raw_videos --output_dir ./scene --fps 30 --resolution 720x1280 --duration 10
    python preprocess.py --input_dir ./raw_videos --output_dir ./scene --skip_sync

Output (Contract A):
    scene/
      images/
        cam00/
          frame_00000.png   <-- clap frame = frame 0
          frame_00001.png
          ...
        cam01/
          ...
      metadata.json
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np


# ─────────────────────────────────────────────
# ffmpeg binary (bundled fallback)
# ─────────────────────────────────────────────

def get_ffmpeg() -> str:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        print("[ERROR] ffmpeg not found. Run: pip install imageio-ffmpeg")
        sys.exit(1)

FFMPEG = get_ffmpeg()
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


# ─────────────────────────────────────────────
# Step 1: Find video files
# ─────────────────────────────────────────────

def find_videos(input_dir: Path) -> list[Path]:
    videos = sorted([
        p for p in input_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    ])
    if not videos:
        print(f"[ERROR] No video files found in {input_dir}")
        sys.exit(1)
    print(f"[INFO] Found {len(videos)} video(s):")
    for v in videos:
        print(f"       {v.name}")
    return videos


# ─────────────────────────────────────────────
# Step 2: Extract mono audio (to temp dir)
# ─────────────────────────────────────────────

def extract_audio(video_path: Path, audio_dir: Path) -> Path:
    audio_path = audio_dir / (video_path.stem + ".wav")
    if audio_path.exists():
        return audio_path

    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-ac", "1",       # mono
        "-ar", "44100",   # 44.1kHz
        "-vn",            # no video
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Audio extraction failed for {video_path.name}")
        print(result.stderr)
        sys.exit(1)
    return audio_path


# ─────────────────────────────────────────────
# Step 3: Clap detection
# ─────────────────────────────────────────────

def find_clap_time(audio_path: Path) -> float:
    """
    Finds the clap timestamp in seconds.

    The clap is always near the START of the recording by design,
    so we search only the first 50% of the audio. Among detected
    onsets we pick the FIRST one — not the loudest — to avoid
    end-of-recording stop sounds being selected.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)

    # Only search first half to avoid end-of-recording artifacts
    y_search = y[: int(len(y) * 0.5)]
    onset_env = librosa.onset.onset_strength(y=y_search, sr=sr)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        units="frames",
        delta=0.2,
        wait=5,
    )

    if len(onset_frames) == 0:
        print(f"[WARN] No clap detected in {audio_path.name}, using 0.0s")
        return 0.0

    clap_time = float(librosa.frames_to_time(onset_frames[0], sr=sr))
    return clap_time


def compute_sync_offsets(audio_paths: list[Path]) -> list[float]:
    """
    Returns list of clap timestamps (seconds), one per video.
    Seeking to these offsets makes frame_00000 = clap frame across all cameras.
    """
    print("[INFO] Detecting clap sync point in each video...")
    offsets = []
    for ap in audio_paths:
        t = find_clap_time(ap)
        offsets.append(t)
        print(f"[INFO]   {ap.stem}: clap at {t:.4f}s")
    return offsets


# ─────────────────────────────────────────────
# Step 4: Extract frames
# ─────────────────────────────────────────────

def extract_frames(
    video_path: Path,
    output_cam_dir: Path,
    start_offset: float,
    duration: float,
    fps: int,
    resolution: tuple[int, int],
) -> int:
    """
    Seeks to start_offset, extracts `duration` seconds of frames.

    - Frames are zero-indexed: frame_00000.png = clap frame
    - Resolution is preserved with letterbox padding (no stretching)
    """
    output_cam_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(output_cam_dir / "frame_%05d.jpg")

    w, h = resolution
    # scale to fit within WxH preserving aspect ratio, then pad to exact WxH
    vf = (
        f"fps={fps},"
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", str(max(0.0, start_offset)),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-start_number", "1",     # frame_00001.jpg (1-indexed for 4DGS loader)
        "-q:v", "1",
        "-fps_mode", "cfr",
        output_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # -fps_mode is newer ffmpeg; fall back to -vsync for older versions
    if result.returncode != 0 and "-fps_mode" in result.stderr:
        cmd = [c if c != "-fps_mode" else "-vsync" for c in cmd]
        cmd[cmd.index("cfr") ] = "cfr"
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ERROR] Frame extraction failed for {video_path.name}")
        print(result.stderr)
        sys.exit(1)

    frames = sorted(output_cam_dir.glob("frame_*.jpg"))
    print(f"[OK]   {video_path.name} -> {len(frames)} frames -> {output_cam_dir.name}/")
    return len(frames)


# ─────────────────────────────────────────────
# Step 5: Quality check (blur detection)
# ─────────────────────────────────────────────

def check_frame_quality(cam_dirs: list[Path], blur_threshold: float = 50.0):
    """
    Checks each camera's first frame for blur using the Laplacian variance method.
    A variance below blur_threshold means the frame is too blurry for COLMAP.
    Warns but does not abort — blurry frames are better than nothing.
    """
    try:
        import cv2
    except ImportError:
        print("[SKIP] opencv-python not installed, skipping blur check")
        return

    print("[INFO] Checking frame quality (blur detection)...")
    for cam_dir in cam_dirs:
        frames = sorted(cam_dir.glob("frame_*.jpg"))
        if not frames:
            continue
        # Sample 3 frames: first, middle, last
        sample = [frames[0], frames[len(frames) // 2], frames[-1]]
        scores = []
        for f in sample:
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                scores.append(cv2.Laplacian(img, cv2.CV_64F).var())

        avg = np.mean(scores) if scores else 0
        status = "OK" if avg >= blur_threshold else "BLURRY"
        flag = "" if avg >= blur_threshold else "  <-- WARNING: may hurt COLMAP"
        print(f"[{status}] {cam_dir.name}: sharpness score {avg:.1f}{flag}")


# ─────────────────────────────────────────────
# Step 6: Equalize frame counts
# ─────────────────────────────────────────────

def equalize_frame_counts(cam_dirs: list[Path]) -> int:
    counts = [len(list(d.glob("frame_*.jpg"))) for d in cam_dirs]
    min_count = min(counts)
    print(f"[INFO] Frame counts per camera: {counts} -> equalizing to {min_count}")

    for d, count in zip(cam_dirs, counts):
        if count > min_count:
            frames = sorted(d.glob("frame_*.jpg"))
            for f in frames[min_count:]:
                f.unlink()

    return min_count


# ─────────────────────────────────────────────
# Step 7: Write metadata.json
# ─────────────────────────────────────────────

def write_metadata(
    output_dir: Path,
    fps: int,
    num_cameras: int,
    num_frames: int,
    resolution: tuple[int, int],
    clap_offsets: list[float],
):
    metadata = {
        "fps": fps,
        "num_cameras": num_cameras,
        "num_frames": num_frames,
        "resolution": list(resolution),
        "sync_event_frame": 0,
        "sync_offsets_seconds": clap_offsets,
    }
    meta_path = output_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[OK]   Written {meta_path}")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def parse_resolution(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except Exception:
        print(f"[ERROR] Invalid resolution '{s}' — use format like 1920x1080 or 720x1280")
        sys.exit(1)


def get_audio_duration(audio_path: Path) -> float:
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    return len(y) / sr


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stage 1: video -> synced frames (Contract A)")
    parser.add_argument("--input_dir",       required=True,            help="Folder of raw video files")
    parser.add_argument("--output_dir",      required=True,            help="Output scene folder")
    parser.add_argument("--fps",             type=int,   default=30,   help="Output FPS (default: 30)")
    parser.add_argument("--resolution",      default="720x1280",       help="Output resolution WxH (default: 720x1280)")
    parser.add_argument("--duration",        type=float, default=None, help="Seconds to extract after clap (auto if omitted)")
    parser.add_argument("--skip_sync",       action="store_true",      help="Skip clap detection, assume videos are already aligned")
    parser.add_argument("--blur_threshold",  type=float, default=50.0, help="Laplacian blur threshold (default: 50)")
    args = parser.parse_args()

    input_dir  = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    resolution = parse_resolution(args.resolution)

    if not input_dir.exists():
        print(f"[ERROR] Input directory not found: {input_dir}")
        sys.exit(1)

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Use a system temp dir for audio — keeps scene/ clean
    with tempfile.TemporaryDirectory() as tmp:
        audio_dir = Path(tmp)

        # Step 1
        videos = find_videos(input_dir)

        # Step 2
        print("[INFO] Extracting audio tracks...")
        audio_paths = [extract_audio(v, audio_dir) for v in videos]

        # Step 3
        if args.skip_sync:
            offsets = [0.0] * len(videos)
            print("[INFO] Skipping sync (--skip_sync)")
        else:
            offsets = compute_sync_offsets(audio_paths)

        print(f"[INFO] Clap offsets: {[f'{o:.3f}s' for o in offsets]}")

        # Step 4 — auto duration = shortest usable clip with 0.5s safety margin
        if args.duration:
            duration = args.duration
        else:
            usable = [get_audio_duration(ap) - off for ap, off in zip(audio_paths, offsets)]
            duration = max(1.0, min(usable) - 0.5)
            print(f"[INFO] Auto duration: {duration:.2f}s")

        cam_dirs = []
        for i, (video, offset) in enumerate(zip(videos, offsets)):
            cam_dir = images_dir / f"cam{i+1:02d}"
            extract_frames(video, cam_dir, offset, duration, args.fps, resolution)
            cam_dirs.append(cam_dir)

    # Step 5 — quality check
    check_frame_quality(cam_dirs, args.blur_threshold)

    # Step 6 — equalize
    num_frames = equalize_frame_counts(cam_dirs)

    # Step 7 — metadata
    write_metadata(output_dir, args.fps, len(videos), num_frames, resolution, offsets)

    print()
    print("=" * 50)
    print(f"[DONE] Contract A output: {output_dir}")
    print(f"       Cameras : {len(videos)}")
    print(f"       Frames  : {num_frames} per camera  (frame_00000 = clap)")
    print(f"       FPS     : {args.fps}")
    print(f"       Res     : {resolution[0]}x{resolution[1]}")
    print("=" * 50)


if __name__ == "__main__":
    main()
