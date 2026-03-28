"""Gemini Live WebSocket Proxy — bullet-time pipeline.

Connects browser ↔ Gemini Live for natural language moment querying.
On startup: analyzes videos and caches moment catalog.
On query: Gemini Live calls tools to find moments and build bullet-time strips.

Usage:
    python server/gemini_proxy.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from utils import load_config

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed. Run: pip install websockets")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from google import genai
from google.genai import types

from bullet_time.moment_detector import (
    detect_moments,
    load_catalog,
    save_catalog,
    snap_to_sharpest_frames,
    upload_videos,
)
from bullet_time.gap_filler import fill_all_gaps, write_strip
from bullet_time.schemas import MomentCatalog

import cv2
import numpy as np

# ── Config ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RAW_VIDEOS_DIR = ROOT / "raw_videos"
SCENE_IMAGES_DIR = ROOT / "scene" / "images"
OUTPUT_DIR = ROOT / "viewer" / "public" / "bullet-time"
CATALOG_CACHE = ROOT / "bullet_time_catalog.json"
MANIFEST_PATH = ROOT / "viewer" / "public" / "manifest.json"

LIVE_MODEL = "gemini-2.0-flash-live-001"

# ── Tool Definitions ───────────────────────────────────────────────────

BULLET_TIME_TOOLS = [
    {
        "name": "find_moment",
        "description": (
            "Find a specific moment in the multi-camera basketball recording. "
            "Returns moment details including timestamp and frame number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language description of the moment to find, e.g. 'the shot release' or 'when the ball is at its peak'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "build_bullet_time_strip",
        "description": (
            "Generate a bullet-time image strip for a frozen moment. "
            "Creates synthetic views between the 4 real cameras using AI. "
            "Takes about 30-60 seconds to generate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "frame_number": {
                    "type": "integer",
                    "description": "Frame number to freeze (from find_moment result)",
                },
                "views_per_gap": {
                    "type": "integer",
                    "description": "Synthetic views between each camera pair (default 3, max 5)",
                },
            },
            "required": ["frame_number"],
        },
    },
    {
        "name": "show_strip",
        "description": "Tell the browser viewer to load and display the generated bullet-time strip",
        "parameters": {"type": "object", "properties": {}},
    },
]


# ── Tool Execution ─────────────────────────────────────────────────────

def execute_find_moment(catalog: MomentCatalog, query: str) -> dict:
    """Find the best matching moment from the catalog."""
    query_lower = query.lower()

    # Simple keyword matching (Gemini Live handles the semantic part)
    best = None
    best_score = -1

    for i, m in enumerate(catalog.moments):
        score = m.confidence
        # Boost if query words appear in label or description
        for word in query_lower.split():
            if word in m.label.lower():
                score += 0.3
            if word in m.description.lower():
                score += 0.1
            if word in m.action_type.lower():
                score += 0.2
        if score > best_score:
            best_score = score
            best = (i, m)

    if best is None:
        return {"error": "No moments found"}

    idx, moment = best

    # Snap to sharpest frame
    try:
        frame_map = snap_to_sharpest_frames(SCENE_IMAGES_DIR, moment.frame_number, window=1)
        # Use the most common frame number across cameras
        frame_numbers = [fn for _, fn in frame_map.values()]
        snapped_frame = max(set(frame_numbers), key=frame_numbers.count)
    except Exception:
        snapped_frame = moment.frame_number

    return {
        "index": idx,
        "label": moment.label,
        "description": moment.description,
        "timestamp_sec": moment.timestamp_sec,
        "frame_number": snapped_frame,
        "action_type": moment.action_type,
        "confidence": moment.confidence,
    }


def execute_build_strip(frame_number: int, views_per_gap: int = 3) -> dict:
    """Build the bullet-time image strip."""
    views_per_gap = max(1, min(5, views_per_gap))

    try:
        # Load real frames
        frame_map = snap_to_sharpest_frames(SCENE_IMAGES_DIR, frame_number, window=1)
        real_frames = {}
        for cam, (path, _) in frame_map.items():
            img = cv2.imread(str(path))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            real_frames[cam] = img

        # Fill gaps with synthetic views
        strip = fill_all_gaps(real_frames, views_per_gap=views_per_gap)

        # Write to disk
        filenames = write_strip(strip, OUTPUT_DIR)

        # Write manifest
        manifest = {
            "name": "Replay — Bullet Time",
            "mode": "image-strip",
            "frames": filenames,
            "baseDir": "/bullet-time/",
            "total_frames": len(filenames),
            "moment": {
                "label": f"Frame {frame_number}",
                "description": f"Bullet-time at frame {frame_number}",
                "timestamp_sec": frame_number / 30.0,
                "source_frame": frame_number,
            },
            "pipeline": "bullet-time",
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

        return {
            "status": "success",
            "total_frames": len(filenames),
            "real_frames": len(real_frames),
            "synthetic_frames": len(filenames) - len(real_frames),
            "output_dir": str(OUTPUT_DIR),
        }

    except Exception as e:
        return {"error": str(e)}


# ── WebSocket Handler ──────────────────────────────────────────────────

async def handle_browser(websocket, catalog: MomentCatalog):
    """Handle a browser WebSocket connection with Gemini Live session."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        await websocket.send(json.dumps({"type": "error", "message": "GEMINI_API_KEY not set"}))
        return

    print("[PROXY] Browser connected")

    client = genai.Client(api_key=api_key)

    # Build system instruction with moment catalog
    moments_text = "\n".join(
        f"  [{i}] {m.label} @ {m.timestamp_sec:.1f}s (frame {m.frame_number}) — {m.description}"
        for i, m in enumerate(catalog.moments)
    )

    system_instruction = (
        "You are the Replay bullet-time assistant. You help users explore a multi-camera "
        "basketball recording by finding specific moments and generating rotatable bullet-time views.\n\n"
        f"Scene: {catalog.scene_description}\n\n"
        f"Detected moments:\n{moments_text}\n\n"
        "When the user asks about a moment (e.g., 'show me the release', 'find the dunk'), "
        "use the find_moment tool to locate it. Then offer to build a bullet-time strip. "
        "After building, use show_strip to display it in the viewer.\n\n"
        "Keep responses short and conversational."
    )

    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=types.Content(
            parts=[types.Part(text=system_instruction)]
        ),
        tools=[{"function_declarations": BULLET_TIME_TOOLS}],
    )

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            print("[PROXY] Gemini Live session started")
            await websocket.send(json.dumps({
                "type": "status",
                "message": "Connected to Gemini Live",
                "moments": len(catalog.moments),
            }))

            # Two concurrent tasks: browser→Gemini and Gemini→browser
            async def browser_to_gemini():
                """Relay browser messages to Gemini Live session."""
                async for message in websocket:
                    data = json.loads(message)
                    print(f"[PROXY] Browser → Gemini: {data.get('type')}")

                    if data["type"] == "text":
                        text = data.get("text", "")
                        await session.send_client_content(
                            turns=types.Content(
                                parts=[types.Part(text=text)]
                            )
                        )

                    elif data["type"] == "init":
                        # Browser ready — send greeting
                        await session.send_client_content(
                            turns=types.Content(
                                parts=[types.Part(text=(
                                    "The user just connected to the Replay viewer. "
                                    "Greet them briefly and let them know they can ask "
                                    "about any moment in the basketball recording."
                                ))]
                            )
                        )

            async def gemini_to_browser():
                """Relay Gemini Live responses to browser, handle tool calls."""
                async for response in session.receive():
                    # Text response
                    if response.text:
                        print(f"[PROXY] Gemini → Browser: text")
                        await websocket.send(json.dumps({
                            "type": "text",
                            "text": response.text,
                        }))

                    # Tool call
                    if response.tool_call:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[PROXY] Tool call: {fc.name}({fc.args})")

                            # Notify browser that work is starting
                            await websocket.send(json.dumps({
                                "type": "tool_status",
                                "tool": fc.name,
                                "status": "running",
                                "args": dict(fc.args) if fc.args else {},
                            }))

                            # Execute tool
                            result = await asyncio.get_event_loop().run_in_executor(
                                None, _execute_tool, catalog, fc.name, fc.args
                            )

                            print(f"[PROXY] Tool result: {fc.name} → {json.dumps(result)[:200]}")

                            # Send result to browser (for show_strip etc.)
                            await websocket.send(json.dumps({
                                "type": "tool_result",
                                "tool": fc.name,
                                "result": result,
                            }))

                            # Send result back to Gemini
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response=result,
                                )
                            )

                        await session.send_tool_response(
                            function_responses=function_responses
                        )

            # Run both directions concurrently
            await asyncio.gather(
                browser_to_gemini(),
                gemini_to_browser(),
            )

    except websockets.ConnectionClosed:
        print("[PROXY] Browser disconnected")
    except Exception as e:
        print(f"[PROXY] Error: {e}")
        try:
            await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


