/**
 * Freezeframe voice — ElevenLabs Conversational AI, bare WebSocket.
 *
 * Tap spacebar to toggle mic. Agent hears you, responds with voice + tool calls.
 */

const MIC_RATE = 16000;

// ── Scenes ────────────────────────────────────────────────────────────

const SCENES = [
  { slug: 'keanu_dodge',     label: 'The Keanu Dodge',     desc: 'A person dodging backwards, leaning away Matrix-style. Peak evasion, captured from every angle.' },
  { slug: 'kobe_fadeaway',   label: 'The Kobe Fadeaway',   desc: 'The signature fadeaway jumper — body fading back, arm extended, ball at the release point. Pure finesse.' },
  { slug: 'roundhouse_kick', label: 'The Roundhouse Kick', desc: 'Full-body rotation, leg extended in a perfect roundhouse. Maximum torque, frozen at the moment of impact.' },
  { slug: 'water_throw',     label: 'The Water Throw',     desc: 'A water bottle mid-flight, liquid trailing through the air. The throw that went spectacularly wrong.' },
];

let sceneIndex = 0;

function matchScene(query) {
  const q = query.toLowerCase();
  let best = null, bestScore = -1;
  for (const s of SCENES) {
    let score = 0;
    if (s.label.toLowerCase() === q || s.slug === q) score += 10;
    for (const w of q.split(/\s+/)) {
      if (w.length < 3) continue;
      if (s.label.toLowerCase().includes(w)) score += 2;
      if (s.slug.includes(w)) score += 1.5;
    }
    if (score > bestScore) { bestScore = score; best = s; }
  }
  return bestScore > 0 ? best : null;
}

function nextScene() {
  const scene = SCENES[sceneIndex % SCENES.length];
  sceneIndex++;
  return scene;
}

// ── State ─────────────────────────────────────────────────────────────

let ws            = null;
let sessionReady  = false;
let micStream     = null;
let audioCtx      = null;
let workletNode   = null;
let micSource     = null;
let micActive     = false;
let audioPlayer   = null;

let onNavigate        = null;
let onExitViewer      = null;
let onIndicatorChange = null;
let onUserSpeech      = null;

let viewerFrame = 0;
let viewerTotal = 0;
let currentSceneLabel = '';

// ── Base64 ────────────────────────────────────────────────────────────

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function toBase64(bytes) {
  let r = '', len = bytes.length, rem = len % 3, end = len - rem;
  for (let i = 0; i < end; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i+1] << 8) | bytes[i+2];
    r += B64[(n>>18)&63] + B64[(n>>12)&63] + B64[(n>>6)&63] + B64[n&63];
  }
  if (rem === 1) { const n = bytes[end]; r += B64[n>>2] + B64[(n<<4)&63] + '=='; }
  else if (rem === 2) { const n = (bytes[end]<<8)|bytes[end+1]; r += B64[n>>10] + B64[(n>>4)&63] + B64[(n<<2)&63] + '='; }
  return r;
}

// ── Audio playback ────────────────────────────────────────────────────

class Player {
  constructor(rate) { this.ctx = null; this.rate = rate; this.nextAt = 0; }
  _init() {
    if (!this.ctx) this.ctx = new AudioContext({ sampleRate: this.rate });
    if (this.ctx.state === 'suspended') this.ctx.resume();
  }
  play(b64) {
    this._init();
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const i16 = new Int16Array(u8.buffer);
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / (i16[i] < 0 ? 0x8000 : 0x7fff);
    const buf = this.ctx.createBuffer(1, f32.length, this.rate);
    buf.copyToChannel(f32, 0);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    const now = this.ctx.currentTime;
    if (this.nextAt < now) this.nextAt = now;
    src.start(this.nextAt);
    this.nextAt += buf.duration;
  }
  reset() { this.nextAt = 0; }
  stop() { if (this.ctx) { this.ctx.close(); this.ctx = null; } this.nextAt = 0; }
}

