/**
 * gemini_live.js — Gemini Live client for bullet-time interaction.
 *
 * Connects to server/gemini_proxy.py via WebSocket.
 * Handles: text I/O with Gemini Live, tool result notifications,
 * and viewer commands (load strip, show moment, etc.)
 */

const PROXY_URL = "ws://localhost:8765";

let ws = null;
let reconnectTimer = null;

// ── UI Elements ──────────────────────────────────────────────────────

const chatContainer = document.getElementById('gemini-chat');
const chatMessages = document.getElementById('gemini-messages');
const chatInput = document.getElementById('gemini-input');
const chatSend = document.getElementById('gemini-send');
const statusDot = document.getElementById('gemini-status-dot');
const statusLabel = document.getElementById('gemini-status-label');

function updateStatus(state, label) {
  if (statusDot) {
    statusDot.className = `gemini-dot ${state}`;
  }
  if (statusLabel) {
    statusLabel.textContent = label;
  }
}

function appendMessage(role, text) {
  if (!chatMessages) return;
  const msg = document.createElement('div');
  msg.className = `gemini-msg gemini-msg-${role}`;
  msg.textContent = text;
  chatMessages.appendChild(msg);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendStatus(text) {
  if (!chatMessages) return;
  const msg = document.createElement('div');
  msg.className = 'gemini-msg gemini-msg-status';
  msg.textContent = text;
  chatMessages.appendChild(msg);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ── WebSocket Connection ─────────────────────────────────────────────

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  try {
    ws = new WebSocket(PROXY_URL);
  } catch (e) {
    updateStatus('error', 'Failed');
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    updateStatus('connected', 'Connected');
    console.log("[GEMINI] Connected to proxy");

    // Send init handshake
    ws.send(JSON.stringify({ type: "init" }));
  };

  ws.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      console.warn("[GEMINI] Non-JSON message:", event.data);
      return;
    }

    handleMessage(data);
  };

  ws.onclose = () => {
    updateStatus('disconnected', 'Disconnected');
    console.log("[GEMINI] Disconnected");
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    updateStatus('error', 'Error');
    console.error("[GEMINI] WebSocket error:", err);
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    updateStatus('disconnected', 'Reconnecting...');
    connect();
  }, 3000);
}

// ── Message Handling ─────────────────────────────────────────────────

function handleMessage(data) {
  console.log("[GEMINI] Received:", data.type);

  switch (data.type) {
    case 'text':
      // Gemini's text response
      appendMessage('assistant', data.text);
      break;

    case 'status':
      appendStatus(data.message);
      break;

    case 'tool_status':
      if (data.tool === 'build_bullet_time_strip') {
        appendStatus('Generating bullet-time strip...');
        updateStatus('working', 'Generating...');
      } else if (data.tool === 'find_moment') {
        appendStatus('Finding moment...');
      }
      break;

    case 'tool_result':
      handleToolResult(data.tool, data.result);
      break;

    case 'error':
      appendMessage('error', `Error: ${data.message}`);
      break;
  }
}

function handleToolResult(tool, result) {
  if (tool === 'find_moment') {
    if (result.error) {
      appendStatus(`Could not find moment: ${result.error}`);
    } else {
      appendStatus(
        `Found: "${result.label}" at ${result.timestamp_sec.toFixed(1)}s (frame ${result.frame_number})`
      );
    }
  }

  if (tool === 'build_bullet_time_strip') {
    updateStatus('connected', 'Connected');
    if (result.error) {
      appendStatus(`Strip generation failed: ${result.error}`);
    } else {
      appendStatus(
        `Strip ready: ${result.total_frames} frames (${result.real_frames} real + ${result.synthetic_frames} synthetic)`
      );
    }
  }

  if (tool === 'show_strip') {
    // Reload the viewer to pick up the new manifest
    appendStatus('Loading strip in viewer...');
    setTimeout(() => {
      window.location.reload();
    }, 500);
  }
}

// ── Send User Input ──────────────────────────────────────────────────

function sendText(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    appendMessage('error', 'Not connected to Gemini');
    return;
  }
  if (!text.trim()) return;

  appendMessage('user', text);
  ws.send(JSON.stringify({ type: "text", text: text }));
}

// ── UI Event Binding ─────────────────────────────────────────────────

if (chatSend) {
  chatSend.addEventListener('click', () => {
    if (chatInput) {
      sendText(chatInput.value);
      chatInput.value = '';
    }
  });
}

if (chatInput) {
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendText(chatInput.value);
      chatInput.value = '';
    }
  });
}

// ── Init ─────────────────────────────────────────────────────────────

connect();
