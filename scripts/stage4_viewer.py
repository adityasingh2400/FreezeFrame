"""Stage 4: Web Viewer Server — Owner: Mia (after cloud infra)

Serves the viewer/ directory on localhost for the demo.
Prefers SOG frames (output/frames_sog/) for 20x compression.
Falls back to PLY frames (output/frames/) if SOG not available.

USAGE:
  make view     — serves on http://localhost:8000
  make proxy    — starts Gemini Live WebSocket proxy on ws://localhost:8765
  make demo     — downloads demo scene + launches viewer
  make convert  — convert PLY → SOG before viewing
"""

import http.server
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def build_manifest(cfg) -> dict | None:
    """Build manifest.json from available frames. Prefers SOG over PLY."""
    frames_dir_ply = resolve_path(cfg["stage3"]["export_dir"])
    frames_dir_sog = frames_dir_ply.parent / "frames_sog"
    meta_path = resolve_path(cfg["stage3"]["output_meta_path"])

    # Prefer SPZ
    sog_files = sorted(frames_dir_sog.glob("frame_*.spz")) if frames_dir_sog.exists() else []
    ply_files = sorted(frames_dir_ply.glob("frame_*.ply")) if frames_dir_ply.exists() else []

    if sog_files:
        frame_names = [f.name for f in sog_files]
        base_dir = "/output/frames_sog/"
        fmt = "spz"
    elif ply_files:
        frame_names = [f.name for f in ply_files]
        base_dir = "/output/frames/"
        fmt = "ply"
        print("  NOTE: No SPZ files found, serving PLY. Run 'make convert' for 10x smaller files.")
    else:
        return None

    fps = 30
    name = "replay"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        fps = meta.get("fps", 30)
        name = meta.get("name", "replay")

    return {
        "name": name,
        "frames": frame_names,
        "baseDir": base_dir,
        "fps": fps,
        "format": fmt,
    }


def run():
    cfg = load_config()
    viewer_dir = resolve_path(cfg["stage4"]["viewer_dir"])
    root_dir = viewer_dir.parent
    port = 8000

    # Generate manifest.json at project root
    manifest = build_manifest(cfg)
    if manifest:
        manifest_path = root_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"Stage 4: manifest.json written ({len(manifest['frames'])} {manifest['format']} frames @ {manifest['fps']} fps)")
    else:
        print("Stage 4: No frames found — viewer will load demo scene.")

    print(f"Stage 4: Serving viewer at http://localhost:{port}")
    print(f"  Open http://localhost:{port}/viewer/ in your browser")

    import os
    os.chdir(root_dir)
    handler = http.server.SimpleHTTPRequestHandler
    with http.server.HTTPServer(("", port), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    run()