// ── Indicator ─────────────────────────────────────────────────────────

function setIndicator(state) {
  if (onIndicatorChange) onIndicatorChange(state);
  if (window.setIndicatorState) window.setIndicatorState(state);
  const el = document.getElementById('listening-indicator');
  if (el) el.dataset.state = state;
}

// ── Public API ────────────────────────────────────────────────────────

export function isMicActive() { return micActive; }
export function reportFrameChange(f, t) { viewerFrame = f; viewerTotal = t; }
export function setCurrentScene(l) {
  currentSceneLabel = l || '';
  // Tell the agent what scene we're now viewing
  if (ws && ws.readyState === WebSocket.OPEN && l) {
    const sceneInfo = SCENES.find(s => s.label === l);
    const desc = sceneInfo ? sceneInfo.desc : '';
    ws.send(JSON.stringify({
      type: 'contextual_update',
      text: `USER IS NOW VIEWING FREEZEFRAME: "${l}". ${desc}. 21 angles: 5 real cameras + 16 AI-generated views.`,
    }));
  }
  if (ws && ws.readyState === WebSocket.OPEN && !l) {
    ws.send(JSON.stringify({
      type: 'contextual_update',
      text: `USER IS NOW BACK TO WATCHING LIVE VIDEO FEEDS. Not in a freezeframe.`,
    }));
  }
}

export function setMicActive(active) {
  micActive = active;
  if (active) {
    setIndicator(sessionReady ? 'listening' : 'connecting');
    if (onUserSpeech) onUserSpeech('');
  } else {
    setIndicator(sessionReady ? 'idle' : 'connecting');
  }
}

export async function connectVoice(opts = {}) {
  onNavigate = opts.onNavigate || null;
  onExitViewer = opts.onExitViewer || null;
  onIndicatorChange = opts.onIndicatorChange || null;
  onUserSpeech = opts.onUserSpeech || null;

  if (!micStream) {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: MIC_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      console.error('[VOICE] Mic denied:', e);
      return;
    }
  }

  if (!audioCtx) {
    audioCtx = new AudioContext({ sampleRate: MIC_RATE });
    await audioCtx.audioWorklet.addModule('/pcm-processor.js');
  }
  if (workletNode) try { workletNode.disconnect(); } catch {}
  if (micSource) try { micSource.disconnect(); } catch {}
  micSource = audioCtx.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioCtx, 'pcm-processor');
  micSource.connect(workletNode);
  workletNode.connect(audioCtx.destination);

  setIndicator('connecting');
  let signedUrl;
  try {
    const res = await fetch('/api/signed-url');
    const data = await res.json();
    signedUrl = data.signed_url;
  } catch (e) {
    console.error('[VOICE] Signed URL fetch failed:', e);
    setTimeout(() => connectVoice(opts), 3000);
    return;
  }

  ws = new WebSocket(signedUrl);
  audioPlayer = new Player(MIC_RATE);

  ws.onopen = () => {
    console.log('[VOICE] Connected');
    ws.send(JSON.stringify({
      type: 'conversation_initiation_client_data',
      conversation_config_override: { agent: { language: 'en' } },
    }));
  };

  ws.onclose = () => {
    console.log('[VOICE] Disconnected');
    sessionReady = false;
    setIndicator('idle');
    setTimeout(() => connectVoice(opts), 2000);
  };

  ws.onerror = (e) => console.error('[VOICE] Error:', e);

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.type) {
      case 'conversation_initiation_metadata':
        sessionReady = true;
        setIndicator(micActive ? 'listening' : 'idle');
        console.log('[VOICE] Session ready');
        break;

      case 'audio':
        if (msg.audio_event?.audio_base_64) {
          setIndicator('speaking');
          audioPlayer.play(msg.audio_event.audio_base_64);
        }
        break;

      case 'user_transcript':
      case 'agent_response':
        break;

      case 'interruption':
        audioPlayer.reset();
        setIndicator(micActive ? 'listening' : 'idle');
        break;

      case 'ping':
        if (msg.ping_event?.event_id != null)
          ws.send(JSON.stringify({ type: 'pong', event_id: msg.ping_event.event_id }));
        break;

      case 'client_tool_call':
        handleTool(msg.client_tool_call);
        break;
    }
  };

  workletNode.port.onmessage = (e) => {
    if (!micActive || !sessionReady || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ user_audio_chunk: toBase64(new Uint8Array(e.data)) }));
  };
}

