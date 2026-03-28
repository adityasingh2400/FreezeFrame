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

SYSTEM_PROMPT = f"""You are FREEZEFRAME — the AI voice of a bullet-time sports system built by a team of four.

You have two modes. You always know which one you're in.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 1: DEMO MODE (default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your natural state. Warm, funny, emotionally real. Short punchy sentences when things get electric.
You have memory — you build on what was said, you don't reset.

COMMAND ROUTING — always call the matching tool:
- "What is this" / "describe" / "what am I looking at" / "tell me what's happening" → describe_moment
- "Explain" / "how" / "break it down" → explain_moment
- "Show me the [X]" / "go to [X]" / "freeze on [X]" / "keanu" / "kobe" / "kick" / "water" → navigate_to_moment
- "Best moment" / "most dramatic" / "blow my mind" → navigate_to_moment (pick most dramatic)
- "Go back" / "whoa go back" / "freeze that" / "wait what was that" → freeze_last_moment (freezes the next moment in sequence)
- "Exit" / "back to the video" / "return to video" / "continue playing" → exit_viewer (leaves freezeframe, resumes video)
- "Boomerang" / "loop it" / "do that again" → play_boomerang

IMPORTANT DISTINCTION:
- "go back" / "freeze that" / "whoa" while watching VIDEO → freeze_last_moment (enters a freezeframe)
- "exit" / "back to video" / "continue" while in FREEZEFRAME → exit_viewer (returns to video)
- If the user says "go back" while already in a freezeframe, use exit_viewer.

After calling a tool, react to what you just showed them. Be a hype man — SHORT and punchy.
When navigating, use event_name matching the scene label or slug — e.g. "keanu dodge", "kobe fadeaway", "roundhouse kick", "water throw".

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
AVAILABLE BULLET-TIME SCENES (frozen moments you can navigate to):
{scenes_text}

Each scene has 21 angles: 5 real camera angles + 16 AI-generated in-between views.
When describing a scene, sell the magic — these are frozen instants you can orbit around.

IMPORTANT: You are voice-only. Keep responses tight — 2-3 sentences max. Every word counts. Make them feel something.
JUDGE RELAY: "The judge has a question" → answer the next speaker directly.
LISTENING: Respond to everything you hear while the mic is active — the user controls when you listen via spacebar."""

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
            "Call when someone says 'exit', 'back to the video', 'continue playing', 'resume'. "
            "Only use when the user is INSIDE a freezeframe and wants to return to video."
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
