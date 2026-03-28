import * as THREE from 'three';
import { ImageStripPlayer } from './image-strip-player.js';
import { connectVoice } from './gemini_live.js';

const MANIFEST_PATH = '/manifest.json';

// ── Screen references ─────────────────────────────────────────────────

const landing    = document.getElementById('landing');
const agentView  = document.getElementById('agent-view');
const canvas     = document.getElementById('viewport');
const hud        = document.getElementById('viewer-hud');
const fileInput  = document.getElementById('file-input');
const uploadZone = document.getElementById('upload-zone');
const agentCircle = document.getElementById('agent-circle');

// ── Upload ────────────────────────────────────────────────────────────

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) showAgentView(fileInput.files);
});

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag-over');
});

uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  if (e.dataTransfer.files.length > 0) showAgentView(e.dataTransfer.files);
});

// ── Agent View ────────────────────────────────────────────────────────

function showAgentView(files) {
  // Fade out landing
  landing.classList.add('hidden');
  setTimeout(() => { landing.style.display = 'none'; }, 600);

  // Show agent view
  agentView.classList.add('visible');

  // Populate thumbnails
  const count = Math.min(files.length, 5);
  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    const label = thumb.querySelector('.thumb-label');

    if (i < count) {
      // Show filename (trimmed) as label
      const name = files[i].name.replace(/\.[^.]+$/, '');
      label.textContent = name.length > 8 ? 'CAM ' + (i + 1) : name;

      // Staggered entrance
      setTimeout(() => thumb.classList.add('visible'), 200 + i * 120);
    }
  }

  // Tap agent circle to trigger merge (placeholder — Phase 3 will use voice)
  agentCircle.addEventListener('click', triggerMerge, { once: true });
}

// ── Merge → Viewer ────────────────────────────────────────────────────

function triggerMerge() {
  // Animate all visible thumbnails into center
  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    if (thumb.classList.contains('visible')) {
      thumb.classList.add('merging');
    }
  }

  // Agent circle absorb pulse
  agentCircle.classList.add('merging');

  // Transition to viewer after animation completes
  setTimeout(() => {
    agentView.classList.add('hidden');
    setTimeout(() => {
      agentView.style.display = 'none';
      initViewer();
    }, 600);
  }, 900);
}

// Expose for Phase 3 voice trigger
window.triggerMerge = triggerMerge;

// ── Viewer ────────────────────────────────────────────────────────────

async function initViewer() {
  canvas.classList.add('visible');
  hud.classList.add('visible');

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x0a0a0f);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0a0f);

  const stripPlayer = new ImageStripPlayer(scene);
  const camera = stripPlayer.createCamera();

  window.freezeframePlayer = stripPlayer;

  let manifest = null;
  try {
    const res = await fetch(MANIFEST_PATH);
    if (res.ok) manifest = await res.json();
  } catch {}

  if (manifest && manifest.frames) {
    const baseDir = manifest.baseDir || '/bullet-time/';
    const urls = manifest.frames.map(f => baseDir + f);
    await stripPlayer.loadImages(urls);
    stripPlayer.bindDrag(canvas);
  }

  window.addEventListener('keydown', (e) => {
    switch (e.code) {
      case 'ArrowLeft':  e.preventDefault(); stripPlayer.stepFrame(-1); break;
      case 'ArrowRight': e.preventDefault(); stripPlayer.stepFrame(1);  break;
      case 'Home':       e.preventDefault(); stripPlayer.setFrame(0);   break;
      case 'End':        e.preventDefault(); stripPlayer.setFrame(stripPlayer.totalFrames - 1); break;
    }
  });

  window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  renderer.setAnimationLoop(() => {
    renderer.render(scene, camera);
  });

  // Start voice connection
  connectVoice().catch(err => console.error('[VOICE] connectVoice failed:', err));
}

// ── Agent / Listening Indicator State ────────────────────────────────

/**
 * Set state on both the agent circle and the viewer HUD indicator.
 * @param {'idle'|'listening'|'speaking'} state
 */
export function setIndicatorState(state) {
  agentCircle.dataset.state = state;
  const hud = document.getElementById('listening-indicator');
  if (hud) hud.dataset.state = state;
}

window.setIndicatorState = setIndicatorState;