export function disconnectVoice() {
  if (ws) { ws.close(); ws = null; }
  if (audioPlayer) { audioPlayer.stop(); audioPlayer = null; }
  sessionReady = false;
}

export function resetAgent() {
  micActive = false;
  if (audioPlayer) audioPlayer.reset();
  setIndicator('idle');
}

// ── Tool execution ────────────────────────────────────────────────────

function handleTool(call) {
  if (!call) return;
  const { tool_name, tool_call_id, parameters } = call;
  let result = '';

  switch (tool_name) {
    case 'navigate_to_moment': {
      const scene = matchScene(parameters?.event_name || '');
      if (scene) {
        result = `NOW SHOWING: "${scene.label}". ${scene.desc}`;
        if (onNavigate) onNavigate(scene.slug, scene.label);
      } else {
        result = 'No matching scene found. Available: The Keanu Dodge, The Kobe Fadeaway, The Roundhouse Kick, The Water Throw.';
      }
      break;
    }

    case 'freeze_last_moment': {
      const scene = nextScene();
      result = `FREEZING NOW: "${scene.label}". ${scene.desc}`;
      if (onNavigate) onNavigate(scene.slug, scene.label);
      break;
    }

    case 'exit_viewer': {
      if (window.freezeframePlayer && onExitViewer) {
        result = 'Going back to the video.';
        onExitViewer();
      } else {
        result = 'Already on the video.';
      }
      break;
    }

    case 'play_boomerang': {
      result = 'Playing boomerang.';
      if (window.freezeframePlayer) window.freezeframePlayer.playBoomerang(2, 18);
      break;
    }

    case 'change_view': {
      const dir = (parameters?.direction || '').toLowerCase();
      const player = window.freezeframePlayer;
      if (!player) { result = 'Not in a freezeframe.'; break; }
      const last = player.totalFrames - 1;
      if (dir.includes('right')) {
        player.setFrame(last);
        result = `Showing rightmost angle — frame ${last + 1}.`;
      } else if (dir.includes('left')) {
        player.setFrame(0);
        result = `Showing leftmost angle — frame 1.`;
      } else if (dir.includes('center') || dir.includes('middle')) {
        player.setFrame(Math.floor(last / 2));
        result = `Showing center angle — frame ${Math.floor(last / 2) + 1}.`;
      } else {
        result = `Unknown direction "${dir}". Use left, right, or center.`;
      }
      break;
    }

    case 'describe_moment':
    case 'explain_moment': {
      if (window.freezeframePlayer && currentSceneLabel) {
        const sceneInfo = SCENES.find(s => s.label === currentSceneLabel);
        const desc = sceneInfo ? sceneInfo.desc : '';
        result = `THE SCENE ON SCREEN RIGHT NOW IS: "${currentSceneLabel}". ${desc} Frame ${viewerFrame+1} of ${viewerTotal}. 5 real cameras + 16 AI-generated angles. DO NOT name any other scene — this is what the user sees.`;
      } else {
        result = `User is watching live video feeds, NOT in a freezeframe. Suggest they say "show me the keanu dodge" or name another scene to enter bullet-time.`;
      }
      break;
    }

    default:
      result = `Unknown tool: ${tool_name}`;
  }

  ws.send(JSON.stringify({ type: 'client_tool_result', tool_call_id, result, is_error: false }));
}
