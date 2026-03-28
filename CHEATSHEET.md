# Freezeframe — Demo Cheat Sheet

## How to Run

### Terminal 1 — Voice Proxy
```
cd C:\Users\arusa\OneDrive\Desktop\AOA\hack\Replay
python server/gemini_proxy.py
```
You should see:
```
[PROXY] Gemini Live session open
[PROXY] Waiting for browser on ws://localhost:8765
```

### Terminal 2 — Viewer
```
cd C:\Users\arusa\OneDrive\Desktop\AOA\hack\Replay\viewer
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

| Say | What happens |
|---|---|
| **"Hey Gemini, what the hell did I just watch"** | Emotional description of current frame |
| **"Hey Gemini, what was that"** | Same — goes off about the moment |
| **"Hey Gemini, describe this"** | Describes the exact frame currently on screen |
| **"Hey Gemini, explain what's happening"** | Technical breakdown with personality |
| **"Hey Gemini, freeze on the [release / jump / etc]"** | Navigates to that moment + boomerang |
| **"Hey Gemini, show me the best moment"** | Picks most dramatic, navigates there |
| **"Hey Gemini, blow my mind"** | Same as above |
| **"Hey Gemini, zoom in"** / **"get closer"** | Zooms camera in |
| **"Hey Gemini, zoom out"** / **"pull back"** | Zooms camera out |
| **"Hey Gemini, reset zoom"** | Back to normal view |
| **"Hey Gemini, calm down"** | It laughs, then immediately loses it again |

---

### Pitch Mode (judge Q&A — sharp, confident, still has personality)

| Say | What happens |
|---|---|
| **"pitch mode"** / **"hey gemini pitch mode"** | Switches to pitch mode |
| **"demo mode"** / **"I got it"** / **"I'll take it"** | Switches back to demo mode |

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
| **"Gemini, the judge has a question"** | Next speaker answered directly, no wake word needed |
| **"Judge, go ahead"** | Same — opens the floor |
| **"Ask Gemini directly"** | Same |

After answering, Gemini goes back to silence mode automatically.

---

### Frame-Aware Description
While **dragging the viewer**, Gemini tracks which frame you're on.
When you say "describe this" or "explain this" it knows the exact frame + which labeled moment it matches.

---

## Full Command Reference

```
FREEZEFRAME          → dramatic jump to best moment
pitch mode           → judge Q&A mode
demo mode            → fun/hype mode
I got it             → exit pitch mode
Gemini, describe this           → describes current frame
Gemini, explain what's happening → tech breakdown
Gemini, freeze on [X]           → navigate to moment
Gemini, zoom in                 → zoom in
Gemini, zoom out                → zoom out
Gemini, reset zoom              → normal view
Gemini, the judge has a question → open floor to judge
Gemini, show me the best moment → most dramatic moment
Gemini, blow my mind            → same
Gemini, calm down               → it laughs
```

---

## Stack

| Component | What it does |
|---|---|
| `server/gemini_proxy.py` | Python WebSocket proxy — bridges browser ↔ Gemini Live |
| `viewer/src/gemini_live.js` | Browser voice client — mic capture, audio playback, tool handling |
| `viewer/src/main.js` | Three.js viewer — frame tracking, zoom, boomerang |
| Gemini Live model | `gemini-3.1-flash-live-preview` |
| Proxy port | `ws://localhost:8765` |
| Viewer port | `http://localhost:5173` |

---

## If Something Breaks

| Problem | Fix |
|---|---|
| "Mic not working" | Refresh browser, allow mic permissions |
| "Browser disconnected" | Restart proxy, refresh browser |
| "Not responding to voice" | Make sure you said "Hey Gemini" first |
| "0 moments loaded" | Add videos to `raw_videos/` folder and restart proxy |
| Proxy crashes | Check terminal for error, share with team |
