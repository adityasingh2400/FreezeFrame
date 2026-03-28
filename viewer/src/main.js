import * as THREE from 'three';
import { ImageStripPlayer } from './image-strip-player.js';

const MANIFEST_PATH = '/manifest.json';

// ── Screen references ─────────────────────────────────────────────────

const landing    = document.getElementById('landing');
const processing = document.getElementById('processing');
const canvas     = document.getElementById('viewport');
const hud        = document.getElementById('viewer-hud');
const fileInput  = document.getElementById('file-input');
const uploadZone = document.getElementById('upload-zone');

// ── Upload ────────────────────────────────────────────────────────────

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) startProcessing();
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
  if (e.dataTransfer.files.length > 0) startProcessing();
});

// ── Fake Processing Pipeline ──────────────────────────────────────────

const STEPS = ['step-0', 'step-1', 'step-2', 'step-3'];
const STEP_DELAYS = [0, 900, 1900, 3100];
const DONE_DELAYS = [800, 1800, 3000, 3600];
const TRANSITION_DELAY = 4000;

function startProcessing() {
  landing.classList.add('hidden');
  setTimeout(() => { landing.style.display = 'none'; }, 600);

  processing.classList.add('visible');

  STEPS.forEach((id, i) => {
    const el = document.getElementById(id);
    setTimeout(() => { el.classList.add('active'); }, STEP_DELAYS[i]);
    setTimeout(() => {
      el.classList.remove('active');
      el.classList.add('done');
      if (i === STEPS.length - 1) el.classList.add('final');
    }, DONE_DELAYS[i]);
  });

  setTimeout(() => {
    processing.classList.add('hidden');
    setTimeout(() => {
      processing.style.display = 'none';
      initViewer();
    }, 500);
  }, TRANSITION_DELAY);
}

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

  // Expose for Phase 3 voice integration
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
}

// ── Listening Indicator ───────────────────────────────────────────────

const indicator = document.getElementById('listening-indicator');

/**
 * Set the listening indicator state.
 * @param {'idle'|'listening'|'speaking'} state
 */
export function setIndicatorState(state) {
  if (indicator) indicator.dataset.state = state;
}

// Expose for Phase 3 voice integration
window.setIndicatorState = setIndicatorState;
