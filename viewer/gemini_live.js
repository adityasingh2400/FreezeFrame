/**
 * gemini_live.js — Gemini Live API client
 * Connects to server/gemini_proxy.py via WebSocket.
 * Captures microphone audio, sends to proxy, plays back Gemini's audio responses.
 * Handles function_call messages by executing them against window.replayAPI.
 */

const PROXY_URL = "ws://localhost:8765";
const SAMPLE_RATE_OUT = 16000;  // Send 16kHz to Gemini
const SAMPLE_RATE_IN  = 24000;  // Gemini responds at 24kHz

const voiceDot   = document.getElementById("voice-dot");
const voiceLabel = document.getElementById("voice-label");

let ws = null;
let reconnectTimer = null;
let audioContext = null;
let micStream = null;
let processor = null;
let audioQueue = [];
let isPlayingAudio = false;

// ─── Status UI ────────────────────────────────────────────────────────────────

function setStatus(cls, text) {
    voiceDot.className = cls;
    voiceLabel.textContent = `Voice: ${text}`;
}

// ─── WebSocket ────────────────────────────────────────────────────────────────

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    try { ws = new WebSocket(PROXY_URL); }
    catch (e) { setStatus("error", "failed"); scheduleReconnect(); return; }

    ws.onopen = () => {
        setStatus("connected", "connected — click to speak");
        console.log("[GEMINI] Connected");
        ws.send(JSON.stringify({ type: "init" }));
        startMic();
    };

    ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data); }
        catch { return; }

        if (data.type === "function_call")  handleFunctionCall(data);
        if (data.type === "audio")          handleAudioResponse(data.data);
        if (data.type === "transcript")     console.log("[GEMINI]", data.text);
        if (data.type === "status")         console.log("[PROXY]", data.message);
        if (data.type === "error")          console.error("[PROXY]", data.message);
    };

    ws.onclose = () => {
        setStatus("", "disconnected");
        stopMic();
        scheduleReconnect();
    };

    ws.onerror = () => setStatus("error", "error");
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        setStatus("", "reconnecting...");
        connect();
    }, 3000);
}

// ─── Function Call Handler ────────────────────────────────────────────────────

function toCamelCase(s) {
    return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function handleFunctionCall(data) {
    const fn = window.replayAPI?.[toCamelCase(data.name)];
    if (!fn) {
        sendResult(data.call_id, { error: `Unknown function: ${data.name}` });
        return;
    }
    try {
        const args = data.args || {};
        const result = fn(...Object.values(args));
        console.log(`[GEMINI] ${data.name}(${JSON.stringify(args)}) →`, result);
        sendResult(data.call_id, result);
    } catch (e) {
        sendResult(data.call_id, { error: e.message });
    }
}

function sendResult(callId, result) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "function_result", call_id: callId, result }));
}

// ─── Microphone Capture ───────────────────────────────────────────────────────

async function startMic() {
    try {
        if (!audioContext) {
            audioContext = new AudioContext({ sampleRate: SAMPLE_RATE_OUT });
        }
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

        const source = audioContext.createMediaStreamSource(micStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (e) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            const samples = e.inputBuffer.getChannelData(0);
            const pcm16 = float32ToPCM16(samples);
            const b64 = arrayBufferToBase64(pcm16.buffer);
            ws.send(JSON.stringify({ type: "audio", data: b64 }));
        };

        source.connect(processor);
        processor.connect(audioContext.destination);
        setStatus("listening", "listening...");
        console.log("[MIC] Started");
    } catch (err) {
        console.warn("[MIC] Could not start:", err.message);
        setStatus("error", "mic denied");
    }
}

function stopMic() {
    if (processor) { processor.disconnect(); processor = null; }
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
}

function float32ToPCM16(float32Array) {
    const out = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let bin = "";
    for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}

// ─── Audio Playback ───────────────────────────────────────────────────────────

function handleAudioResponse(b64data) {
    const bytes = base64ToArrayBuffer(b64data);
    const samples = pcm16ToFloat32(bytes);
    audioQueue.push(samples);
    if (!isPlayingAudio) drainAudioQueue();
}

async function drainAudioQueue() {
    if (audioQueue.length === 0) { isPlayingAudio = false; return; }
    isPlayingAudio = true;

    if (!audioContext) audioContext = new AudioContext({ sampleRate: SAMPLE_RATE_IN });
    if (audioContext.sampleRate !== SAMPLE_RATE_IN) {
        // best effort — create separate context for playback if rates differ
    }

    const samples = audioQueue.shift();
    const buffer = audioContext.createBuffer(1, samples.length, SAMPLE_RATE_IN);
    buffer.copyToChannel(samples, 0);

    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.onended = drainAudioQueue;
    source.start();
}

function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
}

function pcm16ToFloat32(bytes) {
    const int16 = new Int16Array(bytes.buffer);
    const out = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        out[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff);
    }
    return out;
}

// ─── Init ─────────────────────────────────────────────────────────────────────

connect();
