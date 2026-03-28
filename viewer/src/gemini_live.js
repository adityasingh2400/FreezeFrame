/**
 * Gemini Live voice integration for Freezeframe viewer.
 *
 * - Connects to the Python proxy over WebSocket
 * - Streams mic audio (16kHz PCM via AudioWorklet) to Gemini Live
 * - Plays back Gemini audio responses (24kHz PCM)
 * - Handles navigate tool: snaps viewer to frame + plays boomerang loop
 * - Updates transcript overlay and indicator state
 */

const PROXY_URL   = 'ws://localhost:8765';
const MIC_RATE    = 16000;
const OUTPUT_RATE = 24000;

// ── Debug console ─────────────────────────────────────────────────────

function debugLog(text, type = 'sys') {
  const log = document.getElementById('debug-log');
  if (!log) return;
  const line = document.createElement('div');
  line.className = `debug-line ${type}`;
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
  // Keep max 60 lines
  while (log.children.length > 60) log.removeChild(log.firstChild);
}

// Input transcription via Web Speech API
function startSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  const rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = 'en-US';
  let lastFinal = '';
  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) {
        if (t !== lastFinal) { debugLog(t, 'you'); setTranscript('you', t); lastFinal = t; }
      } else interim = t;
    }
    if (interim) {
      setTranscript('you', interim);
      const last = document.querySelector('#debug-log .you:last-child');
      if (last && last.dataset.interim) last.textContent = interim;
      else { const el = document.createElement('div'); el.className = 'debug-line you'; el.dataset.interim = '1'; el.textContent = interim; document.getElementById('debug-log')?.appendChild(el); }
    }
  };
  rec.onend = () => setTimeout(() => rec.start(), 300);
  rec.start();
}

// ── Overlay helpers ────────────────────────────────────────────────────

const overlayEl   = () => document.getElementById('viewer-overlay-text');
const indicatorEl = () => document.getElementById('listening-indicator');

let _youTimer = null;
let _aiTimer  = null;

function setTranscript(who, text) {
  const row  = document.getElementById(`transcript-${who}`);
  const span = document.getElementById(`transcript-${who}-text`);
  if (!row || !span) return;
  span.textContent = text;
  row.classList.toggle('visible', !!text);

  // Auto-hide YOU after 4s, GEMINI after 6s
  const timer = who === 'you' ? '_youTimer' : '_aiTimer';
  if (window[timer]) clearTimeout(window[timer]);
  if (text) {
    const delay = who === 'you' ? 4000 : 6000;
    window[timer] = setTimeout(() => {
      row.classList.remove('visible');
    }, delay);
  }
}

function setOverlay(text, mode = 'output') {
  const el = overlayEl();
  if (!el) return;
  el.textContent = text;
  el.dataset.mode = mode;
  el.classList.toggle('visible', !!text);
}

function setIndicator(state) {
  const el = indicatorEl();
  if (el) el.dataset.state = state;
  if (window.setIndicatorState) window.setIndicatorState(state);
}

// ── Boomerang animation ────────────────────────────────────────────────

let _boomerangRaf = null;

function playBoomerang(player, centerFrame, halfSwing = 6, fps = 18) {
  if (_boomerangRaf) cancelAnimationFrame(_boomerangRaf);

  const total = player.totalFrames;
  const lo    = Math.max(0, centerFrame - halfSwing);
  const hi    = Math.min(total - 1, centerFrame + halfSwing);

  // Build forward + reverse sequence
  const forward  = [];
  for (let f = centerFrame; f <= hi; f++) forward.push(f);
  const backward = [...forward].reverse();
  const sequence = [...forward, ...backward];

  let idx       = 0;
  let lastTime  = null;
  const delay   = 1000 / fps;

  function step(ts) {
    if (lastTime === null) lastTime = ts;
    if (ts - lastTime >= delay) {
      player.setFrame(sequence[idx % sequence.length]);
      idx++;
      lastTime = ts;
    }
    // Loop 2.5 full boomerangs then stop
    if (idx < sequence.length * 2.5) {
      _boomerangRaf = requestAnimationFrame(step);
    } else {
      player.setFrame(centerFrame);
      _boomerangRaf = null;
    }
  }

  _boomerangRaf = requestAnimationFrame(step);
}

// ── Audio playback queue ──────────────────────────────────────────────

class AudioPlayer {
  constructor(sampleRate = OUTPUT_RATE) {
    this._ctx    = null;
    this._rate   = sampleRate;
    this._queue  = [];
    this._playing = false;
    this._nextAt = 0;
  }

  _ensureCtx() {
    if (!this._ctx) this._ctx = new AudioContext({ sampleRate: this._rate });
    if (this._ctx.state === 'suspended') this._ctx.resume();
  }

