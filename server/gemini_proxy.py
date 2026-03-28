"""
Gemini Live WebSocket Proxy — server/gemini_proxy.py
Relays audio and function calls between the browser viewer and Gemini Live API.

Usage:
    export GEMINI_API_KEY=your_key
    python server/gemini_proxy.py
"""

import asyncio
import base64
import json
import os
import sys

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: pip install google-genai")
    sys.exit(1)

PROXY_PORT = 8765
MODEL = "gemini-2.0-flash-live-001"

SYSTEM_PROMPT = """You are the Replay Director for a 4D sports replay system.
You help users explore reconstructed 3D sports moments by controlling the camera and playback.

When the user asks to see something, call the appropriate function:
- To orbit/rotate the view: orbit_camera(azimuth, elevation)
- To jump to a specific moment: jump_to_frame(frame_index)
- To slow down or speed up: set_playback_speed(speed) — 0.1=slowmo, 1.0=normal, 2.0=fast
- To play or pause: toggle_play()
- To zoom in or out: zoom_camera(level) — 1.0=default, 2.0=2x zoom
- To reset the view: reset_view()
- To show where the scene is weakest: show_gap_confidence()
- To get scene details: get_scene_info()
- To activate cinematic director mode: toggle_director_mode()

Be concise, enthusiastic, and describe what you're doing.
Example: "Let me slow that down and orbit around to the release point."
"""

FUNCTION_DECLARATIONS = [
    types.FunctionDeclaration(
        name="orbit_camera",
        description="Orbit the 3D camera to a specific azimuth and elevation angle",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "azimuth":   types.Schema(type=types.Type.NUMBER, description="Horizontal angle in degrees (0-360)"),
                "elevation": types.Schema(type=types.Type.NUMBER, description="Vertical angle in degrees (-85 to 85)"),
            },
            required=["azimuth", "elevation"],
        ),
    ),
    types.FunctionDeclaration(
        name="jump_to_frame",
        description="Jump to a specific frame/timestep in the replay",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "frame_index": types.Schema(type=types.Type.INTEGER, description="Frame number to jump to"),
            },
            required=["frame_index"],
        ),
    ),
    types.FunctionDeclaration(
        name="set_playback_speed",
        description="Set replay playback speed. 0.1=extreme slowmo, 0.5=half, 1.0=normal, 2.0=fast",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "speed": types.Schema(type=types.Type.NUMBER, description="Speed multiplier"),
            },
            required=["speed"],
        ),
    ),
    types.FunctionDeclaration(
        name="toggle_play",
        description="Toggle play or pause of the replay",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="zoom_camera",
        description="Set camera zoom level. 1.0=wide, 5.0=default, 10.0=close",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "level": types.Schema(type=types.Type.NUMBER, description="Zoom level"),
            },
            required=["level"],
        ),
    ),
    types.FunctionDeclaration(
        name="reset_view",
        description="Reset camera to default position and pause playback",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="toggle_director_mode",
        description="Toggle the autonomous cinematic director mode that choreographs the replay",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="get_scene_info",
        description="Get information about the current scene state",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="show_gap_confidence",
        description="Show which angular sectors of the scene are weakest/under-observed",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
]


async def gemini_relay(browser_ws, api_key):
    """Connect to Gemini Live and relay between browser and Gemini."""
    client = genai.Client(api_key=api_key)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        tools=[types.Tool(function_declarations=FUNCTION_DECLARATIONS)],
        system_instruction=SYSTEM_PROMPT,
    )

    print(f"[PROXY] Connecting to Gemini Live ({MODEL})...")

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("[PROXY] Gemini Live connected")
        await browser_ws.send(json.dumps({"type": "status", "message": "Gemini Live connected"}))

        async def browser_to_gemini():
            """Forward browser messages to Gemini."""
            try:
                async for raw in browser_ws:
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "audio":
                        pcm = base64.b64decode(data["data"])
                        await session.send(
                            input=types.LiveClientRealtimeInput(
                                media_chunks=[types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")]
                            )
                        )
                    elif msg_type == "function_result":
                        await session.send(
                            input=types.LiveClientToolResponse(
                                function_responses=[
                                    types.FunctionResponse(
                                        id=data["call_id"],
                                        name=data.get("name", "unknown"),
                                        response={"result": data.get("result", {})},
                                    )
                                ]
                            )
                        )
                    elif msg_type == "init":
                        print("[PROXY] Browser handshake received")
            except websockets.ConnectionClosed:
                pass

        async def gemini_to_browser():
            """Forward Gemini responses to browser."""
            try:
                async for response in session.receive():
                    # Audio response
                    if response.data:
                        b64 = base64.b64encode(response.data).decode()
                        await browser_ws.send(json.dumps({"type": "audio", "data": b64}))

                    # Function call
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            await browser_ws.send(json.dumps({
                                "type": "function_call",
                                "call_id": fc.id,
                                "name": fc.name,
                                "args": dict(fc.args) if fc.args else {},
                            }))

                    # Text (for logging)
                    if response.text:
                        await browser_ws.send(json.dumps({"type": "transcript", "text": response.text}))
                        print(f"[GEMINI] {response.text}")

            except Exception as e:
                print(f"[PROXY] Gemini stream error: {e}")

        await asyncio.gather(browser_to_gemini(), gemini_to_browser())


async def handle_browser(websocket):
    """Handle a WebSocket connection from the browser."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        await websocket.send(json.dumps({"type": "error", "message": "GEMINI_API_KEY not set on server"}))
        print("[PROXY] ERROR: GEMINI_API_KEY not set")
        return

    print(f"[PROXY] Browser connected from {websocket.remote_address}")
    try:
        await gemini_relay(websocket, api_key)
    except websockets.ConnectionClosed:
        print("[PROXY] Browser disconnected")
    except Exception as e:
        print(f"[PROXY] Error: {e}")
        try:
            await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


async def main():
    print(f"[PROXY] Starting Gemini Live proxy on ws://localhost:{PROXY_PORT}")
    print(f"[PROXY] Model: {MODEL}")
    print(f"[PROXY] Tools: {[f.name for f in FUNCTION_DECLARATIONS]}")

    async with websockets.serve(handle_browser, "0.0.0.0", PROXY_PORT):
        print(f"[PROXY] Ready")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
