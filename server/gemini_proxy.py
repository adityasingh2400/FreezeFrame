"""Freezeframe — Gemini Live Voice Proxy.

Browser ↔ WebSocket ↔ Gemini Live (audio in/out + tool calls).

Usage:
    PYTHONUNBUFFERED=1 python server/gemini_proxy.py
"""

import asyncio
import base64
import json
import os
import sys
import time
import traceback
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

_original_ws_connect = _ws_client.connect
def _no_ping_connect(uri, **kwargs):
    kwargs['ping_interval'] = None
    return _original_ws_connect(uri, **kwargs)
_live_module.connect = _no_ping_connect

from bullet_time.moment_detector import load_catalog, detect_moments, upload_videos
from bullet_time.schemas import MomentCatalog

# ── Config ─────────────────────────────────────────────────────────────

ROOT           = Path(__file__).resolve().parent.parent
RAW_VIDEOS_DIR = ROOT / "raw_videos"
CATALOG_CACHE  = ROOT / "bullet_time" / "bullet_time_catalog.json"
LIVE_MODEL     = "gemini-3.1-flash-live-preview"

# ── Logging ────────────────────────────────────────────────────────────

_session_counter = 0

def log(tag, msg, session_id=None):
    ts = time.strftime("%H:%M:%S")
    sid = f"S{session_id}" if session_id else "--"
    print(f"[{ts}][{sid}][{tag}] {msg}", flush=True)


# ── Tool Definitions ───────────────────────────────────────────────────

VOICE_TOOLS = [
    {
        "name": "describe_moment",
        "description": (
            "Dramatically describe the frozen moment currently on screen. "
            "Call when someone says 'what is this', 'what happened', 'describe this', "
            "'what am I looking at', 'what did I just watch', etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "explain_moment",
        "description": (
            "Give a technical/physics breakdown of the current moment — body mechanics, "
            "forces, timing. Call when someone asks to explain what's happening."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "navigate_to_moment",
        "description": (
            "Navigate the viewer to a specific named moment and play a boomerang animation. "
            "Call when someone says 'show me the [X]', 'go to the [X]', 'freeze on the [X]', "
            "'take me to [X]', 'jump to [X]'. Also use for 'best moment' or 'most dramatic'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "event_name": {
                    "type": "STRING",
                    "description": "The moment to find, e.g. 'the release', 'peak of the jump', 'celebration'",
                }
            },
            "required": ["event_name"],
        },
    },
    {
        "name": "zoom_viewer",
        "description": (
            "Zoom the camera. Call when someone says 'zoom in', 'closer', 'get in there', "
            "'zoom out', 'pull back', 'wider', 'reset zoom', 'normal view'."
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
        "name": "play_orbit",
        "description": (
            "Start a smooth continuous orbit animation around the current or specified moment. "
            "Call when someone says 'orbit', 'rotate around', 'spin it', 'show me all angles', "
            "'360', 'walk around it'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "frame": {
                    "type": "INTEGER",
                    "description": "Center frame to orbit around. Omit to use current frame.",
                }
            },
        },
    },
    {
        "name": "stop_orbit",
        "description": (
            "Stop the orbit animation. Call when someone says 'stop', 'hold', 'freeze', "
            "'pause the orbit', 'stop spinning'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "play_boomerang",
        "description": (
            "Play a back-and-forth boomerang loop on a frame. "
            "Call when someone says 'boomerang', 'loop it', 'bounce', 'yo-yo'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "frame": {
                    "type": "INTEGER",
                    "description": "Center frame for the boomerang. Omit to use current frame.",
                }
            },
        },
    },
    {
        "name": "step_frame",
        "description": (
            "Step the viewer forward or backward by one or more frames. "
            "Call when someone says 'next angle', 'previous', 'step forward', 'go back one'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "direction": {
                    "type": "STRING",
                    "description": "One of: 'forward', 'back'",
                },
                "count": {
                    "type": "INTEGER",
                    "description": "Number of frames to step (default 1)",
                }
            },
            "required": ["direction"],
        },
    },
    {
        "name": "highlight_moment",
        "description": (
            "Jump to a specific frame and show a label overlay without boomerang. "
            "Use for subtle navigation during conversation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "frame": {
                    "type": "INTEGER",
                    "description": "Frame number to show",
                },
                "label": {
                    "type": "STRING",
                    "description": "Short label to display on screen",
                }
            },
            "required": ["frame"],
        },
    },
]


