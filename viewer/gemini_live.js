/**
 * gemini_live.js — Gemini Live API client (connects to server/gemini_proxy.py)
 *
 * Establishes a WebSocket to the local proxy, handles function_call responses
 * from Gemini, and executes them against window.replayAPI (from viewer.js).
 *
 * Mia: implement the audio I/O and Gemini Live protocol here.
 */

const PROXY_URL = "ws://localhost:8765";
const voiceDot = document.getElementById("voice-dot");
const voiceLabel = document.getElementById("voice-label");

let ws = null;
let reconnectTimer = null;

function updateVoiceStatus(status, label) {
    voiceDot.className = status;
    voiceLabel.textContent = `Voice: ${label}`;
}

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    try {
        ws = new WebSocket(PROXY_URL);
    } catch (e) {
        updateVoiceStatus("error", "failed to connect");
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        updateVoiceStatus("connected", "connected");
        console.log("[GEMINI] Connected to proxy");

        // Send initial handshake
        ws.send(JSON.stringify({
            type: "init",
            tools: Object.keys(window.replayAPI),
        }));
    };

    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            console.warn("[GEMINI] Non-JSON message:", event.data);
            return;
        }

        console.log("[GEMINI] Proxy → Browser:", data);

        if (data.type === "function_call") {
            handleFunctionCall(data);
        } else if (data.type === "status") {
            console.log("[GEMINI] Status:", data.message);
        }
    };

    ws.onclose = () => {
        updateVoiceStatus("", "disconnected");
        console.log("[GEMINI] Disconnected from proxy");
        scheduleReconnect();
    };

    ws.onerror = (err) => {
        updateVoiceStatus("error", "connection error");
        console.error("[GEMINI] WebSocket error:", err);
    };
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        updateVoiceStatus("", "reconnecting...");
        connect();
    }, 3000);
}

function handleFunctionCall(data) {
    /**
     * Handle a function_call from Gemini Live.
     *
     * data.name:   function name (e.g., "orbit_camera")
     * data.args:   function arguments (e.g., { azimuth: 90, elevation: 30 })
     * data.call_id: unique call ID to return result
     */
    const fn = window.replayAPI[toCamelCase(data.name)];
    if (!fn) {
        console.warn(`[GEMINI] Unknown function: ${data.name}`);
        sendResult(data.call_id, { error: `Unknown function: ${data.name}` });
        return;
    }

    try {
        const args = data.args || {};
        const result = fn(...Object.values(args));
        console.log(`[GEMINI] ${data.name}(${JSON.stringify(args)}) → ${JSON.stringify(result)}`);
        sendResult(data.call_id, result);
    } catch (e) {
        console.error(`[GEMINI] Error executing ${data.name}:`, e);
        sendResult(data.call_id, { error: e.message });
    }
}

function sendResult(callId, result) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
        type: "function_result",
        call_id: callId,
        result: result,
    }));
}

function toCamelCase(snake) {
    return snake.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

// ============================================================
// AUDIO I/O (TODO: Mia)
// ============================================================

/**
 * TODO Mia: Implement audio capture and playback for Gemini Live.
 *
 * 1. Request microphone access (navigator.mediaDevices.getUserMedia)
 * 2. Capture audio as 16-bit PCM at 16kHz
 * 3. Send audio chunks to proxy via WebSocket
 * 4. Receive audio responses from Gemini via proxy
 * 5. Play audio responses through Web Audio API (24kHz PCM)
 */

// ============================================================
// INIT
// ============================================================

connect();
