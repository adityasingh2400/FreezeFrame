"""Quick side-by-side comparison server. Shows old frame vs new frame."""

import http.server
import threading
import sys
from pathlib import Path

HTML = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Frame Comparison</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0a0a0f; color: #e8e8f0; font-family: 'Geist Mono', monospace; }
  .container { display: flex; height: 100vh; gap: 4px; padding: 4px; }
  .panel { flex: 1; display: flex; flex-direction: column; align-items: center; }
  .panel img { max-height: calc(100vh - 40px); max-width: 100%; object-fit: contain; }
  .label { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
           padding: 8px; text-align: center; }
  .label.old { color: #ff6b35; }
  .label.new { color: #00d4ff; }
</style>
</head><body>
<div class="container">
  <div class="panel">
    <div class="label old">OLD — {old_label}</div>
    <img src="/old.jpg">
  </div>
  <div class="panel">
    <div class="label new">NEW — {new_label}</div>
    <img src="/new.jpg">
  </div>
</div>
</body></html>"""


def serve(old_path, new_path, old_label="Previous", new_label="Generated", port=9999):
    old_bytes = Path(old_path).read_bytes()
    new_bytes = Path(new_path).read_bytes()
    page = HTML.replace("{old_label}", old_label).replace("{new_label}", new_label).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/old.jpg":
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(old_bytes)
            elif self.path == "/new.jpg":
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(new_bytes)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page)

        def log_message(self, *args):
            pass  # Silence logs

    server = http.server.HTTPServer(("localhost", port), Handler)
    print(f"  Compare: http://localhost:{port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python compare_viewer.py <old.jpg> <new.jpg> [port]")
        sys.exit(1)
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 9999
    serve(sys.argv[1], sys.argv[2], port=port)
    input("Press Enter to stop...")
