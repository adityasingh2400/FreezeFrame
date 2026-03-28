"""Download a pre-baked demo scene for viewer development.

Fetches a Gaussian splat scene so the viewer team can develop orbit/zoom/time
controls without waiting for the full pipeline to produce output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_config, resolve_path


def download_file(url: str, dest: Path):
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: make setup")
        sys.exit(1)

    print(f"  Downloading {url}")
    print(f"  Destination: {dest}")

    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  Progress: {pct}% ({downloaded}/{total} bytes)", end="", flush=True)
        print(f"\n  Downloaded {downloaded} bytes")
    except requests.ConnectionError:
        print("ERROR: Download failed — no network connection.")
        print("  Copy a .ply or .splat file manually to output/frames/")
        sys.exit(1)
    except requests.Timeout:
        print("ERROR: Download timed out after 60s.")
        print("  Copy a .ply or .splat file manually to output/frames/")
        sys.exit(1)


def run():
    cfg = load_config()
    url = cfg["stage4"]["demo_scene_url"]
    frames_dir = resolve_path(cfg["stage4"]["frames_dir"])

    filename = url.split("/")[-1]
    dest = frames_dir / filename

    print("Download Demo Scene")
    print("=" * 50)

    if dest.exists():
        print(f"  Demo scene already exists: {dest}")
        return

    download_file(url, dest)
    print(f"  Demo scene ready at {dest}")
    print(f"  Run 'make view' to launch the viewer")


if __name__ == "__main__":
    run()