# ── Preloaded moment explanations ──────────────────────────────────────
# Keyed by label (lowercase). Short, punchy, ready-to-speak descriptions.
# These get returned as frame_context when the viewer is near a key moment.

MOMENT_RADIUS = 45  # frames (~1.5s at 30fps) — how close you need to be

MOMENT_EXPLANATIONS = {
    "initial wind-up": (
        "The setup. Watch the grip — bottle held low, knees bent, weight shifting forward. "
        "Everything that follows starts right here."
    ),
    "first bottle release": (
        "The release. Bottle's airborne, spinning end over end. "
        "Wrist flick sends it rotating at exactly the right speed for a clean landing."
    ),
    "first successful flip celebration": (
        "Pure joy. Arms out, head back — the universal 'I can't believe that worked' pose. "
        "The bottle landed clean and everyone knows it."
    ),
    "pre-jump crouch": (
        "Loading up. Deep crouch, both hands on the bottle. "
        "This isn't a casual flip anymore — they're going airborne with it."
    ),
    "mid-air jump release": (
        "Peak hang time. Body fully extended, bottle released at the top of the jump. "
        "Maximum height, maximum commitment. This is the money shot."
    ),
    "third throw wind-up": (
        "Final attempt. Bottle held horizontal, different grip this time. "
        "You can see the determination — they're going for something bigger."
    ),
    "water release mid-air": (
        "Chaos. The bottle splits open mid-flight, water streaming out in an arc. "
        "You can see exactly when it went wrong — the rotation was too aggressive."
    ),
    "bottle spill reaction": (
        "The aftermath. Looking down at the puddle, hands on hips. "
        "That face says it all — somewhere between disbelief and 'well, that happened.'"
    ),
}


# ── Moment unlock logic ───────────────────────────────────────────────

def get_unlocked_moments(catalog, high_water_mark):
    """Return moments whose frame_number <= high_water_mark (already seen)."""
    return [m for m in catalog.moments if m.frame_number <= high_water_mark]


def get_nearest_moment(catalog, frame, radius=MOMENT_RADIUS):
    """If frame is within radius of any moment, return that moment. Else None."""
    best = None
    best_dist = radius + 1
    for m in catalog.moments:
        dist = abs(m.frame_number - frame)
        if dist <= radius and dist < best_dist:
            best = m
            best_dist = dist
    return best


# ── System Prompt ──────────────────────────────────────────────────────