  enqueue(int16Buffer) {
    this._ensureCtx();
    const int16   = new Int16Array(int16Buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff);
    }

    const audioBuffer = this._ctx.createBuffer(1, float32.length, this._rate);
    audioBuffer.copyToChannel(float32, 0);

    const source = this._ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this._ctx.destination);

    const now = this._ctx.currentTime;
    if (this._nextAt < now) this._nextAt = now;
    source.start(this._nextAt);
    this._nextAt += audioBuffer.duration;
  }

  reset() {
    this._nextAt = 0;
  }
}

// ── Main connect function ─────────────────────────────────────────────

export async function connectVoice() {
  const player = window.freezeframePlayer;

  // ── Mic setup via AudioWorklet ──────────────────────────────────────
  let micStream;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: MIC_RATE, channelCount: 1, echoCancellation: true },
    });
  } catch (err) {
    console.error('[VOICE] Mic permission denied:', err);
    setOverlay('Microphone access denied', 'error');
    return;
  }

  const audioCtx = new AudioContext({ sampleRate: MIC_RATE });
  await audioCtx.audioWorklet.addModule('/pcm-processor.js');

  const micSource    = audioCtx.createMediaStreamSource(micStream);
  const workletNode  = new AudioWorkletNode(audioCtx, 'pcm-processor');
  micSource.connect(workletNode);
  workletNode.connect(audioCtx.destination); // needed on some browsers

  // ── WebSocket to proxy ──────────────────────────────────────────────
  const ws       = new WebSocket(PROXY_URL);
  const audioOut = new AudioPlayer(OUTPUT_RATE);

  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    console.log('[VOICE] WebSocket open');
    window._voiceWs = ws;
    ws.send(JSON.stringify({ type: 'init' }));
    setIndicator('listening');
    setOverlay('');
    debugLog('Connected to Gemini Live', 'sys');
    startSpeechRecognition();
  };

  ws.onclose = () => {
    console.log('[VOICE] WebSocket closed');
    debugLog('Disconnected', 'sys');
    setIndicator('idle');
    workletNode.disconnect();
    micSource.disconnect();
    micStream.getTracks().forEach(t => t.stop());
  };

  ws.onerror = (err) => {
    console.error('[VOICE] WebSocket error:', err);
    debugLog('Connection error', 'sys');
    setOverlay('Voice connection failed', 'error');
    setIndicator('idle');
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.type) {

      case 'audio_out': {
        const binary  = atob(msg.data);
        const bytes   = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        setIndicator('speaking');
        audioOut.enqueue(bytes.buffer);
        break;
      }

      case 'turn_complete': {
        setIndicator('listening');
        break;
      }

      case 'input_transcript': {
        if (msg.text) { setOverlay(msg.text, 'input'); debugLog(msg.text, 'you'); }
        break;
      }

      case 'output_transcript': {
        if (msg.text) {
          setOverlay(msg.text, 'output');
          setTranscript('ai', msg.text);
          debugLog(msg.text, 'ai');
        }
        break;
      }

      case 'navigate': {
        const frame = msg.frame;
        const label = msg.label || '';
        debugLog(`navigate → ${label} (frame ${frame})`, 'tool');
        console.log(`[VOICE] Navigate → frame ${frame} (${label})`);

        if (player && typeof frame === 'number') {
          player.setFrame(frame);
          playBoomerang(player, frame);
        }
        if (label) setOverlay(label, 'navigate');
        break;
      }

      case 'zoom': {
        debugLog(`zoom ${msg.action}`, 'tool');
        const cam = window.freezeframeCamera;
        if (!cam) break;
        const step = 0.3;
        if (msg.action === 'in')    cam.zoom = Math.min(cam.zoom + step, 5);
        if (msg.action === 'out')   cam.zoom = Math.max(cam.zoom - step, 0.3);
        if (msg.action === 'reset') cam.zoom = 1;
        cam.updateProjectionMatrix();
        break;
      }

      case 'tool_ack': {
        debugLog(msg.tool, 'tool');
        break;
      }

      case 'error': {
        console.error('[VOICE] Proxy error:', msg.message);
        setOverlay(msg.message, 'error');
        break;
      }
    }
  };

  // ── Forward mic PCM to WebSocket ────────────────────────────────────
  workletNode.port.onmessage = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;

    const int16  = new Int16Array(e.data);
    const bytes  = new Uint8Array(int16.buffer);
    let b64 = '';
    for (let i = 0; i < bytes.length; i++) b64 += String.fromCharCode(bytes[i]);
    b64 = btoa(b64);
    ws.send(JSON.stringify({ type: 'audio_in', data: b64 }));
  };

  return ws;
}
