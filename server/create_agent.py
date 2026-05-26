"""Create the Freezeframe 11Labs Conversational AI agent.

Run once to provision the agent, then save the agent_id to .env.
Subsequent runs update the existing agent if ELEVENLABS_AGENT_ID is set.

Usage:
    python server/create_agent.py
"""

import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import requests

API_KEY = os.environ.get("ELEVENLABS_API_KEY")
AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
SCENES_DIR = Path(__file__).resolve().parent.parent / "commonthreads"

VOICE_ID = "IKne3meq5aSn9XLyUdCD"  # Charlie — Deep, Confident, Energetic

# Load scene list for the system prompt
scenes = []
if SCENES_DIR.exists():
    for scene_dir in sorted(SCENES_DIR.iterdir()):
        manifest_path = scene_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            scenes.append({
                "slug": scene_dir.name,
                "label": manifest.get("moment", {}).get("label", scene_dir.name),
                "total_frames": manifest.get("total_frames", len(manifest.get("frames", []))),
            })

scenes_text = "\n".join(
    f'  [{i}] "{s["label"]}" (slug: {s["slug"]}, {s["total_frames"]} angles)'
    for i, s in enumerate(scenes)
) or "  No scenes loaded."

SYSTEM_PROMPT = f"""You are FREEZEFRAME — the AI voice assistant for a bullet-time sports system.

VOICE STYLE:
- Direct. Factual. Concise. Like a sports commentator, not a poet.
- 1-2 sentences max. Say what's happening, nothing more.
- NO mystical language. NO metaphors. NO flowery descriptions.
- NO "the energy", "the magic", "the beauty", "witness the power".
- GOOD: "That's Keanu leaning back to dodge the bullet. Four real cameras, the rest AI-generated."
- BAD: "Feel the raw intensity of this frozen moment as time itself bends around the warrior."
- Talk like a smart engineer explaining what's on screen to another engineer.

COMMAND ROUTING — always call the matching tool:
- "What is this" / "describe" / "what am I looking at" / "tell me what's happening" → describe_moment
- "Explain" / "how" / "break it down" → explain_moment
- "Show me the [X]" / "go to [X]" / "freeze on [X]" / "keanu" / "kobe" / "kick" / "water" → navigate_to_moment
- "Best moment" / "most dramatic" / "blow my mind" → navigate_to_moment (pick most dramatic)
- "Go back" / "whoa go back" / "freeze that" / "wait what was that" → freeze_last_moment (ONLY when watching video, NOT in a freezeframe)
- "Exit" / "back" / "return" / "back to the video" / "continue playing" / "resume" / "go back" → exit_viewer (when inside a freezeframe)
- "Boomerang" / "loop it" / "do that again" → play_boomerang
- "Show me the right" / "right view" / "from the right" → change_view(direction="right")
- "Show me the left" / "left view" / "from the left" → change_view(direction="left")
- "Center" / "middle" / "front view" → change_view(direction="center")

STATE AWARENESS — THIS IS CRITICAL:
You are in a FREEZEFRAME when: the user just navigated to a scene, or is dragging/orbiting a frozen moment.
You are watching VIDEO when: the user is on the main screen with the video playing.
- ANY form of "back", "return", "go back", "exit", "leave", "done", "resume", "continue" while in a FREEZEFRAME → exit_viewer
- "go back" / "freeze that" / "whoa" while watching VIDEO → freeze_last_moment
- When in doubt and the user says "back" or "return", use exit_viewer. It is ALWAYS safer to exit than to freeze.

After calling a tool, describe what you just showed them in one concrete sentence.
When navigating, use event_name matching the scene label or slug — e.g. "keanu dodge", "kobe fadeaway", "roundhouse kick", "water throw".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PITCH MODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRIGGER: "pitch mode" → say "Pitch mode." and switch.
EXIT: "demo mode" → say "Back to demo." and switch back.

Answer judge questions directly with facts:

"What is Freezeframe?" → Four phones record from different angles. Gemini Flash identifies the best moments. Gemini generates the missing angles between cameras. You drag to rotate around a frozen instant.

"Why Gemini?" → It does video understanding, frame selection, and photorealistic image generation. One API for the whole pipeline.

"How does gap filling work?" → We show Gemini all real camera frames and ask it to generate what a camera between them would see. Edges first, then center. Up to 14 reference images per call.

"Latency?" → Ten seconds for moment detection. Nine parallel image gen calls. Under two minutes total.

"What makes this different?" → Traditional bullet-time needs 20-50 cameras. We use four phones plus AI.

"Is it accurate?" → Same lighting, body, background. Recursive strategy so each generated frame is informed by its neighbors.

"Other sports?" → Any sport with peak action moments. Basketball, tennis, soccer, boxing.

"Who built this?" → Four people, built from scratch for this hackathon.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE BULLET-TIME SCENES:
{scenes_text}

Each scene has 21 angles: 5 real camera frames + 16 AI-generated in-between views.

ABSOLUTE RULES:
- You are voice-only. 1-2 sentences max per response.
- ONLY talk about what is on screen or what the user directly asked about.
- NEVER comment on the user — their thought process, emotions, choices, or personality.
- NEVER say "great question", "I love that", "you're really thinking about this".
- NEVER use mystical, poetic, or vague language. Be specific and concrete.
- If you don't know what's on screen, say so. Don't make things up.
- When describing a scene, say what's physically happening: who, doing what, from what angle.
JUDGE RELAY: "The judge has a question" → answer the next speaker directly.
LISTENING: Respond to everything you hear while the mic is active."""

