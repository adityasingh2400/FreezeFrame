"""Contract validators — checks that stage outputs match the agreed interfaces.

Usage:
  python scripts/validate_contracts.py a      # validate Contract A
  python scripts/validate_contracts.py b      # validate Contract B
  python scripts/validate_contracts.py c      # validate Contract C
  python scripts/validate_contracts.py all    # validate all
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def validate_contract_a(cfg: dict) -> bool:
    """Validate Contract A: Arshia → Divij (sync + preprocessing).

    Checks:
      - Camera folders exist and are non-empty
      - Frame counts match across all cameras
      - All frames are the same resolution
      - metadata.json exists and has required fields
      - Synced videos exist
      - Frame naming convention (5-digit zero-padded)
    """
    ok = True
    images_dir = resolve_path(cfg["stage1"]["images_dir"])
    synced_dir = resolve_path(cfg["stage1"]["synced_videos_dir"])
    meta_path = resolve_path(cfg["stage1"]["metadata_path"])

    print("Contract A: Sync + Preprocessing")
    print("=" * 50)

    # metadata.json
    if not meta_path.exists():
        print(f"  {FAIL} metadata.json not found at {meta_path}")
        return False

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  {FAIL} metadata.json is invalid JSON: {e}")
        return False

    required_fields = ["fps", "num_cameras", "num_frames", "resolution"]
    for field in required_fields:
        if field not in meta:
            print(f"  {FAIL} metadata.json missing required field: {field}")
            ok = False
    if not ok:
        return False

    print(f"  {PASS} metadata.json valid (fps={meta['fps']}, cameras={meta['num_cameras']}, frames={meta['num_frames']})")

    # Camera folders
    cam_dirs = sorted([d for d in images_dir.iterdir() if d.is_dir() and d.name.startswith("cam")])
    if len(cam_dirs) == 0:
        print(f"  {FAIL} No camera directories found in {images_dir}")
        return False

    if len(cam_dirs) != meta["num_cameras"]:
        print(f"  {FAIL} Expected {meta['num_cameras']} camera dirs, found {len(cam_dirs)}")
        ok = False
    else:
        print(f"  {PASS} Found {len(cam_dirs)} camera directories")

    # Frame counts
    frame_counts = {}
    for cam_dir in cam_dirs:
        frames = sorted(cam_dir.glob("frame_*.png"))
        frame_counts[cam_dir.name] = len(frames)

    counts = list(frame_counts.values())
    if len(set(counts)) > 1:
        print(f"  {FAIL} Frame count mismatch across cameras:")
        for cam, count in frame_counts.items():
            print(f"    {cam}: {count} frames")
        ok = False
    elif counts and counts[0] != meta["num_frames"]:
        print(f"  {FAIL} Frames on disk ({counts[0]}) != metadata num_frames ({meta['num_frames']})")
        ok = False
    elif counts:
        print(f"  {PASS} All cameras have {counts[0]} frames")

    # Frame naming convention
    for cam_dir in cam_dirs:
        frames = sorted(cam_dir.glob("*.png"))
        for frame in frames:
            name = frame.stem
            if not name.startswith("frame_") or len(name) != 11:
                print(f"  {FAIL} Bad frame name: {frame.name} (expected frame_XXXXX.png)")
                ok = False
                break

    # Resolution check (sample first frame of each camera)
    resolutions = set()
    try:
        from PIL import Image
        for cam_dir in cam_dirs:
            first_frame = sorted(cam_dir.glob("frame_*.png"))
            if first_frame:
                img = Image.open(first_frame[0])
                resolutions.add(img.size)
        if len(resolutions) > 1:
            print(f"  {FAIL} Resolution mismatch: {resolutions}")
            ok = False
        elif resolutions:
            res = list(resolutions)[0]
            print(f"  {PASS} Consistent resolution: {res[0]}x{res[1]}")
    except ImportError:
        print(f"  SKIP Resolution check (Pillow not installed)")

    # Synced videos
    if synced_dir.exists():
        videos = list(synced_dir.glob("cam*.mp4"))
        if videos:
            print(f"  {PASS} Found {len(videos)} synced videos")
        else:
            print(f"  WARN No synced videos found (optional for COLMAP path)")
    else:
        print(f"  WARN Synced videos directory doesn't exist (optional)")

    if ok:
        print(f"\n  Contract A: {PASS}")
    else:
        print(f"\n  Contract A: {FAIL}")
    return ok


def validate_contract_b(cfg: dict) -> bool:
    """Validate Contract B: Divij → Aditya (camera poses).

    Checks:
      - COLMAP path: cameras.bin, images.bin, points3D.bin exist
      - LLFF path: poses_bounds.npy exists with shape (N, 17)
      - At least one path is valid
      - Camera count matches metadata
    """
    ok = True
    sparse_dir = resolve_path(cfg["stage2"]["sparse_dir"])
    poses_path = resolve_path(cfg["stage2"]["poses_bounds_path"])
    meta_path = resolve_path(cfg["stage1"]["metadata_path"])

    print("Contract B: Camera Poses")
    print("=" * 50)

    # Load metadata for camera count check
    num_cameras = None
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
            num_cameras = meta.get("num_cameras")

    # COLMAP path
    colmap_files = ["cameras.bin", "images.bin", "points3D.bin"]
    colmap_ok = True
    for fname in colmap_files:
        if not (sparse_dir / fname).exists():
            colmap_ok = False
            break

    if colmap_ok:
        print(f"  {PASS} COLMAP path: all .bin files present in {sparse_dir}")
    else:
        missing = [f for f in colmap_files if not (sparse_dir / f).exists()]
        print(f"  WARN COLMAP path missing: {', '.join(missing)}")

    # LLFF path
    llff_ok = False
    if poses_path.exists():
        try:
            import numpy as np
            poses = np.load(poses_path)
            if poses.ndim == 2 and poses.shape[1] == 17:
                llff_ok = True
                print(f"  {PASS} LLFF path: poses_bounds.npy shape={poses.shape}")
                if num_cameras and poses.shape[0] != num_cameras:
                    print(f"  {FAIL} Camera count mismatch: poses has {poses.shape[0]}, metadata says {num_cameras}")
                    ok = False
            else:
                print(f"  {FAIL} poses_bounds.npy has wrong shape: {poses.shape} (expected (N, 17))")
                ok = False
        except ImportError:
            print(f"  SKIP LLFF validation (numpy not installed)")
            llff_ok = poses_path.exists()
    else:
        print(f"  WARN LLFF path: poses_bounds.npy not found")

    if not colmap_ok and not llff_ok:
        print(f"  {FAIL} Neither COLMAP nor LLFF path is valid")
        ok = False

    if ok:
        print(f"\n  Contract B: {PASS}")
    else:
        print(f"\n  Contract B: {FAIL}")
    return ok


def validate_contract_c(cfg: dict) -> bool:
    """Validate Contract C: Aditya → Viewer (trained model).

    Checks:
      - output/frames/ contains .ply files
      - Count > 0 and <= max_export_frames
      - output_meta.json exists and is parseable
      - Frame count in meta matches .ply count
      - hero_frame in range
    """
    ok = True
    export_dir = resolve_path(cfg["stage3"]["export_dir"])
    meta_path = resolve_path(cfg["stage3"]["output_meta_path"])
    max_frames = cfg["stage3"]["max_export_frames"]

    print("Contract C: Trained Model")
    print("=" * 50)

    # PLY files
    ply_files = sorted(export_dir.glob("frame_*.ply"))
    splat_files = sorted(export_dir.glob("*.splat"))
    scene_files = ply_files or splat_files

    if not scene_files:
        print(f"  {FAIL} No .ply or .splat files found in {export_dir}")
        return False

    file_type = "ply" if ply_files else "splat"
    print(f"  {PASS} Found {len(scene_files)} .{file_type} files")

    if len(scene_files) > max_frames:
        print(f"  WARN {len(scene_files)} files exceeds MVP cap of {max_frames}")

    # Output metadata
    if not meta_path.exists():
        print(f"  WARN output_meta.json not found (optional for demo scene)")
        if ok:
            print(f"\n  Contract C: {PASS}")
        return ok

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  {FAIL} output_meta.json invalid JSON: {e}")
        return False

    print(f"  {PASS} output_meta.json valid")

    if "num_frames" in meta and meta["num_frames"] != len(scene_files):
        print(f"  {FAIL} Meta says {meta['num_frames']} frames but found {len(scene_files)} files")
        ok = False

    if "hero_frame" in meta:
        hf = meta["hero_frame"]
        if hf < 0 or hf >= len(scene_files):
            print(f"  {FAIL} hero_frame={hf} out of range [0, {len(scene_files)-1}]")
            ok = False
        else:
            print(f"  {PASS} hero_frame={hf} in range")

    if ok:
        print(f"\n  Contract C: {PASS}")
    else:
        print(f"\n  Contract C: {FAIL}")
    return ok


def main():
    cfg = load_config()

    if len(sys.argv) < 2:
        print("Usage: python validate_contracts.py [a|b|c|all]")
        sys.exit(1)

    target = sys.argv[1].lower()
    results = {}

    if target in ("a", "all"):
        results["A"] = validate_contract_a(cfg)
        print()
    if target in ("b", "all"):
        results["B"] = validate_contract_b(cfg)
        print()
    if target in ("c", "all"):
        results["C"] = validate_contract_c(cfg)
        print()

    if not results:
        print(f"Unknown contract: {target}. Use a, b, c, or all.")
        sys.exit(1)

    # Summary
    print("=" * 50)
    print("SUMMARY")
    all_pass = True
    for name, passed in results.items():
        status = PASS if passed else FAIL
        print(f"  Contract {name}: {status}")
        if not passed:
            all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