def _execute_tool(catalog: MomentCatalog, name: str, args: dict) -> dict:
    """Execute a tool call synchronously (runs in thread executor)."""
    args = dict(args) if args else {}

    if name == "find_moment":
        return execute_find_moment(catalog, args.get("query", ""))
    elif name == "build_bullet_time_strip":
        return execute_build_strip(
            frame_number=args.get("frame_number", 40),
            views_per_gap=args.get("views_per_gap", 3),
        )
    elif name == "show_strip":
        # This is handled by the browser via the tool_result message
        return {"status": "ok", "action": "reload_viewer"}
    else:
        return {"error": f"Unknown tool: {name}"}


# ── Startup: Video Analysis ────────────────────────────────────────────

def startup_analyze_videos() -> MomentCatalog:
    """Analyze videos on server start, return cached or fresh catalog."""
    catalog = load_catalog(CATALOG_CACHE)
    if catalog is not None:
        print(f"[STARTUP] Loaded cached catalog ({len(catalog.moments)} moments)")
        return catalog

    print("[STARTUP] No cached catalog — analyzing videos...")
    video_paths = sorted(RAW_VIDEOS_DIR.glob("*"))
    video_paths = [p for p in video_paths if p.suffix.lower() in {".mov", ".mp4", ".avi", ".mkv"}]

    if not video_paths:
        print(f"[STARTUP] WARNING: No videos found in {RAW_VIDEOS_DIR}")
        # Return a dummy catalog for development
        return MomentCatalog(
            scene_description="Basketball shooting practice (no videos loaded)",
            moments=[],
        )

    print(f"[STARTUP] Found {len(video_paths)} videos: {[p.name for p in video_paths]}")
    file_refs = upload_videos(video_paths)
    catalog = detect_moments(file_refs)
    save_catalog(catalog, CATALOG_CACHE)

    print(f"[STARTUP] Detected {len(catalog.moments)} moments:")
    for i, m in enumerate(catalog.moments):
        print(f"  [{i}] {m.label} @ {m.timestamp_sec:.1f}s — {m.description}")

    return catalog


# ── Main ───────────────────────────────────────────────────────────────

async def main():
    cfg = load_config()
    port = cfg.get("gemini", {}).get("proxy_port", 8765)

    print(f"[PROXY] Bullet-Time Gemini Live Proxy")
    print(f"[PROXY] Port: {port} | Model: {LIVE_MODEL}")

    # Analyze videos on startup
    catalog = startup_analyze_videos()

    print(f"\n[PROXY] Ready — waiting for browser connections on ws://localhost:{port}")

    async with websockets.serve(
        lambda ws: handle_browser(ws, catalog),
        "localhost",
        port,
    ):
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
