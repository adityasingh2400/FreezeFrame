# Freezeframe — Demo Cheat Sheet

## How to Run

### Terminal 1 — Voice Proxy
```
cd /path/to/Replay
python server/gemini_proxy.py
```
You should see:
```
[PROXY] Gemini Live session open
[PROXY] Waiting for browser on ws://localhost:8765
```

### Terminal 2 — Viewer
```
cd /path/to/Replay/viewer
npm run dev
```
Open: **http://localhost:5173**

---

## Voice Commands

### Wake Word
Gemini is **always listening** but only responds when directly addressed.

| Trigger | Notes |
|---|---|
| **"Hey Gemini, ..."** | Main wake word |
| **"Hey Freezeframe, ..."** | Alternative wake word |
| **"FREEZEFRAME"** (shout it) | Jumps to most dramatic moment + boomerang |

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

**In pitch mode, Gemini knows:**
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
| **"Gemini, the judge has a question"** | Next speaker answered directly |
| **"Judge, go ahead"** | Same — opens the floor |
| **"Ask Gemini directly"** | Same |

After answering, Gemini goes back to silence mode automatically.

---

## Stack

| Component | What it does |
|---|---|
| `server/gemini_proxy.py` | Python WebSocket proxy — bridges browser ↔ Gemini Live |
| `viewer/src/gemini_live.js` | Browser voice client — mic capture, audio playback, tool handling |
| `viewer/src/main.js` | Three.js viewer — frame tracking, zoom, boomerang |
| `viewer/public/pcm-processor.js` | AudioWorklet — 32ms PCM chunks at 16kHz |
| Gemini Live model | `gemini-3.1-flash-live-preview` |
| Proxy port | `ws://localhost:8765` |
| Viewer port | `http://localhost:5173` |

---

## Tool → Command Routing

| Gemini Tool | Proxy Result | Browser Message Type | Viewer Action |
|---|---|---|---|
| `describe_moment` | frame context | `tool_ack` | Gemini narrates |
| `explain_moment` | frame context | `tool_ack` | Gemini explains |
| `navigate_to_moment` | matched frame | `navigate` | `setFrame()` + boomerang |
| `zoom_viewer` | action passthrough | `zoom` | `camera.zoom` adjust |
| `play_orbit` | center frame | `play_orbit` | continuous rotation |
| `stop_orbit` | ok | `stop_orbit` | stops animation |
| `play_boomerang` | center frame | `play_boomerang` | back-and-forth loop |
| `step_frame` | direction + count | `step_frame` | `stepFrame(±N)` |
| `highlight_moment` | frame + label | `highlight_moment` | jump + overlay |

---

## If Something Breaks

| Problem | Fix |
|---|---|
| "Mic not working" | Refresh browser, allow mic permissions |
| "Browser disconnected" | Auto-reconnects with backoff. If stuck, restart proxy + refresh |
| "Not responding to voice" | Say "Hey Gemini" first. Check debug console (bottom-right) |
| "0 moments loaded" | Add videos to `raw_videos/` folder and restart proxy |
| Proxy crashes | Check terminal for error, share with team |
| "Connecting..." stuck | Proxy not running or GEMINI_API_KEY not set in .env |
