"""Stage 1: Audio Sync + Frame Extraction — Owner: Arshia

INPUT:  Raw phone videos in scene/raw_videos/ (cam00.mp4, cam01.mov, etc.)
OUTPUT: Contract A — see below

CONTRACT A OUTPUT:
  Video path:  scene/synced_videos/cam00.mp4, cam01.mp4, ...
  Frame path:  scene/images/cam00/frame_00000.png, cam01/frame_00000.png, ...
  Metadata:    scene/metadata.json

RULES:
  - Every camera folder has the EXACT same number of frames
  - frame_00000 from every camera = same instant (sync point = clap)
  - All PNGs are the same resolution
  - All synced videos are the same FPS and duration
  - If cameras have different durations, TRIM ALL to the shortest post-sync duration

ALGORITHM:
  1. Extract audio track from each video (ffmpeg)
  2. Cross-correlate audio waveforms to find the clap offset (scipy)
  3. Trim all videos so clap = frame 0, trim to shortest duration
  4. Extract frames as PNG at target FPS/resolution (ffmpeg)
  5. Run blur detection (cv2.Laplacian variance) and flag blurry frames
  6. Write metadata.json
  7. Validate with: make validate-a
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def find_raw_videos(raw_dir: Path) -> list[Path]:
    """Find all video files in the raw_videos directory.

    Returns sorted list of paths to .mp4/.mov/.MOV files.
    """
    raise NotImplementedError("Arshia: implement this")


def extract_audio(video_path: Path, output_path: Path):
    """Extract audio track from a video file using ffmpeg.

    Args:
        video_path: Path to input video
        output_path: Path to write .wav audio
    """
    raise NotImplementedError("Arshia: implement this")


def find_sync_offset(audio_paths: list[Path]) -> dict[str, float]:
    """Cross-correlate audio waveforms to find time offsets.

    Uses the clap/loud-event as the sync point. Returns a dict mapping
    camera name -> offset in seconds relative to the earliest camera.
    """
    raise NotImplementedError("Arshia: implement this")


def extract_frames(
    video_path: Path,
    output_dir: Path,
    fps: int,
    resolution: tuple[int, int],
    start_offset: float,
    max_frames: int,
):
    """Extract frames from a video starting at start_offset.

    Outputs: output_dir/frame_00000.png, frame_00001.png, ...
    All frames resized to resolution. Stops after max_frames.
    """
    raise NotImplementedError("Arshia: implement this")


def detect_blur(frame_path: Path, threshold: float = 100.0) -> bool:
    """Return True if the frame is blurry (Laplacian variance below threshold)."""
    raise NotImplementedError("Arshia: implement this")


def write_metadata(
    output_path: Path,
    fps: int,
    num_cameras: int,
    num_frames: int,
    resolution: tuple[int, int],
    blurry_frames: dict[str, list[int]],
):
    """Write scene/metadata.json with all required fields."""
    raise NotImplementedError("Arshia: implement this")


def run():
    cfg = load_config()
    raw_dir = resolve_path(cfg["stage1"]["raw_videos_dir"])
    synced_dir = resolve_path(cfg["stage1"]["synced_videos_dir"])
    images_dir = resolve_path(cfg["stage1"]["images_dir"])
    metadata_path = resolve_path(cfg["stage1"]["metadata_path"])
    fps = cfg["stage1"]["target_fps"]
    resolution = tuple(cfg["stage1"]["target_resolution"])

    print(f"Stage 1: Sync + Frame Extraction")
    print(f"  Raw videos:    {raw_dir}")
    print(f"  Synced videos: {synced_dir}")
    print(f"  Frames:        {images_dir}")
    print(f"  Target:        {fps}fps @ {resolution[0]}x{resolution[1]}")

    # TODO: implement the pipeline
    raise NotImplementedError("Arshia: implement run()")


if __name__ == "__main__":
    run()
