# Freezeframe — Demo Cheat Sheet

## How to Run

### One-time setup
```
make install
make setup-agent
```

### Start
```
make start
```
Open: **http://localhost:5173**

---

## Voice Control

### Activation
**Hold spacebar** to talk. Release to stop. The AI responds after you release.

| Action | What happens |
|---|---|
| **Hold spacebar + speak** | Mic active, voice sent to AI |
| **Release spacebar** | Mic off, AI processes and responds |

---

### Demo Mode (default — fun, emotional, reactive)

| Say | Tool Called | What Happens |
|---|---|---|
| "describe this" / "what is this" / "what happened" | `describe_moment` | Emotional description of current frame |
| "explain" / "how does this work" / "break it down" | `explain_moment` | Technical breakdown with personality |
| "show me the [X]" / "go to [X]" / "freeze on [X]" | `navigate_to_moment` | Navigates to moment + boomerang |
| "best moment" / "blow my mind" / "most dramatic" | `navigate_to_moment` | Picks most dramatic, navigates there |
| "zoom in" / "closer" / "get in there" | `zoom_viewer(in)` | Zooms camera in |
| "zoom out" / "pull back" / "wider" | `zoom_viewer(out)` | Zooms camera out |
| "reset zoom" / "normal view" | `zoom_viewer(reset)` | Back to normal view |
| "orbit" / "spin it" / "360" / "all angles" | `play_orbit` | Continuous rotation animation |
| "stop" / "hold" / "freeze" / "pause" | `stop_orbit` | Stops orbit animation |
| "boomerang" / "loop it" / "bounce" | `play_boomerang` | Back-and-forth loop |
| "next angle" / "advance" | `step_frame(forward)` | Step one frame forward |
| "previous" / "go back" | `step_frame(back)` | Step one frame back |

---

### Pitch Mode (judge Q&A — sharp, confident, still has personality)

| Say | What happens |
|---|---|
| **"pitch mode"** | Switches to pitch mode |
| **"demo mode"** / **"I got it"** | Switches back to demo mode |

**In pitch mode, the agent knows:**
- What is Freezeframe
- Why Gemini (vs anything else)
- How gap filling works
- What the latency is (~90s end to end)
- What makes it different from traditional bullet-time (4 cameras vs 50)
- Whether it's accurate
- Can it work for other sports
- Who built it (team of 4, built for this hackathon)

---

### Judge Relay (hand the mic to a judge)

| Say | What happens |
|---|---|
| **"The judge has a question"** | Next speaker answered directly |
| **"Judge, go ahead"** | Same — opens the floor |

---

## Stack

| Component | What it does |
|---|---|
| `server/voice_proxy.py` | Lightweight signing server — generates signed WebSocket URLs |
| `server/create_agent.py` | Creates/updates the ElevenLabs Conversational AI agent |
| `viewer/src/voice.js` | Browser voice client — 11Labs WebSocket, mic capture, tool execution |
| `viewer/src/main.js` | Three.js viewer — frame tracking, zoom, boomerang, spacebar PTT |
| `viewer/public/pcm-processor.js` | AudioWorklet — 32ms PCM chunks at 16kHz |
| Voice engine | ElevenLabs Conversational AI (Charlie voice) |
| Signing server | `ws://localhost:8765` |
| Viewer | `http://localhost:5173` |

---

## Architecture

```
Browser mic → AudioWorklet (16kHz PCM)
  → 11Labs WebSocket (direct, signed URL)
    → STT + LLM + TTS (all 11Labs)
  ← audio response + client tool calls
Browser executes tools locally (navigate, zoom, orbit, etc.)
```

No Python proxy in the audio path. The signing server only runs once per session to issue a URL.

---

## If Something Breaks

| Problem | Fix |
|---|---|
| "Mic not working" | Refresh browser, allow mic permissions |
| "Voice server not running" | `make start` — signing server must be running |
| "Not responding" | Hold spacebar while speaking. Check debug console |
| "0 moments loaded" | Run `make setup-agent` to recreate agent with catalog |
| "Session expired" | Refresh the page (gets a new signed URL) |
| "Agent not found" | Check `.env` for `ELEVENLABS_AGENT_ID`, run `make setup-agent` |
