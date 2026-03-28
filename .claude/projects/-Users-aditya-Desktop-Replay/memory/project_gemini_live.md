---
name: Gemini Live integration
description: Gemini Live API details for voice-controlled 4D replay viewer - WebSocket, function calling, ephemeral tokens
type: reference
---

Gemini Live API for voice-controlling the 4D replay viewer:

- **Protocol**: WebSocket (WSS), bidirectional audio streaming
- **Audio format**: Input 16-bit PCM 16kHz, Output 16-bit PCM 24kHz
- **Key feature**: Function calling — declare viewer commands as tools, Gemini calls them when user speaks
- **Auth for production**: Ephemeral tokens (backend provisions short-lived token, client connects directly)
- **Session limits**: 15 min audio-only, 2 min audio+video
- **Models**: `gemini-3.1-flash-live-preview` (latest), supports sync function calling
- **Pricing**: ~$0.005/min input audio, ~$0.018/min output audio

**Existing code**: `viewer/gemini_live.js` already has function call dispatch to `window.replayAPI`. `viewer/viewer.js` exposes `orbitCamera`, `jumpToFrame`, `setPlaybackSpeed`, `togglePlay`, `zoomCamera`, `resetView`, `getSceneInfo`.

**Recommended architecture**: Direct browser WebSocket with ephemeral tokens (lower latency than proxy).

**Browser audio note**: Must downsample from 44.1kHz Float32 to 16kHz Int16 PCM via AudioWorklet.

**Starter repo**: https://github.com/google-gemini/live-api-web-console
