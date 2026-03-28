/**
 * Gemini Live voice integration for Freezeframe viewer.
 *
 * Architecture:
 *   Browser mic → AudioWorklet (16kHz Int16 PCM, 32ms chunks)
 *     → WebSocket → Python proxy → Gemini Live API
 *     → audio response + tool calls → proxy → browser
 *
 * Optimizations:
 *   - Batch base64 encoding via lookup table (no char-at-a-time loop)
 *   - 32ms audio chunks (was 100ms) for faster VAD response
 *   - Readiness handshake: mic audio held until proxy confirms Gemini session open
 *   - Auto-reconnection with exponential backoff
 *   - Structured command routing for all viewer actions
 */

const PROXY_URL       = 'ws://localhost:8765';
const MIC_RATE        = 16000;
const OUTPUT_RATE     = 24000;
const RECONNECT_BASE  = 1000;
const RECONNECT_MAX   = 16000;

// ── Fast base64 encode ──────────────────────────────────────────────────

const _b64Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function uint8ToBase64(bytes) {
  let result = '';
  const len = bytes.length;
  const rem = len % 3;
  const end = len - rem;
  for (let i = 0; i < end; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    result += _b64Chars[(n >> 18) & 63] + _b64Chars[(n >> 12) & 63] +
              _b64Chars[(n >> 6) & 63]  + _b64Chars[n & 63];
  }
  if (rem === 1) {
    const n = bytes[end];
    result += _b64Chars[n >> 2] + _b64Chars[(n << 4) & 63] + '==';
  } else if (rem === 2) {
    const n = (bytes[end] << 8) | bytes[end + 1];
    result += _b64Chars[n >> 10] + _b64Chars[(n >> 4) & 63] + _b64Chars[(n << 2) & 63] + '=';
  }
  return result;
}

// ── Debug console ─────────────────────────────────────────────────────

function debugLog(text, type = 'sys') {
  const log = document.getElementById('debug-log');
  if (!log) return;
  const line = document.createElement('div');
  line.className = `debug-line ${type}`;
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
  while (log.children.length > 60) log.removeChild(log.firstChild);
}

// ── Input transcription via Web Speech API ────────────────────────────

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
      else {
        const el = document.createElement('div');
        el.className = 'debug-line you';
        el.dataset.interim = '1';
        el.textContent = interim;
        document.getElementById('debug-log')?.appendChild(el);
      }
    }
  };
  rec.onend = () => setTimeout(() => rec.start(), 300);
  rec.start();
}

// ── Overlay helpers ────────────────────────────────────────────────────

const overlayEl   = () => document.getElementById('viewer-overlay-text');
const indicatorEl = () => document.getElementById('listening-indicator');

function setTranscript(who, text) {
  const row  = document.getElementById(`transcript-${who}`);
  const span = document.getElementById(`transcript-${who}-text`);
  if (!row || !span) return;
  span.textContent = text;
  row.classList.toggle('visible', !!text);

  const timerKey = `_${who}Timer`;
  if (window[timerKey]) clearTimeout(window[timerKey]);
  if (text) {
    const delay = who === 'you' ? 4000 : 6000;
    window[timerKey] = setTimeout(() => row.classList.remove('visible'), delay);
  }
}

function setOverlay(text, mode = 'output') {
  const el = overlayEl();
  if (!el) return;
  el.textContent = text;
  el.dataset.mode = mode;
  el.classList.toggle('visible', !!text);
}

// ── Audio playback queue ──────────────────────────────────────────────