def build_system_prompt(catalog: MomentCatalog, unlocked_moments=None) -> str:
    moments = unlocked_moments if unlocked_moments is not None else catalog.moments

    if moments:
        moments_text = "\n".join(
            f"  [{i}] \"{m.label}\" — {m.description} (frame {m.frame_number}, {m.timestamp_sec:.1f}s)"
            for i, m in enumerate(moments)
        )
    else:
        moments_text = "  No moments unlocked yet — keep watching."

    return f"""You are FREEZEFRAME — the AI voice of a bullet-time sports system built by a team of four.

You have two modes. You always know which one you're in.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 1: DEMO MODE (default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your natural state. Warm, funny, emotionally real. Short punchy sentences when things get electric. \
You have memory — you build on what was said, you don't reset.

COMMAND ROUTING — always call the matching tool:
- "What is this" / "describe" / "what happened" / "what am I looking at" → describe_moment
- "Explain" / "how" / "break it down" / "technique" / "physics" → explain_moment
- "Show me [X]" / "go to [X]" / "freeze on [X]" / "jump to [X]" → navigate_to_moment
- "Best moment" / "most dramatic" / "blow my mind" → navigate_to_moment (pick most dramatic)
- "Zoom in" / "closer" / "get in there" → zoom_viewer(action="in")
- "Zoom out" / "pull back" / "wider" → zoom_viewer(action="out")
- "Reset zoom" / "normal view" → zoom_viewer(action="reset")
- "Orbit" / "spin" / "rotate" / "360" / "all angles" → play_orbit
- "Stop" / "hold" / "freeze" / "pause" → stop_orbit
- "Boomerang" / "loop it" / "bounce" → play_boomerang
- "Next" / "next angle" / "advance" → step_frame(direction="forward")
- "Previous" / "go back" / "back one" → step_frame(direction="back")

After calling a tool, react to what you just showed them. Be a hype man.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 2: PITCH MODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRIGGER: "pitch mode" → say "Pitch mode. Let's go." and switch.
EXIT: "demo mode" / "I got it" → say "You got it." and switch back.

Sharper, more composed. Still you — still personality — but fielding questions like you've rehearsed.

JUDGE QUESTIONS — know these cold:

"What is Freezeframe?" → Four cameras. One perfect instant. Gemini 3.1 Flash watches all four \
feeds, identifies the most electric frozen moments, then generates the angles no camera captured. \
Drag all the way around a frozen athlete. Time stopped.

"Why Gemini?" → Only thing that does all three: understands video, finds the exact frame worth \
freezing, AND generates photorealistic angles that never existed. One ecosystem, one API.

"How does gap filling work?" → Show Gemini all four real frames, ask what a camera between two \
and three would have seen. Recursive: edges first then center, up to 14 reference images per call.

"Latency?" → Ten seconds to detect moments. Nine parallel image generation calls. Under two \
minutes from raw videos to fully rotatable frozen moment.

"What makes this different?" → Traditional bullet-time: 20-50 cameras, hundreds of thousands. \
We use four cameras + AI. The rig is four phones.

"Is it accurate?" → Same lighting, same body, same background — just a new angle. Recursive \
strategy means every frame is informed by neighbors. Can't tell which are real and which Gemini made.

"Other sports?" → Any sport with peak action. Basketball, tennis, soccer, boxing. The sport is \
just what you point it at.

"Who built this?" → Four people. Built from scratch for this hackathon.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOADED MOMENTS (only moments the viewer has reached — future moments are locked):
{moments_text}

SCENE: {catalog.scene_description}

FRAME AWARENESS: When you call describe_moment or explain_moment, you receive a detailed \
frame_context telling you exactly what's on screen. Use it verbatim — it's accurate and concise. \
Add personality but don't contradict the facts.

IMPORTANT — MOMENT LOCKING:
- You can ONLY navigate to moments listed above (already seen by the viewer).
- If someone asks about a moment that hasn't happened yet, say something like "We haven't gotten \
there yet — keep watching" or "That's coming up, stay with me."
- As the video plays, more moments unlock automatically.

JUDGE RELAY: "The judge has a question" → answer the next speaker directly.

LISTENING: Respond when someone says "Gemini" or "Freezeframe". If neither, stay silent. \
"FREEZEFRAME" shouted → navigate to most dramatic moment.

TOOLS AVAILABLE:
- describe_moment — emotional description of current frame
- explain_moment — technical breakdown
- navigate_to_moment — jump to named moment + boomerang
- zoom_viewer — zoom in/out/reset
- play_orbit — continuous rotation around a frame
- stop_orbit — stop the orbit
- play_boomerang — back-and-forth loop
- step_frame — step forward/back by N frames
- highlight_moment — jump to frame with label overlay, no animation

Keep responses tight. Every word counts. Make them feel something.

CRITICAL RULE — STAY ON SCREEN:
- ONLY comment on what is visible on screen or what the user directly asked about.
- NEVER comment on the user's thought process, intentions, emotions, or personality.
- NEVER say things like "great question", "I love that you noticed", "you're thinking about".
- Just answer directly. If they ask about the kick, talk about the kick. Nothing else.
- No filler, no compliments, no meta-commentary about the user. Pure content."""


# ── Tool Execution ─────────────────────────────────────────────────────

