import * as THREE from 'three';
import { SplatPlayer } from './splat-player.js';
import { ImageStripPlayer } from './image-strip-player.js';
import { CameraController } from './controls.js';
import { Timeline } from './timeline.js';
import { UI } from './ui.js';
import { DirectorMode } from './director.js';

const MANIFEST_PATH = '/manifest.json';
const DEMO_SPLAT = '/demo/nike.splat';

async function fetchManifest() {
  try {
    const res = await fetch(MANIFEST_PATH);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ── Bullet-Time Mode ────────────────────────────────────────────────

async function initBulletTime(manifest, canvas, renderer, ui) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0a0f);

  const stripPlayer = new ImageStripPlayer(scene);
  const camera = stripPlayer.createCamera();

  ui.setSceneName(manifest.moment?.label || 'Bullet Time');
  ui.setLoadingText('Loading bullet-time strip...');

  const baseDir = manifest.baseDir || '/bullet-time/';
  const urls = manifest.frames.map(f => baseDir + f);

  await stripPlayer.loadImages(urls, (loaded, total) => {
    ui.setLoadingProgress(loaded, total);
  });

  stripPlayer.bindDrag(canvas);
  ui.setFrameNames(manifest.frames);
  ui.showBulletTimeMode(manifest.moment, stripPlayer);
  ui.hideLoading();

  // Keyboard
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    switch (e.code) {
      case 'ArrowLeft':
        e.preventDefault();
        stripPlayer.stepFrame(-1);
        break;
      case 'ArrowRight':
        e.preventDefault();
        stripPlayer.stepFrame(1);
        break;
      case 'Home':
        e.preventDefault();
        stripPlayer.setFrame(0);
        break;
      case 'End':
        e.preventDefault();
        stripPlayer.setFrame(stripPlayer.totalFrames - 1);
        break;
    }
  });

  window.addEventListener('resize', () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  renderer.setAnimationLoop(() => {
    renderer.render(scene, camera);
  });

  // Expose for Gemini Live
  window.replayStripPlayer = stripPlayer;
}

// ── Splat Mode (existing) ───────────────────────────────────────────

async function initSplatMode(manifest, canvas, renderer, ui) {
  const scene = new THREE.Scene();

  const bgCanvas = document.createElement('canvas');
  bgCanvas.width = 512;
  bgCanvas.height = 512;
  const ctx = bgCanvas.getContext('2d');
  const grad = ctx.createRadialGradient(256, 256, 0, 256, 256, 360);
  grad.addColorStop(0, '#171112');
  grad.addColorStop(0.6, '#110A0D');
  grad.addColorStop(1, '#0D0809');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 512);
  scene.background = new THREE.CanvasTexture(bgCanvas);

  const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.set(0, 1.2, 3);

  const cameraCtrl = new CameraController(camera, canvas);
  const player = new SplatPlayer(scene);
  const timeline = new Timeline(player);

  let splatCount = 0;

  if (manifest && manifest.frames && manifest.frames.length > 0) {
    const sceneName = manifest.name || manifest.frames[0].split('/').pop().replace(/\.\w+$/, '');
    ui.setSceneName(sceneName);
    ui.setLoadingText('Loading hero frame...');
    const baseDir = manifest.baseDir || '/frames/';
    const urls = manifest.frames.map(f => baseDir + f);
    const heroIdx = manifest.hero_frame || 0;

    splatCount = await player.loadFrames(urls, manifest.fps || 30, (loaded, total) => {
      if (loaded === 1) {
        ui.setSplatCount(splatCount || player.mesh?.numSplats || 0);
        timeline.init();
        ui.hideLoading();
        ui.setLoadingBg(loaded, total);
      } else {
        ui.setLoadingBg(loaded, total);
      }
    }, heroIdx);
  } else {
    ui.setSceneName('nike.splat — demo');
    ui.setLoadingText('Loading demo scene...');
    ui.setLoadingProgress(50, 100);
    splatCount = await player.loadSingle(DEMO_SPLAT);
    ui.setLoadingProgress(100, 100);
  }

  ui.setSplatCount(splatCount);
  timeline.init();
  ui.hideLoading();

  const director = new DirectorMode(camera, cameraCtrl, player);
  director.loadDefault(Math.max(player.totalFrames, 1), player.fps || 30);

  const directorBtn = document.getElementById('director-btn');
  if (directorBtn) {
    directorBtn.addEventListener('click', () => {
      director.toggle();
      ui.setDirectorActive(director.active);
    });
  }

  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  if (prevBtn) prevBtn.addEventListener('click', () => { player.pause(); player.stepFrame(-1); });
  if (nextBtn) nextBtn.addEventListener('click', () => { player.pause(); player.stepFrame(1); });

  canvas.addEventListener('pointerdown', () => {
    cameraCtrl.onUserInteract();
  }, { once: true });

  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    switch (e.code) {
      case 'Space':
        e.preventDefault();
        player.togglePlay();
        timeline.update();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        player.pause();
        player.stepFrame(-1);
        break;
      case 'ArrowRight':
        e.preventDefault();
        player.pause();
        player.stepFrame(1);
        break;
      case 'BracketLeft':
        e.preventDefault();
        timeline.setActiveSpeed(player.cycleSpeed(-1));
        break;
      case 'BracketRight':
        e.preventDefault();
        timeline.setActiveSpeed(player.cycleSpeed(1));
        break;
      case 'KeyD':
        e.preventDefault();
        director.toggle();
        ui.setDirectorActive(director.active);
        break;
    }
  });

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  function animate(timestamp) {
    player.update(timestamp);
    director.update(timestamp);
    cameraCtrl.update();
    timeline.update();
    ui.updateFps(timestamp);
    renderer.render(scene, camera);
  }

  renderer.setAnimationLoop(animate);
}

// ── Init ─────────────────────────────────────────────────────────────

async function init() {
  const canvas = document.getElementById('viewport');
  const ui = new UI();
  ui.setLoadingText('Initializing...');

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x0a0a0f);

  const manifest = await fetchManifest();

  if (manifest && manifest.mode === 'image-strip') {
    document.body.classList.add('bullet-time-mode');
    await initBulletTime(manifest, canvas, renderer, ui);
  } else {
    await initSplatMode(manifest, canvas, renderer, ui);
  }
}

init().catch(err => {
  console.error('Replay viewer failed to initialize:', err);
  const ui = new UI();
  ui.showError(err.message || 'Unknown error');
});
