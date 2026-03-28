"""Stage 4: Web Viewer Server — Owner: Mia (after cloud infra)

Serves the viewer/ directory on localhost for the demo.
The viewer loads .ply files from output/frames/ and renders them with gsplat.js.

USAGE:
  make view     — serves on http://localhost:8000
  make proxy    — starts Gemini Live WebSocket proxy on ws://localhost:8765
  make demo     — downloads demo scene + launches viewer
"""

import http.server
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def run():
    cfg = load_config()
    viewer_dir = resolve_path(cfg["stage4"]["viewer_dir"])
    port = 8000

    print(f"Stage 4: Serving viewer at http://localhost:{port}")
    print(f"  Viewer dir: {viewer_dir}")
    print(f"  Frames dir: {resolve_path(cfg['stage4']['frames_dir'])}")

    import os
    os.chdir(viewer_dir.parent)
    handler = http.server.SimpleHTTPRequestHandler
    with http.server.HTTPServer(("", port), handler) as httpd:
        print(f"  Open http://localhost:{port}/viewer/ in your browser")
        httpd.serve_forever()


if __name__ == "__main__":
    run()