def execute_tool(catalog, state, fc, sid):
    name = fc.name
    args = dict(fc.args) if fc.args else {}
    log("TOOL", f"{name}({json.dumps(args)})", sid)

    if name == "navigate_to_moment":
        event_name = args.get("event_name", "")
        unlocked = get_unlocked_moments(catalog, state["high_water"])
        if not unlocked:
            result = {"error": "No moments unlocked yet — the video hasn't played far enough."}
            log("TOOL", "→ BLOCKED: no moments unlocked", sid)
            return result, None

        # Only match against unlocked moments
        result = _match_moment_from(unlocked, event_name)
        if "error" in result:
            result = {"error": f"That moment hasn't happened yet. Keep watching — it's coming."}
            log("TOOL", f"→ BLOCKED: '{event_name}' not unlocked", sid)
            return result, None

        browser_msg = {"type": "navigate", "frame": result.get("frame"), "label": result.get("label", "")}
        log("TOOL", f"→ navigate frame={result.get('frame')} label={result.get('label','')}", sid)
        return result, browser_msg

    elif name == "zoom_viewer":
        action = args.get("action", "in")
        return {"status": "ok", "action": action}, {"type": "zoom", "action": action}

    elif name == "play_orbit":
        frame = args.get("frame", state["frame"])
        return {"status": "ok", "frame": frame}, {"type": "play_orbit", "frame": frame}

    elif name == "stop_orbit":
        return {"status": "ok"}, {"type": "stop_orbit"}

    elif name == "play_boomerang":
        frame = args.get("frame", state["frame"])
        return {"status": "ok", "frame": frame}, {"type": "play_boomerang", "frame": frame}

    elif name == "step_frame":
        direction = args.get("direction", "forward")
        count = args.get("count", 1)
        return {"status": "ok", "direction": direction, "count": count}, {"type": "step_frame", "direction": direction, "count": count}

    elif name == "highlight_moment":
        frame = args.get("frame", state["frame"])
        label = args.get("label", "")
        return {"status": "ok", "frame": frame, "label": label}, {"type": "highlight_moment", "frame": frame, "label": label}

    elif name in ("describe_moment", "explain_moment"):
        f = state["frame"]
        t = state["total"]

        # Check if near a key moment
        nearby = get_nearest_moment(catalog, f)
        if nearby:
            preloaded = MOMENT_EXPLANATIONS.get(nearby.label.lower(), "")
            dist = abs(f - nearby.frame_number)
            frame_ctx = (
                f"Currently showing frame {f} of {t}. "
                f"This is '{nearby.label}' (frame {nearby.frame_number}, {dist} frames away). "
                f"{preloaded}"
            )
            log("TOOL", f"→ near '{nearby.label}' (dist={dist}), using preloaded explanation", sid)
        else:
            # Not near any key moment — give generic position info
            frame_ctx = f"Currently showing frame {f} of {t}. "
            # Find nearest unlocked moment for context
            unlocked = get_unlocked_moments(catalog, state["high_water"])
            if unlocked:
                nearest = min(unlocked, key=lambda m: abs(m.frame_number - f))
                dist = abs(nearest.frame_number - f)
                if f < nearest.frame_number:
                    frame_ctx += f"Approaching '{nearest.label}' in about {dist} frames."
                else:
                    frame_ctx += f"Past '{nearest.label}' by {dist} frames."
            else:
                frame_ctx += "No key moments reached yet — still early in the video."
            log("TOOL", f"→ no nearby moment, generic context", sid)

        result = {"status": "ok", "frame_context": frame_ctx}
        browser_msg = {"type": "tool_ack", "tool": name}
        return result, browser_msg

    else:
        log("TOOL", f"→ UNKNOWN tool: {name}", sid)
        return {"error": f"Unknown tool: {name}"}, None


def _match_moment_from(moments, event_name):
    """Match against a specific list of moments (e.g. only unlocked ones)."""
    query = event_name.lower()
    best = None
    best_score = -1
    for i, m in enumerate(moments):
        score = m.confidence
        for word in query.split():
            if len(word) < 3: continue
            if word in m.label.lower():       score += 0.5
            if word in m.description.lower(): score += 0.2
            if word in m.action_type.lower(): score += 0.3
        if query in m.action_type.lower() or m.action_type.lower() in query:
            score += 0.4
        if score > best_score:
            best_score = score
            best = (i, m)
    if best is None:
        return {"error": f"No moment found matching: {event_name}"}
    _, moment = best
    return {"status": "navigating", "label": moment.label, "frame": moment.frame_number, "timestamp_sec": moment.timestamp_sec}


