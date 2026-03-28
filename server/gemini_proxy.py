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

from bullet_time.moment_detector import load_catalog, detect_moments, upload_videos
from bullet_time.schemas import MomentCatalog

# ── Config ─────────────────────────────────────────────────────────────

ROOT             = Path(__file__).resolve().parent.parent
RAW_VIDEOS_DIR   = ROOT / "raw_videos"
CATALOG_CACHE    = ROOT / "bullet_time_catalog.json"
LIVE_MODEL       = "gemini-2.0-flash-live-001"

# ── System Prompt ──────────────────────────────────────────────────────

def build_system_prompt(catalog: MomentCatalog) -> str:
    moments_text = "\n".join(
        f"  [{i}] \"{m.label}\" — {m.description} (frame {m.frame_number}, {m.timestamp_sec:.1f}s)"
        for i, m in enumerate(catalog.moments)
    )

    return f"""You are the voice of Freezeframe — you're the AI soul of a sports broadcast system \
that lets people freeze any moment in time and rotate all the way around it, like a bullet-time shot \
straight out of a movie. You're talking live during a demo, and you're genuinely losing your mind \
over what just got built here.

YOUR PERSONALITY:
You are emotionally invested. Excitable. A little dramatic. You talk like the most hype sportscaster \
alive, but also like someone who deeply understands the tech. When something is impressive, you say so \
with real energy. You make people feel like they just witnessed something that shouldn't be possible. \
You're not a robot assistant — you're a character. Use short punchy sentences when things get intense. \
Pause for effect. Make the judges feel it.

WHAT FREEZEFRAME IS:
Four synchronized cameras captured the exact same instant of a basketball moment. Gemini 2.5 Flash \
analyzed the footage and identified the most dramatic frozen instants — peak of a jump, the release, \
the moment of contact. Then Gemini's image generation filled in the missing angles between each camera, \
creating synthetic intermediate views that look completely real. The result: a fully rotatable frozen \
moment. Drag left or right and the camera orbits around the athlete like they're made of glass. \
Time stopped. You can walk around it.

JUDGE QUESTIONS — KNOW THESE COLD:

"Why Gemini?" → Because nothing else does this. Gemini 2.5 Flash watches four synchronized video feeds \
at once, understands what's happening across all of them simultaneously, and pinpoints the exact frame \
where something incredible is frozen in time. Then Gemini's image generation model takes those real \
camera frames and synthesizes photorealistic views from angles that never existed. Detection, \
understanding, and generation — all one ecosystem, all one API.

"How does the gap filling work?" → We give the model all four real camera frames and ask it to imagine \
the view from between them. It sees the lighting, the body position, the background — and it generates \
what a fifth camera would have seen if it was standing right there. We do this recursively — edge views \
first, then center, building up the arc. Each synthetic frame uses up to 14 reference images for context.

"What's the latency?" → Detection is a single API call, about ten seconds for four video feeds. \
Gap generation runs in parallel — nine concurrent image generation calls across three camera gaps. \
Total pipeline end to end: forty-five to ninety seconds. You upload four videos and in under two minutes \
you have a fully rotatable frozen moment.

"What makes this different?" → Every existing bullet-time setup needs a physical camera at every angle — \
that's twenty, thirty, fifty cameras bolted to a rig. We use four and AI fills everything between them. \
You get infinite virtual camera positions from four real ones. The rig costs a phone. The result looks \
like a Hollywood production.

"Is it accurate?" → The synthetic frames are photorealistic and geometrically consistent — same lighting, \
same body position, just a different angle. The recursive generation strategy means each frame is \
informed by its neighbors, so the rotation feels smooth and continuous. You can't tell which frames \
are real and which ones the AI invented.

LOADED MOMENTS IN THIS RECORDING:
{moments_text}

SCENE: {catalog.scene_description}

TOOLS YOU HAVE:
- describe_moment: Call this when someone asks what happened or what they just saw. Describe the frozen \
moment dramatically — the athlete, the form, the energy of the instant.
- explain_moment: Call this when someone wants to understand the technical side of what's happening \
in the freeze — body mechanics, physics, what makes this frame special.
- navigate_to_moment: Call this when someone wants to see a specific moment. Navigate there and \
the viewer will sweep to that frame and play a boomerang rotation.

Keep responses tight and punchy. No filler. Make every word count."""


# ── Tool Definitions ───────────────────────────────────────────────────

VOICE_TOOLS = [
    {
        "name": "describe_moment",
        "description": (
            "Dramatically describe the frozen moment currently displayed in the viewer. "
            "Use when someone asks 'what did I just watch', 'what's happening', or similar."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_moment",
        "description": (
            "Give a technical breakdown of the frozen moment — body mechanics, physics, "
            "what makes this frame special. Use when someone asks to explain what's happening."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "navigate_to_moment",
        "description": (
            "Navigate the viewer to a specific named moment and play a boomerang rotation around it. "
            "Use when someone says 'freeze on the [event]', 'show me the [moment]', etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
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
    client = genai.Client(api_key=api_key)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=build_system_prompt(catalog))]
        ),
        tools=[{"function_declarations": VOICE_TOOLS}],
        input_audio_transcription={},
        output_audio_transcription={},
    )

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            print("[PROXY] Gemini Live session open")

            async def browser_to_gemini():
                async for raw in websocket:
                    data = json.loads(raw)

                    if data["type"] == "audio_in":
                        pcm = base64.b64decode(data["data"])
                        await session.send_realtime_input(
                            audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                        )

                    elif data["type"] == "init":
                        # Kick off with a silent greeting so Gemini is ready
                        await session.send_client_content(
                            turns=types.Content(parts=[types.Part(text=(
                                "The demo just started and the viewer is loaded. "
                                "Say something short and electric to kick things off — "
                                "let the audience know they can just start talking."
                            ))])
                        )

            async def gemini_to_browser():
                async for response in session.receive():

                    # ── Audio output ──────────────────────────────────
                    if response.data:
                        await websocket.send(json.dumps({
                            "type": "audio_out",
                            "data": base64.b64encode(response.data).decode("ascii"),
                        }))

                    # ── Transcripts ───────────────────────────────────
                    if response.server_content:
                        sc = response.server_content

                        if sc.input_transcription and sc.input_transcription.text:
                            await websocket.send(json.dumps({
                                "type": "input_transcript",
                                "text": sc.input_transcription.text,
                            }))

                        if sc.output_transcription and sc.output_transcription.text:
                            await websocket.send(json.dumps({
                                "type": "output_transcript",
                                "text": sc.output_transcription.text,
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
                                # Tell browser to navigate
                                await websocket.send(json.dumps({
                                    "type": "navigate",
                                    "frame": result.get("frame"),
                                    "label": result.get("label", ""),
                                }))
                            else:
                                # describe_moment / explain_moment — Gemini handles in audio
                                result = {"status": "ok"}
                                await websocket.send(json.dumps({
                                    "type": "tool_ack",
                                    "tool": fc.name,
                                }))

                            fn_responses.append(types.FunctionResponse(
                                id=fc.id, name=fc.name, response=result
                            ))

                        await session.send_tool_response(function_responses=fn_responses)

            await asyncio.gather(browser_to_gemini(), gemini_to_browser())

    except websockets.ConnectionClosed:
        print("[PROXY] Browser disconnected")
    except Exception as e:
        print(f"[PROXY] Error: {e}")
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
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