class AudioPlayer {
  constructor(sampleRate = OUTPUT_RATE) {
    this._ctx    = null;
    this._rate   = sampleRate;
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

// ── Module state ──────────────────────────────────────────────────────

let _ws              = null;
let _sessionReady    = false;
let _reconnectDelay  = RECONNECT_BASE;
let _intentionalClose = false;
let _micStream       = null;
let _audioCtx        = null;
let _workletNode     = null;
let _micSource       = null;
let _speechRecStarted = false;

// Callbacks from main.js
let _onNavigate        = null;
let _onIndicatorChange = null;
let _onUserSpeech      = null;

function setIndicator(state) {
  const el = indicatorEl();
  if (el) el.dataset.state = state;
  if (_onIndicatorChange) _onIndicatorChange(state);
  if (window.setIndicatorState) window.setIndicatorState(state);
}

// ── Public API ────────────────────────────────────────────────────────

export function isConnected() {
  return _ws !== null && _ws.readyState === WebSocket.OPEN && _sessionReady;
}

export function sendText(text) {
  if (!isConnected()) return;
  _ws.send(JSON.stringify({ type: 'text_in', text }));
  debugLog(text, 'you');
}

/**
 * Connect to the voice proxy. Options:
 *   onNavigate(slug, label) — called when Gemini navigates to a moment
 *   onIndicatorChange(state) — called when indicator state changes
 */
export async function connectVoice(opts = {}) {
  _onNavigate = opts.onNavigate || null;
  _onIndicatorChange = opts.onIndicatorChange || null;
  _onUserSpeech = opts.onUserSpeech || null;

  // Acquire mic once, reuse across reconnects
  if (!_micStream) {
    try {
      _micStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: MIC_RATE, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err) {
      console.error('[VOICE] Mic permission denied:', err);
      setOverlay('Microphone access denied', 'error');
      return;
    }
  }

  if (!_audioCtx) {
    _audioCtx = new AudioContext({ sampleRate: MIC_RATE });
    await _audioCtx.audioWorklet.addModule('/pcm-processor.js');
  }

  // Disconnect old nodes if reconnecting
  if (_workletNode) { try { _workletNode.disconnect(); } catch {} }
  if (_micSource)   { try { _micSource.disconnect(); } catch {} }

  _micSource   = _audioCtx.createMediaStreamSource(_micStream);
  _workletNode = new AudioWorkletNode(_audioCtx, 'pcm-processor');
  _micSource.connect(_workletNode);
  _workletNode.connect(_audioCtx.destination);

  _sessionReady = false;
  _intentionalClose = false;

  const ws       = new WebSocket(PROXY_URL);
  const audioOut = new AudioPlayer(OUTPUT_RATE);

  ws.binaryType = 'arraybuffer';
  _ws = ws;

  ws.onopen = () => {
    console.log('[VOICE] WebSocket open');
    window._voiceWs = ws;
    ws.send(JSON.stringify({ type: 'init' }));
    setIndicator('connecting');
    setOverlay('');
    debugLog('Connecting to Gemini Live...', 'sys');
    _reconnectDelay = RECONNECT_BASE;
  };

  ws.onclose = () => {
    console.log('[VOICE] WebSocket closed');
    debugLog('Disconnected', 'sys');
    setIndicator('idle');
    _sessionReady = false;

    if (!_intentionalClose) {
      debugLog(`Reconnecting in ${_reconnectDelay / 1000}s...`, 'sys');
      setTimeout(() => connectVoice(opts), _reconnectDelay);
      _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX);
    }
  };

  ws.onerror = (err) => {
    console.error('[VOICE] WebSocket error:', err);
    debugLog('Connection error', 'sys');
    setOverlay('Voice connection failed — retrying', 'error');
    setIndicator('idle');
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.type) {

      case 'session_ready': {
        _sessionReady = true;
        setIndicator('listening');
        debugLog('Connected to Gemini Live', 'sys');
        setOverlay('');
        if (!_speechRecStarted) {
          startSpeechRecognition();
          _speechRecStarted = true;
        }
        break;
      }

      case 'audio_out': {
        const binary = atob(msg.data);
        const bytes  = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        setIndicator('speaking');
        audioOut.enqueue(bytes.buffer);
        break;
      }

      case 'turn_complete': {
        setIndicator('listening');
        audioOut.reset();
        break;
      }

      case 'input_transcript': {
        if (msg.text) {
          setOverlay(msg.text, 'input');
          debugLog(msg.text, 'you');
          if (_onUserSpeech) _onUserSpeech(msg.text);
        }
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

      case 'error': {
        console.error('[VOICE] Proxy error:', msg.message);
        setOverlay(msg.message, 'error');
        break;
      }

      // ── Viewer commands from proxy tool calls ─────────────────────

      case 'navigate': {
        debugLog(`navigate → ${msg.label} (frame ${msg.frame})`, 'tool');
        if (_onNavigate && msg.label) {
          _onNavigate(msg.slug || null, msg.label);
        }
        // If there's a player in the viewer, also set frame directly
        if (window.freezeframePlayer && typeof msg.frame === 'number') {
          window.freezeframePlayer.setFrame(msg.frame);
        }
        if (msg.label) setOverlay(msg.label, 'navigate');
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

      case 'set_frame': {
        debugLog(`set_frame → ${msg.frame}`, 'tool');
        if (window.freezeframePlayer && typeof msg.frame === 'number') {
          window.freezeframePlayer.setFrame(msg.frame);
        }
        break;
      }

      case 'play_orbit': {
        debugLog(`orbit center=${msg.frame}`, 'tool');
        // Orbit is handled by the strip player's boomerang with wider range
        if (window.freezeframePlayer) {
          window.freezeframePlayer.playBoomerang(3, 12);
        }
        break;
      }

      case 'stop_orbit': {
        debugLog('stop_orbit', 'tool');
        if (window.freezeframePlayer) {
          window.freezeframePlayer.stopBoomerang();
        }
        break;
      }

      case 'play_boomerang': {
        debugLog(`boomerang center=${msg.frame}`, 'tool');
        if (window.freezeframePlayer) {
          if (typeof msg.frame === 'number') window.freezeframePlayer.setFrame(msg.frame);
          window.freezeframePlayer.playBoomerang(2, 18);
        }
        break;
      }

      case 'highlight_moment': {
        debugLog(`highlight: ${msg.label}`, 'tool');
        if (msg.label) setOverlay(msg.label, 'navigate');
        if (window.freezeframePlayer && typeof msg.frame === 'number') {
          window.freezeframePlayer.setFrame(msg.frame);
        }
        break;
      }

      case 'step_frame': {
        const dir = msg.direction === 'back' ? -1 : 1;
        const count = msg.count || 1;
        debugLog(`step ${dir > 0 ? 'forward' : 'back'} ${count}`, 'tool');
        if (window.freezeframePlayer) window.freezeframePlayer.stepFrame(dir * count);
        break;
      }

      case 'tool_ack': {
        debugLog(msg.tool, 'tool');
        break;
      }
    }
  };

  // Forward mic PCM to proxy (gated on session readiness)
  _workletNode.port.onmessage = (e) => {
    if (!_sessionReady || ws.readyState !== WebSocket.OPEN) return;
    const bytes = new Uint8Array(e.data);
    const b64   = uint8ToBase64(bytes);
    ws.send(JSON.stringify({ type: 'audio_in', data: b64 }));
  };

  return ws;
}

export function disconnectVoice() {
  _intentionalClose = true;
  if (_ws) {
    _ws.close();
    _ws = null;
  }
  _sessionReady = false;
}
