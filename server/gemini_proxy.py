"""Gemini Live WebSocket Proxy — holds API key server-side.

Relays audio/text/function-calls between the browser and Gemini Live API.
The browser connects to ws://localhost:PROXY_PORT, this proxy connects to
Gemini Live via the Google GenAI SDK.

Usage:
  make proxy
  # or directly: python server/gemini_proxy.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from utils import load_config

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed. Run: make setup")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

REPLAY_TOOLS = [
    {
        "name": "orbit_camera",
        "description": "Orbit the 3D camera to a specific azimuth and elevation angle",
        "parameters": {
            "type": "object",
            "properties": {
                "azimuth": {"type": "number", "description": "Horizontal angle in degrees"},
                "elevation": {"type": "number", "description": "Vertical angle in degrees"},
            },
            "required": ["azimuth", "elevation"],
        },
    },
    {
        "name": "jump_to_frame",
        "description": "Jump to a specific frame/timestep in the replay",
        "parameters": {
            "type": "object",
            "properties": {
                "frame_index": {"type": "integer", "description": "Frame number to jump to"},
            },
            "required": ["frame_index"],
        },
    },
    {
        "name": "set_playback_speed",
        "description": "Set the replay playback speed",
        "parameters": {
            "type": "object",
            "properties": {
                "speed": {"type": "number", "description": "Playback speed multiplier (0.1 = slow-mo, 1.0 = normal)"},
            },
            "required": ["speed"],
        },
    },
    {
        "name": "toggle_play",
        "description": "Toggle play/pause of the replay",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "zoom_camera",
        "description": "Set the camera zoom level",
        "parameters": {
            "type": "object",
            "properties": {
                "level": {"type": "number", "description": "Zoom level (1.0 = default, 2.0 = 2x zoom)"},
            },
            "required": ["level"],
        },
    },
    {
        "name": "reset_view",
        "description": "Reset camera to default position and zoom",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_scene_info",
        "description": "Get information about the current scene (frame count, fps, hero frame)",
        "parameters": {"type": "object", "properties": {}},
    },
]


async def handle_browser(websocket):
    """Handle a WebSocket connection from the browser viewer."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[PROXY] ERROR: GEMINI_API_KEY not set. Copy .env.example to .env and add your key.")
        await websocket.send(json.dumps({"error": "GEMINI_API_KEY not configured on server"}))
        return

    print(f"[PROXY] Browser connected")

    # TODO: Mia — implement Gemini Live API connection here
    # 1. Connect to Gemini Live API via google-genai SDK
    # 2. Register REPLAY_TOOLS as function declarations
    # 3. Relay audio from browser → Gemini
    # 4. Relay function_call responses from Gemini → browser
    # 5. Relay function results from browser → Gemini
    # 6. Handle disconnections gracefully

    try:
        async for message in websocket:
            data = json.loads(message)
            print(f"[PROXY] Browser → Proxy: {data.get('type', 'unknown')}")

            # Placeholder: echo back for testing
            await websocket.send(json.dumps({
                "type": "status",
                "message": "Gemini Live integration not yet implemented. Tools registered.",
                "tools": [t["name"] for t in REPLAY_TOOLS],
            }))
    except websockets.ConnectionClosed:
        print("[PROXY] Browser disconnected")


async def main():
    cfg = load_config()
    port = cfg["gemini"]["proxy_port"]

    print(f"[PROXY] Gemini Live WebSocket proxy starting on ws://localhost:{port}")
    print(f"[PROXY] Model: {cfg['gemini']['model']}")
    print(f"[PROXY] Tools: {[t['name'] for t in REPLAY_TOOLS]}")

    async with websockets.serve(handle_browser, "localhost", port):
        print(f"[PROXY] Ready — waiting for browser connections")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
