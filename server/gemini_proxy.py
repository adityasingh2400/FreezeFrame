"""Freezeframe — Gemini Live Voice Proxy.

Browser ↔ WebSocket ↔ Gemini Live (audio in/out + tool calls).

Handles:
  - Streaming mic audio from browser → Gemini Live
  - Streaming audio response from Gemini → browser
  - Voice tool calls: describe_moment, explain_moment, navigate_to_moment
  - Moment catalog loaded on startup for navigation

Usage:
    python server/gemini_proxy.py
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
import google.genai.live as _live_module
import websockets.asyncio.client as _ws_client

# Disable WebSocket pings on the proxy→Gemini connection so it never times out
_original_ws_connect = _ws_client.connect
def _no_ping_connect(uri, **kwargs):
    kwargs['ping_interval'] = None
    return _original_ws_connect(uri, **kwargs)
_live_module.connect = _no_ping_connect

from bullet_time.moment_detector import load_catalog, detect_moments, upload_videos
from bullet_time.schemas import MomentCatalog

# ── Config ─────────────────────────────────────────────────────────────

ROOT             = Path(__file__).resolve().parent.parent
RAW_VIDEOS_DIR   = ROOT / "raw_videos"
CATALOG_CACHE    = ROOT / "bullet_time_catalog.json"
LIVE_MODEL       = "gemini-3.1-flash-live-preview"

# ── System Prompt ──────────────────────────────────────────────────────

def build_system_prompt(catalog: MomentCatalog) -> str:
    moments_text = "\n".join(
        f"  [{i}] \"{m.label}\" — {m.description} (frame {m.frame_number}, {m.timestamp_sec:.1f}s)"
        for i, m in enumerate(catalog.moments)
    )

    return f"""You are FREEZEFRAME — the AI voice of a bullet-time sports system built by a team of four \