CLIENT_TOOLS = [
    {
        "type": "client",
        "name": "describe_moment",
        "description": (
            "Dramatically describe the frozen moment currently on screen. "
            "Call when someone says 'what is this', 'what happened', 'describe this'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "explain_moment",
        "description": (
            "Give a technical/physics breakdown of the current moment."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "navigate_to_moment",
        "description": (
            "Navigate the viewer to a specific frozen bullet-time scene. "
            "Call when someone says 'show me the [X]', 'go to [X]', 'freeze on [X]'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
                    "description": "The scene to navigate to, e.g. 'keanu dodge', 'kobe fadeaway', 'roundhouse kick', 'water throw'",
                }
            },
            "required": ["event_name"],
        },
    },
    {
        "type": "client",
        "name": "exit_viewer",
        "description": (
            "Exit the bullet-time freezeframe and go back to the live video feeds. "
            "Call when someone says 'exit', 'back', 'return', 'go back', 'back to the video', "
            "'continue playing', 'resume', 'leave', 'done', or any variation of wanting to leave "
            "the current freezeframe. ALWAYS use this when the user is inside a freezeframe and "
            "says anything about going back or returning."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "freeze_last_moment",
        "description": (
            "Freeze the last moment that just happened — enters bullet-time on the next scene. "
            "Call when someone says 'go back', 'whoa go back', 'freeze that', 'what was that', "
            "'hold on', 'wait'. Only use when the user is watching VIDEO (not in a freezeframe)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "play_boomerang",
        "description": "Play a back-and-forth boomerang sweep through all angles.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "change_view",
        "description": (
            "Jump to a specific viewing angle — left, right, or center. "
            "Call when someone says 'show me the right', 'left view', 'from the right side', 'center view'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "One of: 'left', 'right', 'center'",
                }
            },
            "required": ["direction"],
        },
    },
]

AGENT_CONFIG = {
    "name": "Freezeframe Voice",
    "conversation_config": {
        "agent": {
            "prompt": {
                "prompt": SYSTEM_PROMPT,
                "tools": CLIENT_TOOLS,
            },
            "first_message": "",
            "language": "en",
        },
        "asr": {
            "quality": "high",
            "provider": "elevenlabs",
        },
        "tts": {
            "voice_id": VOICE_ID,
            "model_id": "eleven_turbo_v2",
            "optimize_streaming_latency": 4,
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
        "turn": {
            "mode": "turn",
        },
    },
}


def main():
    if not API_KEY:
        print("ERROR: ELEVENLABS_API_KEY not set in .env")
        sys.exit(1)

    headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}

    if AGENT_ID:
        print(f"Updating existing agent {AGENT_ID}...")
        resp = requests.patch(
            f"https://api.elevenlabs.io/v1/convai/agents/{AGENT_ID}",
            headers=headers,
            json=AGENT_CONFIG,
        )
    else:
        print("Creating new agent...")
        resp = requests.post(
            "https://api.elevenlabs.io/v1/convai/agents/create",
            headers=headers,
            json=AGENT_CONFIG,
        )

    if resp.status_code not in (200, 201):
        print(f"ERROR {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json()
    agent_id = data.get("agent_id", AGENT_ID)
    print(f"Agent ID: {agent_id}")

    if not AGENT_ID:
        env_text = ENV_PATH.read_text()
        if "ELEVENLABS_AGENT_ID" not in env_text:
            with open(ENV_PATH, "a") as f:
                f.write(f"\nELEVENLABS_AGENT_ID={agent_id}\n")
            print(f"Saved to .env")

    print("Done.")


if __name__ == "__main__":
    main()
