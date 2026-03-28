"""
export_output.py — Copy 4DGS training output to Replay viewer's output/ folder.

Run this after training completes:
    python scripts/export_output.py --dataset replay --iter 15000
"""

import argparse
import json
import shutil
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
GS_ROOT    = ROOT.parent / "4DGaussians"
OUTPUT_DIR = ROOT / "output" / "frames"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="replay")
    parser.add_argument("--iter",    type=int, default=15000)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Source: 4DGS output point cloud
    src_ply = GS_ROOT / "output" / "multipleview" / args.dataset / "point_cloud" / f"iteration_{args.iter}" / "point_cloud.ply"

    if not src_ply.exists():
        # Try lower iteration checkpoints
        ckpt_dir = GS_ROOT / "output" / "multipleview" / args.dataset / "point_cloud"
        candidates = sorted(ckpt_dir.glob("iteration_*/point_cloud.ply"), reverse=True)
        if candidates:
            src_ply = candidates[0]
            print(f"[EXPORT] Using: {src_ply}")
        else:
            print(f"[ERROR] No point_cloud.ply found under {ckpt_dir}")
            return

    dest = OUTPUT_DIR / "point_cloud.ply"
    shutil.copy2(src_ply, dest)
    print(f"[EXPORT] Copied {src_ply.name} -> {dest}")

    # Write output_meta.json
    meta = {
        "num_frames": 1,
        "fps": 30,
        "hero_frame": 0,
        "splat_url": "/output/frames/point_cloud.ply",
        "dataset": args.dataset,
        "iteration": args.iter,
    }
    meta_path = ROOT / "output" / "output_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[EXPORT] Written {meta_path}")
    print(f"\n[DONE] Now run:")
    print(f"  python server/serve.py       # terminal 1 (port 8080)")
    print(f"  python server/gemini_proxy.py # terminal 2 (port 8765)")
    print(f"  Open http://localhost:8080")


if __name__ == "__main__":
    main()