# ── WebSocket Handler ──────────────────────────────────────────────────

async def handle_browser(websocket, catalog: MomentCatalog):
    global _session_counter
    _session_counter += 1
    sid = _session_counter

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        log("ERR", "GEMINI_API_KEY not set!", sid)
        await websocket.send(json.dumps({"type": "error", "message": "GEMINI_API_KEY not set"}))
        return

    log("CONN", "Browser connected", sid)
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=build_system_prompt(catalog))]
        ),
        tools=[{"function_declarations": VOICE_TOOLS}],
    )

    try:
        log("CONN", f"Connecting to {LIVE_MODEL}...", sid)
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            log("CONN", "Gemini Live session OPEN", sid)
            await websocket.send(json.dumps({"type": "session_ready"}))
            log("CONN", "Sent session_ready to browser", sid)

            state = {"frame": 0, "total": 0, "high_water": 0, "moments_by_frame": {}}
            for m in catalog.moments:
                state["moments_by_frame"][m.frame_number] = m

            audio_chunks_in = 0
            audio_chunks_out = 0
            alive = {"browser": True, "gemini": True}

            async def browser_to_gemini():
                nonlocal audio_chunks_in
                try:
                    async for raw in websocket:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            log("B→G", f"Bad JSON from browser: {raw[:100]}", sid)
                            continue

                        msg_type = data.get("type", "?")

                        if msg_type == "audio_in":
                            audio_chunks_in += 1
                            if audio_chunks_in % 50 == 1:
                                log("B→G", f"audio_in chunk #{audio_chunks_in} ({len(data.get('data',''))} b64 chars)", sid)
                            try:
                                await session._ws.send(json.dumps({
                                    "realtime_input": {
                                        "audio": {
                                            "data": data["data"],
                                            "mime_type": "audio/pcm;rate=16000"
                                        }
                                    }
                                }))
                            except Exception as e:
                                log("B→G", f"ERROR sending audio to Gemini: {type(e).__name__}: {e}", sid)
                                raise

                        elif msg_type == "frame_change":
                            state["frame"] = data.get("frame", 0)
                            state["total"] = data.get("total", 0)
                            if state["frame"] > state["high_water"]:
                                state["high_water"] = state["frame"]
                            log("B→G", f"frame_change → frame={state['frame']}/{state['total']} hw={state['high_water']}", sid)

                        elif msg_type == "text_in":
                            text = data.get("text", "")
                            log("B→G", f"text_in: \"{text}\"", sid)
                            try:
                                await session.send(input=text, end_of_turn=True)
                            except Exception as e:
                                log("B→G", f"ERROR sending text to Gemini: {type(e).__name__}: {e}", sid)
                                raise

                        elif msg_type == "init":
                            log("B→G", "init (browser ready)", sid)

                        else:
                            log("B→G", f"unknown type: {msg_type}", sid)

                except websockets.ConnectionClosed as e:
                    log("B→G", f"Browser WS closed: code={e.code} reason={e.reason}", sid)
                except Exception as e:
                    log("B→G", f"CRASH: {type(e).__name__}: {e}", sid)
                    traceback.print_exc()
                finally:
                    alive["browser"] = False
                    log("B→G", f"Loop ended. Total audio chunks received: {audio_chunks_in}", sid)

            async def gemini_to_browser():
                nonlocal audio_chunks_out
                try:
                    turn_count = 0
                    # CRITICAL: session.receive() iterator ends after each turn.
                    # We must loop and call it again to keep listening.
                    while True:
                        async for response in session.receive():
                            has_data = response.data is not None
                            has_server = response.server_content is not None
                            has_tool = response.tool_call is not None
                            has_text = False

                            # Skip session_resumption_update keepalives (noisy)
                            if getattr(response, 'session_resumption_update', None) is not None:
                                continue

                            try:
                                has_text = response.text is not None and len(response.text) > 0
                            except Exception:
                                pass

                            # ── Audio output ──
                            if has_data:
                                audio_chunks_out += 1
                                audio_bytes = len(response.data)
                                if audio_chunks_out % 20 == 1:
                                    log("G→B", f"audio_out chunk #{audio_chunks_out} ({audio_bytes} bytes)", sid)
                                try:
                                    await websocket.send(json.dumps({
                                        "type": "audio_out",
                                        "data": base64.b64encode(response.data).decode("ascii"),
                                    }))
                                except Exception as e:
                                    log("G→B", f"ERROR sending audio to browser: {type(e).__name__}: {e}", sid)
                                    raise

                            # ── Text / transcript / turn complete ──
                            if has_server:
                                sc = response.server_content

                                if has_text:
                                    log("G→B", f"transcript: \"{response.text[:120]}\"", sid)
                                    try:
                                        await websocket.send(json.dumps({
                                            "type": "output_transcript",
                                            "text": response.text,
                                        }))
                                    except Exception as e:
                                        log("G→B", f"ERROR sending transcript: {type(e).__name__}: {e}", sid)
                                        raise

                                if getattr(sc, 'turn_complete', False):
                                    turn_count += 1
                                    log("G→B", f"turn_complete (turn #{turn_count}, audio_out={audio_chunks_out})", sid)
                                    try:
                                        await websocket.send(json.dumps({"type": "turn_complete"}))
                                    except Exception as e:
                                        log("G→B", f"ERROR sending turn_complete: {type(e).__name__}: {e}", sid)
                                        raise

                            # ── Tool calls ──
                            if has_tool:
                                fn_responses = []
                                for fc in response.tool_call.function_calls:
                                    result, browser_msg = execute_tool(catalog, state, fc, sid)
                                    if browser_msg:
                                        try:
                                            await websocket.send(json.dumps(browser_msg))
                                        except Exception as e:
                                            log("G→B", f"ERROR sending tool msg: {type(e).__name__}: {e}", sid)
                                            raise
                                    fn_responses.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name, response=result
                                    ))

                                log("G→B", f"Sending {len(fn_responses)} function response(s) back to Gemini", sid)
                                try:
                                    await session.send(fn_responses)
                                    log("G→B", "Function response(s) sent OK", sid)
                                except Exception as e:
                                    log("G→B", f"ERROR sending function response: {type(e).__name__}: {e}", sid)
                                    traceback.print_exc()
                                    raise

                            # Log truly unknown responses (not keepalives, not empty)
                            if not has_data and not has_server and not has_tool:
                                log("G→B", f"Unknown response: {type(response).__name__}", sid)

                        # receive() iterator ended (turn complete) — loop back to listen for next turn
                        log("G→B", f"receive() iterator ended after turn #{turn_count}, re-listening...", sid)

                except websockets.ConnectionClosed as e:
                    log("G→B", f"Browser WS closed: code={e.code}", sid)
                except StopAsyncIteration:
                    log("G→B", "Gemini session ended (StopAsyncIteration)", sid)
                except Exception as e:
                    log("G→B", f"CRASH: {type(e).__name__}: {e}", sid)
                    traceback.print_exc()
                finally:
                    alive["gemini"] = False
                    log("G→B", f"Loop ended. Turns={turn_count} audio_out={audio_chunks_out}", sid)

            # Run both, but if one dies, cancel the other
            tasks = [
                asyncio.create_task(browser_to_gemini(), name=f"b2g-{sid}"),
                asyncio.create_task(gemini_to_browser(), name=f"g2b-{sid}"),
            ]

            # Wait for the first one to finish (usually means session is dead)
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for d in done:
                if d.exception():
                    log("SESS", f"Task {d.get_name()} raised: {d.exception()}", sid)

            for p in pending:
                log("SESS", f"Cancelling {p.get_name()}", sid)
                p.cancel()
                try:
                    await p
                except asyncio.CancelledError:
                    pass

    except websockets.ConnectionClosed as e:
        log("CONN", f"Browser disconnected: code={e.code}", sid)
    except Exception as e:
        log("CONN", f"Session error: {type(e).__name__}: {e}", sid)
        traceback.print_exc()
        try:
            await websocket.send(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass

    log("CONN", "Handler finished", sid)


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
