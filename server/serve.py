"""
serve.py — Static file server for the Replay viewer.
Serves viewer/ at / and output files at /output/.

Usage:
    python server/serve.py
    # Then open http://localhost:8080
"""

import http.server
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER_DIR = ROOT / "viewer"
OUTPUT_DIR = ROOT / "output"
PORT = 8080


class ReplayHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]

        if path.startswith("/output/"):
            rel = path[len("/output/"):]
            return str(OUTPUT_DIR / rel)

        # Default: serve from viewer/
        rel = path.lstrip("/") or "index.html"
        return str(VIEWER_DIR / rel)

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} - {fmt % args}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()


def main():
    os.chdir(ROOT)
    print(f"[HTTP] Serving viewer at http://localhost:{PORT}")
    print(f"[HTTP] Viewer dir: {VIEWER_DIR}")
    print(f"[HTTP] Output dir: {OUTPUT_DIR}")
    print(f"[HTTP] Open http://localhost:{PORT} in your browser")

    with http.server.HTTPServer(("0.0.0.0", PORT), ReplayHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
