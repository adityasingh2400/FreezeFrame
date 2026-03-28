import * as THREE from 'three';
import { SplatPlayer } from './splat-player.js';
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

async function init() {
  const canvas = document.getElementById('viewport');
  const ui = new UI();
  ui.setLoadingText('Initializing...');

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x0a0a0f);

  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(
    60,
    window.innerWidth / window.innerHeight,
    0.1,
    1000
  );
  camera.position.set(0, 1.5, 4);

  const cameraCtrl = new CameraController(camera, canvas);

  const player = new SplatPlayer(scene);
  const timeline = new Timeline(player);

  const manifest = await fetchManifest();
  let splatCount = 0;

  if (manifest && manifest.frames && manifest.frames.length > 0) {
    const sceneName = manifest.name || manifest.frames[0].split('/').pop().replace(/\.\w+$/, '');
    ui.setSceneName(sceneName);
    ui.setLoadingText(`Loading ${manifest.frames.length} frames...`);
    const baseDir = manifest.baseDir || '/frames/';
    const urls = manifest.frames.map(f => baseDir + f);
    splatCount = await player.loadFrames(urls, manifest.fps || 30, (loaded, total) => {
      ui.setLoadingProgress(loaded, total);
    });
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
  if (player.totalFrames > 1) {
    director.loadDefault(player.totalFrames, player.fps);
  }

  // Director button
  const directorBtn = document.getElementById('director-btn');
  if (directorBtn) {
    directorBtn.addEventListener('click', () => {
      director.toggle();
      ui.setDirectorActive(director.active);
    });
  }

  // Prev/next frame buttons
  const prevBtn = document.getElementById('prev-btn');
  const nextBtn = document.getElementById('next-btn');
  if (prevBtn) prevBtn.addEventListener('click', () => { player.pause(); player.stepFrame(-1); });
  if (nextBtn) nextBtn.addEventListener('click', () => { player.pause(); player.stepFrame(1); });

  // Dismiss orbit hint on first interaction
  canvas.addEventListener('pointerdown', () => {
    cameraCtrl.onUserInteract();
    ui.dismissOrbitHint();
  }, { once: true });

  // Keyboard shortcuts
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
        ui.dismissOrbitHint();
        break;
    }
  });

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // Sort frequency control — skip renderer.render() (and Spark's Gaussian depth sort)
  // when the camera has barely moved, capping skips at MAX_SKIP_MS for safety.
  const SORT_ANGLE_THRESHOLD = 0.02; // radians (~1.1°)
  const MAX_SKIP_MS = 150;
  const _lastSortQuat = new THREE.Quaternion();
  let _lastSortTime = 0;

  function animate(timestamp) {
    player.update(timestamp);
    director.update(timestamp);
    cameraCtrl.update();
    timeline.update();
    ui.updateFps(timestamp);

    const angleDelta = _lastSortQuat.angleTo(camera.quaternion);
    const timeSinceSort = timestamp - _lastSortTime;

    if (angleDelta >= SORT_ANGLE_THRESHOLD || timeSinceSort >= MAX_SKIP_MS) {
      renderer.render(scene, camera);
      _lastSortQuat.copy(camera.quaternion);
      _lastSortTime = timestamp;
    }
  }

  renderer.setAnimationLoop(animate);
}

init().catch(err => {
  console.error('Replay viewer failed to initialize:', err);
  const ui = new UI();
  ui.showError(err.message || 'Unknown error');
});