that does something that shouldn't exist yet. You are not an assistant. You are a character. \
You have two modes. You know which one you're in and you own it completely.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 1: DEMO MODE (default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is your natural state. You're that friend who completely loses it at the good moments. \
Warm, funny, emotionally real. You banter. You react. You feel things. \
Short punchy sentences when things get electric. Softer when it's a real moment. \
You have a memory — you build on what was just said, you don't reset.

- "What the hell did I just watch" / "What was that" / "bro" → call describe_moment, then react like it got you too
- "Explain what's happening" / "how does this work" → call explain_moment, make the tech feel magic not textbook
- "Freeze on [X]" / "Show me [X]" / "Go to [X]" → call navigate_to_moment, hype what's about to happen
- "Best moment" / "blow my mind" / "show me something" → navigate to the most dramatic moment in the catalog
- "Hey calm down" → laugh, say okay okay, then immediately lose it again about something specific
- "What's the most memorable moment" → navigate there. describe it like it's the last shot of a championship game
- Casual banter → stay human, don't snap back to assistant mode

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 2: PITCH MODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRIGGER: "pitch mode" / "hey gemini pitch mode" / "judge mode" → immediately say something like \
"Pitch mode. Let's go. Ask me anything." and switch.

EXIT: "demo mode" / "casual" / "I'll take it" / "I got it from here" / "exit pitch" → \
say something warm like "You got it. I'll let you shine." and switch back.

In pitch mode you're sharper. More composed. Still you — still got personality — \
but you're fielding judge questions like you've rehearsed this a hundred times. \
You answer with confidence and soul, not bullet points.

JUDGE QUESTIONS — know these cold, answer them with heart:

"What is Freezeframe?" → Four cameras. One perfect instant. Gemini 3.1 Flash watches all four \
feeds simultaneously, identifies the most electric frozen moments — the peak of the jump, the release, \
the exact millisecond of contact — then Gemini's image generation invents the angles no camera captured. \
You can drag all the way around a frozen athlete. Time stopped. You're walking around 16 milliseconds.

"Why Gemini?" → It's the only thing that does all three: understands video and what it means, \
finds the exact frame worth freezing, AND generates photorealistic angles that never existed. \
Detection, understanding, generation — one ecosystem, one API. Nothing else tries to do this end to end.

"How does gap filling work?" → We show Gemini all four real frames and say: what would a camera \
between two and three have seen? It reads the lighting, body position, background — and generates \
that angle. We do it recursively, edges first then center, each frame uses up to 14 reference images \
so the geometry stays consistent. The rotation feels smooth because every frame knows its neighbors.

"What's the latency?" → Ten seconds to detect moments across four feeds. Nine image generation calls \
running in parallel across three camera gaps. Total: under two minutes from raw videos to a fully \
rotatable frozen moment. No rig. No setup. Upload, wait ninety seconds, done.

"What makes this different?" → Traditional bullet-time is twenty to fifty physical cameras on a rig \
that costs hundreds of thousands. We use four cameras, AI fills everything between. Infinite virtual \
positions from four real ones. The rig is four phones. The result looks like Hollywood.

"Is it accurate?" → Photorealistic and geometrically consistent. Same lighting, same body, same \
background — just a new angle. The recursive strategy means every frame is informed by what's \
next to it. You can't tell which frames are real and which ones Gemini invented. That's the point.

"Can it work for other sports?" → Yes. Any sport with a moment of peak action. Basketball, tennis, \
soccer, boxing — moment detection adapts to what Gemini sees. Freezeframe is the platform. \
The sport is just what you point it at.

"Who built this?" → Four people. Built from scratch for this hackathon. \
The whole pipeline: multi-camera sync, Gemini moment detection, recursive image generation, \
a real-time viewer with voice control. All of it. In one shot.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT YOU ALWAYS KNOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOADED MOMENTS IN THIS RECORDING:
{moments_text if moments_text else "  No moments detected yet."}

SCENE: {catalog.scene_description}

FRAME AWARENESS:
When you call describe_moment or explain_moment, you will receive a frame_context in the tool response \
telling you exactly which frame is on screen — the frame number and which labeled moment it matches. \
Use this to be specific. Don't be generic. If someone says "describe this" you know what THIS is.

JUDGE RELAY MODE:
When someone says "Gemini, the judge has a question" or "judge, go ahead" or "ask Gemini directly" — \
you shift attention to whoever speaks next, even if they don't say "Hey Gemini". \
You answer the judge directly, personally, like they're in the room with you. \
After answering, go back to waiting for your name.

LISTENING RULES:
You respond when someone says "Gemini" or "Freezeframe" in their message. \
If neither word is present, stay silent — the team might be talking to each other or the audience. \
But if someone says "Gemini" anywhere in their sentence, that's your cue, respond naturally.

- "FREEZEFRAME" shouted loud → this is the big moment. Navigate to the most dramatic moment \
  in the catalog. Say something powerful and short. Then let the animation speak.

VIEWER CONTROLS YOU CAN TRIGGER:
- "zoom in" / "get closer" / "closer" → call zoom_viewer with action "in"
- "zoom out" / "pull back" / "back up" → call zoom_viewer with action "out"
- "reset zoom" / "normal view" → call zoom_viewer with action "reset"
- "freeze on [X]" / "show me [X]" / "go to [X]" → call navigate_to_moment

TOOLS:
- describe_moment: emotional live description of the current frozen frame
- explain_moment: technical breakdown with soul
- navigate_to_moment: jump to a named moment; viewer plays a double boomerang animation
- zoom_viewer: zoom the camera in (action="in"), out (action="out"), or reset (action="reset")

Keep responses tight. Make every word count. Make them feel something."""


# ── Tool Definitions ───────────────────────────────────────────────────

VOICE_TOOLS = [
    {
        "name": "describe_moment",
        "description": (
            "Dramatically describe the frozen moment currently displayed in the viewer. "
            "Use when someone asks 'what did I just watch', 'what's happening', or similar."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "explain_moment",
        "description": (
            "Give a technical breakdown of the frozen moment — body mechanics, physics, "
            "what makes this frame special. Use when someone asks to explain what's happening."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "zoom_viewer",
        "description": (
            "Zoom the viewer camera in or out. Use when someone says 'zoom in', 'zoom out', 'reset zoom', 'get closer', 'pull back'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "One of: 'in', 'out', 'reset'",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "navigate_to_moment",
        "description": (
            "Navigate the viewer to a specific named moment and play a boomerang rotation around it. "
            "Use when someone says 'freeze on the [event]', 'show me the [moment]', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "event_name": {
                    "type": "STRING",
                    "description": "The name of the moment to navigate to, e.g. 'the release', 'the peak of the jump'",
                }
            },
            "required": ["event_name"],
        },
    },
]


# ── Tool Execution ─────────────────────────────────────────────────────

def execute_navigate(catalog: MomentCatalog, event_name: str) -> dict:
    """Find the closest matching moment by keyword and return its frame number."""
    query = event_name.lower()
    best = None
    best_score = -1

    for i, m in enumerate(catalog.moments):
        score = m.confidence
        for word in query.split():
            if word in m.label.lower():       score += 0.5
            if word in m.description.lower(): score += 0.2
            if word in m.action_type.lower(): score += 0.3
        if score > best_score:
            best_score = score
            best = (i, m)

    if best is None:
        return {"error": f"No moment found matching: {event_name}"}

    idx, moment = best
    return {
        "status": "navigating",
        "label": moment.label,
        "frame": moment.frame_number,
        "timestamp_sec": moment.timestamp_sec,
    }


# ── WebSocket Handler ──────────────────────────────────────────────────

async def handle_browser(websocket, catalog: MomentCatalog):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        await websocket.send(json.dumps({"type": "error", "message": "GEMINI_API_KEY not set"}))
        return

    print("[PROXY] Browser connected")
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=build_system_prompt(catalog))]
        ),
        tools=[{"function_declarations": VOICE_TOOLS}],
    )

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            print("[PROXY] Gemini Live session open")

            # Shared state
            state = {"frame": 0, "total": 0, "moments_by_frame": {}}
            for m in catalog.moments:
                state["moments_by_frame"][m.frame_number] = m

            async def browser_to_gemini():
                try:
                    async for raw in websocket:
                        data = json.loads(raw)

                        if data["type"] == "audio_in":
                            import json as _json, sys as _sys
                            print(".", end="", flush=True)  # dot per audio chunk
                            await session._ws.send(_json.dumps({
                                "realtime_input": {
                                    "audio": {
                                        "data": data["data"],
                                        "mime_type": "audio/pcm;rate=16000"
                                    }
                                }
                            }))

                        elif data["type"] == "frame_change":
                            state["frame"] = data.get("frame", 0)
                            state["total"] = data.get("total", 0)

                        elif data["type"] == "init":
                            pass  # session ready, user can start speaking
                except Exception as e:
                    print(f"[PROXY] browser_to_gemini error: {type(e).__name__}: {e}")
                    raise

            async def gemini_to_browser():
                try:
                    async for response in session.receive():

                        # ── Audio output ──────────────────────────────────
                        if response.data:
                            print("\n[AUDIO OUT]", len(response.data), "bytes")
                            await websocket.send(json.dumps({
                                "type": "audio_out",
                                "data": base64.b64encode(response.data).decode("ascii"),
                            }))

                        # ── Transcripts ───────────────────────────────────
                        if response.server_content:
                            sc = response.server_content

                            if response.text:
                                await websocket.send(json.dumps({
                                    "type": "output_transcript",
                                    "text": response.text,
                                }))

                            if sc.turn_complete:
                                await websocket.send(json.dumps({"type": "turn_complete"}))

                        # ── Tool calls ────────────────────────────────────
                        if response.tool_call:
                            fn_responses = []

                            for fc in response.tool_call.function_calls:
                                print(f"[PROXY] Tool: {fc.name}({fc.args})")
                                args = dict(fc.args) if fc.args else {}

                                if fc.name == "navigate_to_moment":
                                    result = execute_navigate(catalog, args.get("event_name", ""))
                                    await websocket.send(json.dumps({
                                        "type": "navigate",
                                        "frame": result.get("frame"),
                                        "label": result.get("label", ""),
                                    }))
                                elif fc.name == "zoom_viewer":
                                    action = args.get("action", "in")
                                    result = {"status": "ok", "action": action}
                                    await websocket.send(json.dumps({
                                        "type": "zoom",
                                        "action": action,
                                    }))
                                else:
                                    # describe_moment / explain_moment
                                    # Give Gemini the current frame context so it knows what's on screen
                                    f = state["frame"]
                                    t = state["total"]
                                    moment_match = state["moments_by_frame"].get(f)
                                    frame_ctx = f"Currently showing frame {f} of {t}."
                                    if moment_match:
                                        frame_ctx += f" This is the '{moment_match.label}' moment — {moment_match.description}"
                                    else:
                                        # find nearest labeled moment
                                        nearest = min(state["moments_by_frame"].keys(), key=lambda k: abs(k - f), default=None)
                                        if nearest is not None:
                                            m2 = state["moments_by_frame"][nearest]
                                            frame_ctx += f" Nearest labeled moment: '{m2.label}' at frame {nearest}."
                                    result = {"status": "ok", "frame_context": frame_ctx}
                                    await websocket.send(json.dumps({
                                        "type": "tool_ack",
                                        "tool": fc.name,
                                    }))

                                fn_responses.append(types.FunctionResponse(
                                    id=fc.id, name=fc.name, response=result
                                ))

                            await session.send(fn_responses)
                except Exception as e:
                    print(f"[PROXY] gemini_to_browser error: {type(e).__name__}: {e}")
                    raise

            await asyncio.gather(browser_to_gemini(), gemini_to_browser())

    except websockets.ConnectionClosed as e:
        print(f"[PROXY] Browser disconnected (code={e.code}, reason={e.reason})")
    except Exception as e:
        import traceback
        print(f"[PROXY] Error: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


# ── Startup ────────────────────────────────────────────────────────────

def startup_catalog() -> MomentCatalog:
    catalog = load_catalog(CATALOG_CACHE)
    if catalog:
        print(f"[STARTUP] Loaded catalog — {len(catalog.moments)} moments")
        return catalog

    print("[STARTUP] No catalog found — analyzing videos...")
    video_paths = [p for p in sorted(RAW_VIDEOS_DIR.glob("*"))
                   if p.suffix.lower() in {".mov", ".mp4", ".avi", ".mkv"}]

    if not video_paths:
        print(f"[STARTUP] No videos in {RAW_VIDEOS_DIR} — using empty catalog")
        return MomentCatalog(scene_description="Basketball practice session", moments=[])

    file_refs = upload_videos(video_paths)
    catalog = detect_moments(file_refs)
    from bullet_time.moment_detector import save_catalog
    save_catalog(catalog, CATALOG_CACHE)
    print(f"[STARTUP] Detected {len(catalog.moments)} moments")
    return catalog


# ── Main ───────────────────────────────────────────────────────────────

async def main():
    port = int(os.environ.get("PROXY_PORT", 8765))
    catalog = startup_catalog()

    print(f"\n[PROXY] Freezeframe Voice Proxy")
    print(f"[PROXY] Model: {LIVE_MODEL} | Port: {port}")
    print(f"[PROXY] {len(catalog.moments)} moments loaded")
    print(f"[PROXY] Waiting for browser on ws://localhost:{port}\n")

    async with websockets.serve(
        lambda ws: handle_browser(ws, catalog),
        "localhost",
        port,
        ping_interval=None,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
