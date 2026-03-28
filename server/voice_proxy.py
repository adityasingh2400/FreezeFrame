"""Freezeframe — Lightweight voice signing server.

Serves a signed WebSocket URL so the browser can connect directly to 11Labs
without exposing the API key. Also serves the moment catalog for client-side
tool execution.

Usage:
    PYTHONUNBUFFERED=1 python server/voice_proxy.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed. Run: pip install websockets")
    sys.exit(1)

import requests

ROOT = Path(__file__).resolve().parent.parent
CATALOG_CACHE = ROOT / "bullet_time_catalog.json"
SCENES_DIR = ROOT / "commonthreads"

API_KEY = os.environ.get("ELEVENLABS_API_KEY")
AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")


def get_signed_url():
    """Get a signed WebSocket URL from 11Labs for the browser to connect to."""
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={AGENT_ID}",
        headers={"xi-api-key": API_KEY},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get signed URL: {resp.status_code} {resp.text}")
    return resp.json()["signed_url"]


def load_catalog():
    """Load the moment catalog for client-side tool execution."""
    if CATALOG_CACHE.exists():
        return json.loads(CATALOG_CACHE.read_text())
    return {"scene_description": "", "moments": []}


def load_scenes():
    """Scan commonthreads/ for precomputed scenes and return their manifests."""
    scenes = []
    if not SCENES_DIR.exists():
        return scenes
    for scene_dir in sorted(SCENES_DIR.iterdir()):
        manifest_path = scene_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            scenes.append({
                "slug": scene_dir.name,
                "label": manifest.get("moment", {}).get("label", scene_dir.name),
                "description": manifest.get("moment", {}).get("description", ""),
                "total_frames": manifest.get("total_frames", len(manifest.get("frames", []))),
            })
    return scenes


async def handle_request(websocket):
    """Handle a browser request for a signed URL + catalog."""
    try:
        raw = await websocket.recv()
        msg = json.loads(raw)
    except Exception:
        msg = {}

    if msg.get("type") == "get_config":
        try:
            signed_url = get_signed_url()
            catalog = load_catalog()
            scenes = load_scenes()
            await websocket.send(json.dumps({
                "type": "config",
                "signed_url": signed_url,
                "agent_id": AGENT_ID,
                "catalog": catalog,
                "scenes": scenes,
            }))
        except Exception as e:
            await websocket.send(json.dumps({
                "type": "error",
                "message": str(e),
            }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Unknown request type. Send {type: 'get_config'}",
        }))


async def main():
    port = int(os.environ.get("PROXY_PORT", 8765))

    if not API_KEY:
        print("ERROR: ELEVENLABS_API_KEY not set!")
        sys.exit(1)
    if not AGENT_ID:
        print("ERROR: ELEVENLABS_AGENT_ID not set! Run: python server/create_agent.py")
        sys.exit(1)

    print(f"\n[VOICE] Freezeframe Voice Server")
    print(f"[VOICE] Agent: {AGENT_ID}")
    print(f"[VOICE] Port: {port}")
    print(f"[VOICE] Waiting for browser on ws://localhost:{port}\n")

    async with websockets.serve(handle_request, "localhost", port, ping_interval=None):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
