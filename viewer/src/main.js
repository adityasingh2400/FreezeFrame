import * as THREE from 'three';
import { ImageStripPlayer } from './image-strip-player.js';
import { connectVoice, setMicActive, isMicActive, reportFrameChange, setCurrentScene, resetAgent } from './voice.js';

// ── DOM refs ──────────────────────────────────────────────────────────

const landing      = document.getElementById('landing');
const agentView    = document.getElementById('agent-view');
const colmapScreen = document.getElementById('colmap-screen');
const colmapCanvas = document.getElementById('colmap-canvas');
const colmapVideos = document.getElementById('colmap-videos');
const canvas       = document.getElementById('viewport');
const hud          = document.getElementById('viewer-hud');
const fileInput    = document.getElementById('file-input');
const uploadZone   = document.getElementById('upload-zone');
const agentCircle  = document.getElementById('agent-circle');
const backBtn      = document.getElementById('back-btn');
const boomerangBtn = document.getElementById('bt-boomerang-btn');

// ── State ─────────────────────────────────────────────────────────────

let videoURLs   = [];
let videoEls    = [];
let stripPlayer = null;
let renderer    = null;
let scene       = null;
let camera      = null;
let animLoopId  = null;
let frameNames  = [];

// ── Upload (State 1) ─────────────────────────────────────────────────

fileInput.addEventListener('change', () => {
  if (fileInput.files.length > 0) enterAgentView(fileInput.files);
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
  if (e.dataTransfer.files.length > 0) enterAgentView(e.dataTransfer.files);
});

// ── Agent View (State 2) ──────────────────────────────────────────────

function enterAgentView(files) {
  const fileArr = Array.from(files);
  videoURLs = [];
  for (let i = 0; i < 5; i++) {
    const file = fileArr[i % fileArr.length];
    videoURLs.push(URL.createObjectURL(file));
  }

  landing.classList.add('hidden');
  setTimeout(() => { landing.style.display = 'none'; }, 600);

  runColmapSimulation(videoURLs).then(() => {
    showAgentView();
  });
}

// ── COLMAP Simulation ──────────────────────────────────────────────────

async function runColmapSimulation(urls) {
  colmapScreen.style.display = '';
  colmapScreen.classList.add('visible');
  colmapVideos.innerHTML = '';

  const ctx = colmapCanvas.getContext('2d');
  colmapCanvas.width = window.innerWidth;
  colmapCanvas.height = window.innerHeight;

  const stepEl = document.getElementById('colmap-step');
  const detailEl = document.getElementById('colmap-detail');
  const fillEl = document.getElementById('colmap-progress-fill');

  function setStep(text) {
    stepEl.textContent = text;
    stepEl.classList.add('visible');
  }
  function setDetail(text) {
    detailEl.textContent = text;
    detailEl.classList.add('visible');
  }
  function setProgress(pct) {
    fillEl.style.width = `${pct}%`;
  }

  // Create video wrappers at random scattered positions
  const wrappers = [];
  const scatterPositions = [
    { x: -320, y: -180, rot: -12 },
    { x: 280, y: -140, rot: 8 },
    { x: -180, y: 160, rot: -6 },
    { x: 340, y: 190, rot: 14 },
    { x: 20, y: -20, rot: -3 },
  ];

  for (let i = 0; i < 5; i++) {
    const wrapper = document.createElement('div');
    wrapper.className = 'colmap-vid-wrapper';
    const video = document.createElement('video');
    video.src = urls[i];
    video.muted = true;
    video.playsInline = true;
    video.loop = true;
    video.play().catch(() => {});
    const label = document.createElement('div');
    label.className = 'colmap-vid-label';
    label.textContent = '';
    label.style.opacity = '0';
    const scan = document.createElement('div');
    scan.className = 'colmap-vid-scan';
    const features = document.createElement('div');
    features.className = 'colmap-vid-features';
    wrapper.appendChild(video);
    wrapper.appendChild(scan);
    wrapper.appendChild(features);
    wrapper.appendChild(label);
    colmapVideos.appendChild(wrapper);
    wrappers.push({ wrapper, video, scan, features });
  }

  await sleep(100);

  // Phase 1: Videos scatter in from random positions
  setStep('Ingesting video feeds');
  setDetail('Loading and decoding video streams...');
  setProgress(5);

  for (let i = 0; i < 5; i++) {
    const sp = scatterPositions[i];
    wrappers[i].wrapper.style.left = `calc(50% + ${sp.x}px - 110px)`;
    wrappers[i].wrapper.style.top = `calc(50% + ${sp.y}px - 66px)`;
    wrappers[i].wrapper.style.transform = `scale(1) rotate(${sp.rot}deg)`;
    await sleep(120);
    wrappers[i].wrapper.classList.add('scattered');
  }

  await sleep(400);
  setProgress(15);

  // Phase 2: Feature extraction — scan lines pass over each video
  setStep('Extracting SIFT features');

  for (let i = 0; i < 5; i++) {
    const w = wrappers[i];
    w.scan.classList.add('active');
    setDetail(`Scanning CAM ${i + 1} — detecting keypoints...`);
    setProgress(15 + (i + 1) * 8);

    // Spawn feature dots progressively
    for (let f = 0; f < 8; f++) {
      await sleep(30);
      const dot = document.createElement('div');
      dot.className = 'colmap-feature-dot';
      const px = 10 + Math.random() * 80;
      const py = 10 + Math.random() * 80;
      dot.style.left = `${px}%`;
      dot.style.top = `${py}%`;
      dot.style.animationDelay = `${f * 0.02}s`;
      w.features.appendChild(dot);
    }
    w.features.classList.add('active');
    await sleep(200);
    w.scan.classList.remove('active');
  }

  await sleep(300);
  setProgress(60);

  // Phase 3: Feature matching — draw lines between videos on canvas
  setStep('Matching feature correspondences');
  setDetail('Finding overlapping features between camera pairs...');

  const particles = [];
  let matchAnimRunning = true;
  const matchStartTime = performance.now();

  function getWrapperCenter(idx) {
    const rect = wrappers[idx].wrapper.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  const pairs = [[0,1],[1,2],[2,3],[3,4],[0,4],[0,2],[1,3],[0,3],[1,4],[2,4]];

  function animateMatching() {
    if (!matchAnimRunning) return;
    ctx.clearRect(0, 0, colmapCanvas.width, colmapCanvas.height);

    const elapsed = (performance.now() - matchStartTime) * 0.001;
    for (let p = 0; p < pairs.length; p++) {
      const [a, b] = pairs[p];
      const ca = getWrapperCenter(a);
      const cb = getWrapperCenter(b);
      const alpha = Math.max(0, Math.min(1, (elapsed * 1.5 - p * 0.25)));
      if (alpha <= 0) continue;

      ctx.beginPath();
      ctx.moveTo(ca.x, ca.y);
      ctx.lineTo(cb.x, cb.y);
      ctx.strokeStyle = `rgba(212, 64, 96, ${alpha * 0.25})`;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 8]);
      ctx.lineDashOffset = -elapsed * 40;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Animate particles along connection lines
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.t += p.speed;
      if (p.t > 1) { particles.splice(i, 1); continue; }
      const x = p.ax + (p.bx - p.ax) * p.t;
      const y = p.ay + (p.by - p.ay) * p.t;
      const alpha = p.t < 0.2 ? p.t / 0.2 : p.t > 0.8 ? (1 - p.t) / 0.2 : 1;
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(212, 149, 106, ${alpha * 0.9})`;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(212, 149, 106, ${alpha * 0.2})`;
      ctx.fill();
    }

    requestAnimationFrame(animateMatching);
  }

  animateMatching();

  // Spawn match particles
  for (let round = 0; round < 3; round++) {
    for (const [a, b] of pairs.slice(0, 4 + round * 2)) {
      const ca = getWrapperCenter(a);
      const cb = getWrapperCenter(b);
      particles.push({
        ax: ca.x, ay: ca.y, bx: cb.x, by: cb.y,
        t: 0, speed: 0.012 + Math.random() * 0.015,
      });
    }
    setProgress(60 + round * 7);
    await sleep(250);
  }

  await sleep(400);
  setProgress(82);

  // Phase 4: Pose estimation — rearrange into a circle
  setStep('Estimating camera poses');
  setDetail('Computing relative camera positions via bundle adjustment...');

  // Fade feature dots
  wrappers.forEach(w => {
    w.features.querySelectorAll('.colmap-feature-dot').forEach(d => d.classList.add('fade'));
  });

  await sleep(200);

  // Rearrange videos into a circle (same layout as orbit ring)
  const orbitRadius = 220;
  for (let i = 0; i < 5; i++) {
    const angle = (-90 + i * 72) * Math.PI / 180;
    const x = Math.cos(angle) * orbitRadius;
    const y = Math.sin(angle) * orbitRadius;
    wrappers[i].wrapper.classList.add('arranging');
    wrappers[i].wrapper.style.left = `calc(50% + ${x}px - 110px)`;
    wrappers[i].wrapper.style.top = `calc(50% + ${y}px - 66px)`;
    wrappers[i].wrapper.style.transform = `scale(1) rotate(0deg)`;
    setProgress(82 + (i + 1) * 3);
    await sleep(120);
  }

  // Cameras are now in position — reveal labels
  for (let i = 0; i < 5; i++) {
    const label = wrappers[i].wrapper.querySelector('.colmap-vid-label');
    label.textContent = `CAM ${i + 1}`;
    label.style.opacity = '1';
  }

  await sleep(800);
  setProgress(98);

  // Phase 5: Draw the orbit ring on canvas and show "done"
  setStep('Spatial calibration complete');
  setDetail(`5 cameras positioned — 180° coverage estimated`);
  setProgress(100);

  // Draw orbit ring glow on canvas
  const drawOrbit = () => {
    const ringCx = colmapCanvas.width / 2;
    const ringCy = colmapCanvas.height / 2;
    ctx.clearRect(0, 0, colmapCanvas.width, colmapCanvas.height);
    ctx.beginPath();
    ctx.arc(ringCx, ringCy, orbitRadius + 60, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(212, 64, 96, 0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 10]);
    ctx.stroke();
    ctx.setLineDash([]);
  };
  matchAnimRunning = false;
  drawOrbit();

  await sleep(900);

  // Transition out
  colmapScreen.classList.add('hidden');
  await sleep(600);
  colmapScreen.style.display = 'none';
  colmapScreen.classList.remove('visible', 'hidden');
  ctx.clearRect(0, 0, colmapCanvas.width, colmapCanvas.height);
  colmapVideos.innerHTML = '';
}

function showAgentView() {
  agentView.style.display = '';
  agentView.classList.remove('hidden');
  agentView.classList.add('visible');

  videoEls = [];
  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    const video = thumb.querySelector('.thumb-video');
    const label = thumb.querySelector('.thumb-label');

    video.src = videoURLs[i];
    video.muted = true;
    video.preload = 'auto';
    label.textContent = '';
    label.style.opacity = '0';

    videoEls.push(video);
    video.play().catch(() => {});
    setTimeout(() => thumb.classList.add('visible'), 100 + i * 80);
  }

  // Clap frames per camera: cam01=F0, cam02=F0, cam03=F0, cam04=F3, cam05=F8
  const clapFrames = [0, 0, 0, 3, 8];

  setTimeout(async () => {
    startAllVideosSynced();
    await playSyncAnimation(5, clapFrames);
    await highlightAndEnlarge();
  }, 500);

  connectVoice({
    onNavigate: handleMomentSelected,
    onExitViewer: returnToAgent,
    onIndicatorChange: handleIndicatorChange,
    onUserSpeech: handleUserSpeech,
  }).catch(err => console.error('[VOICE] connectVoice failed:', err));

  // Spacebar tap-to-toggle mic
  if (!window._pttRegistered) {
    window._pttRegistered = true;
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !e.repeat) {
        e.preventDefault();
        setMicActive(!isMicActive());
      }
      if (e.code === 'KeyJ' && !e.repeat) {
        e.preventDefault();
        resetAgent();
        resumeAllVideos();
      }
    });
  }
}

// ── Post-Sync: Highlight borders, then enlarge main video ─────────────

async function highlightAndEnlarge() {
  const thumbs = Array.from({ length: 5 }, (_, i) => document.getElementById(`thumb-${i}`));

  // Phase 1: Highlight each video border sequentially (3s total)
  for (let i = 0; i < 5; i++) {
    thumbs[i].classList.add('highlight-border');
    await sleep(600);
  }
  await sleep(600);

  // Phase 2: Fade out non-main thumbs, enlarge thumb-0 as main video
  const mainIdx = 0;
  for (let i = 0; i < 5; i++) {
    thumbs[i].classList.remove('highlight-border');
    if (i !== mainIdx) {
      thumbs[i].classList.add('fade-to-secondary');
    }
  }

  await sleep(400);

  // Hide orbit ring
  const orbitRing = document.getElementById('orbit-ring');
  if (orbitRing) orbitRing.style.opacity = '0';

  // Enlarge main thumb
  thumbs[mainIdx].classList.add('main-video');

  // Move agent circle to bottom-right
  agentCircle.classList.add('corner-mode');

  await sleep(800);
}

// ── Video Playback Control ────────────────────────────────────────────

let videosPaused = false;

function startAllVideosSynced() {
  if (!videoEls.length) return;

  // Reset all to same start time
  const startTime = 0;
  const playPromises = [];

  for (const video of videoEls) {
    video.currentTime = startTime;
    video.muted = true;
    video.playbackRate = 1;
  }

  // Start all in a tight burst — requestAnimationFrame ensures they kick off in the same frame
  requestAnimationFrame(() => {
    for (const video of videoEls) {
      playPromises.push(video.play().catch(() => {}));
    }
    Promise.all(playPromises).then(() => {
      startVideoSync();
    });
  });

  videosPaused = false;
}

function pauseAllVideos() {
  if (videosPaused) return;
  videosPaused = true;
  for (const video of videoEls) {
    video.pause();
  }
}

function resumeAllVideos() {
  if (!videosPaused) return;
  videosPaused = false;

  if (!videoEls.length) return;

  // Snap all to master time before resuming
  const master = videoEls[0];
  const t = master.currentTime;
  for (let i = 1; i < videoEls.length; i++) {
    videoEls[i].currentTime = t;
  }

  requestAnimationFrame(() => {
    for (const video of videoEls) {
      video.play().catch(() => {});
    }
  });
}

function handleIndicatorChange(state) {
  agentCircle.dataset.state = state;
  const hudInd = document.getElementById('listening-indicator');
  if (hudInd) hudInd.dataset.state = state;

  // Spacebar held = strong visual feedback
  agentCircle.classList.toggle('ptt-active', state === 'listening');

  if (state === 'speaking') {
    pauseAllVideos();
  } else if (state === 'listening') {
    pauseAllVideos();
  } else if (state === 'idle' && videosPaused) {
    resumeAllVideos();
  }
}

function handleUserSpeech() {
  pauseAllVideos();
}

// ── Sync Animation ────────────────────────────────────────────────────

const ORBIT_POSITIONS = [
  { ml: 0,    mt: -310 },
  { ml: 295,  mt: -96  },
  { ml: 182,  mt: 251  },
  { ml: -182, mt: 251  },
  { ml: -295, mt: -96  },
];

function captureVideoFrame(video, width, height) {
  const c = document.createElement('canvas');
  c.width = width;
  c.height = height;
  const ctx = c.getContext('2d');
  ctx.drawImage(video, 0, 0, width, height);
  return c;
}

function createWaveformBars(count) {
  const container = document.createElement('div');
  container.className = 'thumb-waveform-bars';
  for (let i = 0; i < count; i++) {
    const bar = document.createElement('div');
    bar.className = 'waveform-bar';
    bar.style.height = '2px';
    container.appendChild(bar);
  }
  return container;
}

function animateWaveformBars(barsContainer, durationMs, clapPct) {
  const bars = barsContainer.querySelectorAll('.waveform-bar');
  const barCount = bars.length;
  const start = performance.now();
  const clapBarIdx = Math.floor(clapPct * barCount);

  function frame() {
    const elapsed = performance.now() - start;
    const progress = Math.min(elapsed / durationMs, 1);
    const scanPos = progress * barCount;

    bars.forEach((bar, i) => {
      const dist = Math.abs(i - scanPos);
      if (dist < 6) {
        const intensity = 1 - dist / 6;
        const nearClap = Math.abs(i - clapBarIdx) < 3 ? 1.5 : 1;
        const h = 3 + intensity * 18 * nearClap * (0.5 + Math.random() * 0.5);
        bar.style.height = `${h}px`;
        bar.style.background = Math.abs(i - clapBarIdx) < 2
          ? 'rgba(212, 64, 96, 0.8)'
          : 'rgba(212, 64, 96, 0.45)';
      } else if (i < scanPos) {
        const h = Math.abs(i - clapBarIdx) < 3 ? 12 : 3;
        bar.style.height = `${h}px`;
        bar.style.background = Math.abs(i - clapBarIdx) < 2
          ? 'rgba(212, 64, 96, 0.7)'
          : 'rgba(122, 27, 45, 0.25)';
      } else {
        bar.style.height = '2px';
        bar.style.background = 'rgba(212, 64, 96, 0.15)';
      }
    });

    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

async function playSyncAnimation(count, clapFrames) {
  const thumbs = Array.from({ length: count }, (_, i) => document.getElementById(`thumb-${i}`));
  const orbitContainer = document.getElementById('orbit-container');

  // ── Phase 0: Show videos on orbit ring briefly ──
  await sleep(1500);

  // ── Phase 1: Rearrange into vertical stack ──
  agentCircle.style.transition = 'opacity 0.5s ease';
  agentCircle.style.opacity = '0';
  const orbitRing = document.getElementById('orbit-ring');
  if (orbitRing) {
    orbitRing.style.transition = 'opacity 0.5s ease';
    orbitRing.style.opacity = '0';
  }

  await sleep(300);

  // Calculate vertical stack positions — wide cards showing full video
  const stackWidth = 520;
  const stackHeight = 100;
  const stackGap = 10;
  const totalStackHeight = count * stackHeight + (count - 1) * stackGap;
  const stackStartY = -totalStackHeight / 2;

  thumbs.forEach((thumb, i) => {
    thumb.classList.add('stack-mode');
    thumb.style.width = `${stackWidth}px`;
    thumb.style.height = `${stackHeight}px`;
    thumb.style.marginLeft = '0px';
    thumb.style.marginTop = `${stackStartY + i * (stackHeight + stackGap)}px`;
    thumb.style.borderRadius = '8px';

    // Seek each video to its clap frame so they visually align in the stack
    const video = thumb.querySelector('.thumb-video');
    if (video && isFinite(clapFrames[i])) {
      video.pause();
      video.currentTime = clapFrames[i] / 30;
    }
  });

  await sleep(900);

  // ── Phase 2: Show status + begin waveform analysis ──
  const syncStatus = document.createElement('div');
  syncStatus.id = 'sync-status';
  syncStatus.innerHTML = '<span class="sync-status-text"><span class="sync-pulse-dot"></span>Analyzing audio waveforms</span>';
  document.body.appendChild(syncStatus);

  await sleep(100);
  syncStatus.classList.add('visible');
  syncStatus.classList.add('analyzing');

  await sleep(400);

  // Add waveform scan overlay and bars to each video, staggered
  const waveformDuration = 2200;
  const staggerDelay = 200;

  for (let i = 0; i < count; i++) {
    const thumb = thumbs[i];

    // Scan overlay (the sweeping light + scanline)
    const scanOverlay = document.createElement('div');
    scanOverlay.className = 'thumb-waveform-scan';
    thumb.appendChild(scanOverlay);

    // Waveform bars
    const waveformBars = createWaveformBars(40);
    thumb.appendChild(waveformBars);

    // Camera number badge
    const badge = document.createElement('div');
    badge.className = 'sync-cam-badge';
    badge.textContent = i + 1;
    thumb.appendChild(badge);

    setTimeout(() => {
      badge.classList.add('visible');
      scanOverlay.classList.add('active');
      waveformBars.classList.add('active');
      animateWaveformBars(waveformBars, waveformDuration, clapFrames[i] / 30);
    }, i * staggerDelay);
  }

  // Wait for all scans to complete
  await sleep(waveformDuration + (count - 1) * staggerDelay + 200);

  // ── Phase 3: "Auditory cue identified" ──
  const pulseDot = syncStatus.querySelector('.sync-pulse-dot');
  if (pulseDot) pulseDot.classList.add('found');
  syncStatus.classList.remove('analyzing');
  syncStatus.classList.add('identified');
  syncStatus.querySelector('.sync-status-text').innerHTML =
    '<span class="sync-pulse-dot found"></span>Auditory cue identified';

  await sleep(600);

  // ── Phase 4: Extract and show clap frames ──
  for (let i = 0; i < count; i++) {
    const thumb = thumbs[i];
    const video = thumb.querySelector('.thumb-video');

    // Seek video to clap frame (assume ~30fps)
    const clapTime = clapFrames[i] / 30;
    if (isFinite(clapTime)) {
      video.currentTime = clapTime;
    }

    await sleep(80);

    // Create clap frame container
    const frameContainer = document.createElement('div');
    frameContainer.className = 'clap-frame-container';

    const frameCanvas = captureVideoFrame(video, 144, 144);
    frameContainer.appendChild(frameCanvas);

    const frameLabel = document.createElement('div');
    frameLabel.className = 'clap-frame-label';
    frameLabel.textContent = `F${clapFrames[i]}`;
    frameContainer.appendChild(frameLabel);

    // Connector line
    const connector = document.createElement('div');
    connector.className = 'clap-connector';
    thumb.appendChild(connector);
    thumb.appendChild(frameContainer);

    // Staggered reveal
    await sleep(150);
    frameContainer.classList.add('visible');
    connector.classList.add('visible');
  }

  await sleep(500);

  // ── Phase 5: Synchronize claps — visual beat ──
  syncStatus.querySelector('.sync-status-text').innerHTML =
    '<span class="sync-pulse-dot found"></span>Synchronizing frames';

  await sleep(400);

  // Flash + ring
  const flash = document.getElementById('clap-flash');
  if (flash) {
    flash.style.opacity = '1';
    setTimeout(() => { flash.style.opacity = '0'; }, 80);
  }

  const ring = document.getElementById('clap-ring');
  if (ring) ring.classList.add('active');

  // All clap frames pulse simultaneously
  thumbs.forEach(thumb => {
    const fc = thumb.querySelector('.clap-frame-container');
    if (fc) fc.classList.add('synced');
    thumb.classList.add('synced');
  });

  await sleep(600);

  // Update status to synced
  syncStatus.classList.remove('identified');
  syncStatus.classList.add('synced');
  syncStatus.querySelector('.sync-status-text').innerHTML = '\u25CF Frames synced';

  // Assign camera labels
  thumbs.forEach((thumb, i) => {
    const label = thumb.querySelector('.thumb-label');
    if (label) {
      label.textContent = `CAM ${i + 1}`;
      label.style.transition = 'opacity 0.4s ease';
      label.style.opacity = '1';
    }
  });

  await sleep(1200);

  // ── Phase 6: Collapse into single centered video ──

  // Fade out clap frames and waveform elements
  thumbs.forEach(thumb => {
    const fc = thumb.querySelector('.clap-frame-container');
    const conn = thumb.querySelector('.clap-connector');
    const scan = thumb.querySelector('.thumb-waveform-scan');
    const bars = thumb.querySelector('.thumb-waveform-bars');
    const badge = thumb.querySelector('.sync-cam-badge');
    if (fc) { fc.style.opacity = '0'; }
    if (conn) { conn.style.opacity = '0'; }
    if (scan) { scan.style.opacity = '0'; }
    if (bars) { bars.style.opacity = '0'; }
    if (badge) { badge.style.opacity = '0'; }
  });

  // Fade out status
  syncStatus.classList.remove('visible');

  await sleep(600);

  // Collapse all thumbs toward center — thumb-0 becomes the "hero"
  // Others shrink and fade into thumb-0's position
  for (let i = 1; i < count; i++) {
    thumbs[i].style.marginTop = '0px';
    thumbs[i].style.opacity = '0';
    thumbs[i].style.transform = 'translate(-50%, -50%) scale(0.5)';
  }

  // Move thumb-0 to dead center
  thumbs[0].style.marginTop = '0px';
  thumbs[0].style.marginLeft = '0px';

  await sleep(700);

  // Enlarge the hero video to a nice centered size
  const heroWidth = 480;
  const heroHeight = 288;
  thumbs[0].style.width = `${heroWidth}px`;
  thumbs[0].style.height = `${heroHeight}px`;
  thumbs[0].style.borderRadius = '12px';
  thumbs[0].style.borderColor = 'var(--border-bright)';
  thumbs[0].style.overflow = 'hidden';

  // Keep camera label visible on the hero
  const heroLabel = thumbs[0].querySelector('.thumb-label');
  if (heroLabel) {
    heroLabel.textContent = 'SYNCED';
    heroLabel.style.opacity = '1';
  }

  await sleep(800);

  // ── Phase 7: Agent circle appears at bottom-right via corner-mode ──
  agentCircle.classList.add('corner-mode');
  agentCircle.style.opacity = '1';

  await sleep(800);

  // Remove temporary DOM elements from all thumbs
  thumbs.forEach(thumb => {
    thumb.querySelectorAll('.clap-frame-container, .clap-connector, .thumb-waveform-scan, .thumb-waveform-bars, .sync-cam-badge, .thumb-timeline').forEach(el => el.remove());
    thumb.classList.remove('synced', 'syncing');
  });

  if (ring) ring.classList.remove('active');
  syncStatus.remove();

  // Start synced video playback
  startAllVideosSynced();
}

let syncInterval = null;
let syncRAF = null;
let syncFrameCount = 0;

function startVideoSync() {
  stopVideoSync();
  syncFrameCount = 0;
  function syncLoop() {
    syncFrameCount++;
    // Check sync every 5 frames (~83ms at 60fps) — tight enough for seamless, light enough on CPU
    if (syncFrameCount % 5 === 0 && videoEls.length) {
      const master = videoEls[0];
      if (master && !master.paused) {
        const t = master.currentTime;
        for (let i = 1; i < videoEls.length; i++) {
          if (Math.abs(videoEls[i].currentTime - t) > 0.05) {
            videoEls[i].currentTime = t;
          }
        }
      }
    }
    syncRAF = requestAnimationFrame(syncLoop);
  }
  syncRAF = requestAnimationFrame(syncLoop);
}

function stopVideoSync() {
  if (syncInterval) { clearInterval(syncInterval); syncInterval = null; }
  if (syncRAF) { cancelAnimationFrame(syncRAF); syncRAF = null; }
}

// ── Freeze Transition (State 2 → 3) ──────────────────────────────────

async function handleMomentSelected(slug, label) {
  // Pause all videos
  videoEls.forEach(v => v.pause());
  stopVideoSync();

  // Freezing glow
  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    thumb.classList.add('freezing');
  }

  await sleep(700);

  // Merge toward center
  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    thumb.classList.add('merging');
  }
  agentCircle.classList.add('merging');

  await sleep(900);

  // Hide agent view, show viewer
  agentView.classList.add('hidden');
  await sleep(600);
  agentView.style.display = 'none';

  await enterViewer(slug, label);
}

// ── Viewer (State 3) ──────────────────────────────────────────────────

async function enterViewer(slug, label) {
  canvas.style.display = '';
  canvas.classList.add('visible');
  hud.style.display = '';
  hud.classList.add('visible');

  // Three.js setup (reuse if already exists)
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0D0809);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0D0809);
  }
  renderer.setSize(window.innerWidth, window.innerHeight);

  // Load manifest
  let manifest;
  try {
    const res = await fetch(`/precomputed/${slug}/manifest.json`);
    manifest = await res.json();
  } catch (err) {
    console.error(`Failed to load manifest for ${slug}:`, err);
    return;
  }

  // Set HUD info
  const momentLabel = manifest.moment?.label || label || slug;
  const momentDesc  = manifest.moment?.description || '';
  document.getElementById('bt-moment-label').textContent = momentLabel;
  document.getElementById('bt-moment-desc').textContent  = momentDesc;
  setCurrentScene(momentLabel);

  // Frame names for REAL/AI badge
  frameNames = manifest.frames || [];
  const totalFrames = frameNames.length;
  document.getElementById('frame-label').textContent = `/ ${String(totalFrames).padStart(3, '0')}`;

  // Build image URLs
  const baseDir = manifest.baseDir || `/precomputed/${slug}/`;
  const urls = frameNames.map(f => baseDir + f);

  // Create strip player
  stripPlayer = new ImageStripPlayer(scene);
  camera = stripPlayer.createCamera();
  window.freezeframePlayer = stripPlayer;
  window.freezeframeCamera = camera;

  await stripPlayer.loadImages(urls);
  stripPlayer.bindDrag(canvas);

  // Wire frame change to HUD updates + voice layer
  stripPlayer.onFrameChange = (frame) => {
    document.getElementById('frame-counter').textContent = String(frame + 1).padStart(3, '0');
    updateAngleBar(frame, totalFrames);
    updateSourceBadge(frame);

    // Report to voice layer (throttled)
    if (!window._frameThrottle) {
      window._frameThrottle = setTimeout(() => {
        window._frameThrottle = null;
        reportFrameChange(frame, totalFrames);
      }, 250);
    }
  };

  // Initial badge state
  updateSourceBadge(0);
  updateAngleBar(0, totalFrames);

  // Show drag hint, fade after 4s
  const hint = document.getElementById('bt-drag-hint');
  if (hint) {
    hint.style.opacity = '1';
    setTimeout(() => { hint.style.opacity = '0'; }, 4000);
  }

  // Keyboard controls
  window._viewerKeyHandler = (e) => {
    if (!stripPlayer) return;
    switch (e.code) {
      case 'ArrowLeft':  e.preventDefault(); stripPlayer.stepFrame(-1); break;
      case 'ArrowRight': e.preventDefault(); stripPlayer.stepFrame(1);  break;
      case 'Home':       e.preventDefault(); stripPlayer.setFrame(0);   break;
      case 'End':        e.preventDefault(); stripPlayer.setFrame(stripPlayer.totalFrames - 1); break;
    }
  };
  window.addEventListener('keydown', window._viewerKeyHandler);

  // Resize handler
  window._viewerResizeHandler = () => {
    renderer.setSize(window.innerWidth, window.innerHeight);
  };
  window.addEventListener('resize', window._viewerResizeHandler);

  // Start render loop
  function renderLoop() {
    animLoopId = requestAnimationFrame(renderLoop);
    renderer.render(scene, camera);
  }
  renderLoop();

  // Auto-play entry sweep: forward → pause → reverse
  await stripPlayer.playForwardReverse(24, 400);
}

function updateAngleBar(frame, total) {
  const fill = document.getElementById('bt-angle-fill');
  if (!fill) return;
  const pct = total > 1 ? (frame / (total - 1)) * 100 : 0;
  fill.style.width = `${pct}%`;
}

function updateSourceBadge(frame) {
  const badge = document.getElementById('bt-source-badge');
  if (!badge || !frameNames.length) return;
  const name = frameNames[frame] || '';
  const isReal = name.startsWith('cam');
  badge.textContent = isReal ? 'Real Camera' : 'AI Generated';
  badge.className = isReal ? 'source-real' : 'source-synth';
}

// ── Boomerang button ──────────────────────────────────────────────────

boomerangBtn.addEventListener('click', () => {
  if (stripPlayer) stripPlayer.playBoomerang(1, 24);
});

// ── Return (State 4 → State 2) ───────────────────────────────────────

backBtn.addEventListener('click', returnToAgent);

function returnToAgent() {
  // Stop render loop
  if (animLoopId) { cancelAnimationFrame(animLoopId); animLoopId = null; }

  // Remove keyboard/resize handlers
  if (window._viewerKeyHandler) {
    window.removeEventListener('keydown', window._viewerKeyHandler);
    window._viewerKeyHandler = null;
  }
  if (window._viewerResizeHandler) {
    window.removeEventListener('resize', window._viewerResizeHandler);
    window._viewerResizeHandler = null;
  }

  // Dispose strip player
  if (stripPlayer) { stripPlayer.dispose(); stripPlayer = null; }
  window.freezeframePlayer = null;
  window.freezeframeCamera = null;
  setCurrentScene('');

  // Hide viewer
  canvas.classList.remove('visible');
  canvas.style.display = 'none';
  hud.classList.remove('visible');
  hud.style.display = 'none';

  // Reset HUD
  document.getElementById('bt-moment-label').textContent = '';
  document.getElementById('bt-moment-desc').textContent  = '';
  document.getElementById('frame-counter').textContent   = '001';

  // Show agent view + restore to centered hero layout
  agentView.style.display = '';
  agentView.classList.remove('hidden');
  agentView.classList.add('visible');

  for (let i = 0; i < 5; i++) {
    const thumb = document.getElementById(`thumb-${i}`);
    thumb.classList.remove('freezing', 'merging', 'syncing', 'synced', 'clap-converge', 'clap-rebound', 'stack-mode');
    thumb.querySelectorAll('.thumb-timeline, .clap-frame-container, .clap-connector, .thumb-waveform-scan, .thumb-waveform-bars, .sync-cam-badge').forEach(el => el.remove());

    if (i === 0) {
      // Restore hero (thumb-0) centered — let main-video CSS handle sizing
      thumb.style.marginTop = '';
      thumb.style.marginLeft = '';
      thumb.style.width = '';
      thumb.style.height = '';
      thumb.style.borderRadius = '';
      thumb.style.borderColor = '';
      thumb.style.overflow = '';
      thumb.style.opacity = '';
      thumb.style.transform = '';
      thumb.classList.add('visible', 'main-video');
      const heroLabel = thumb.querySelector('.thumb-label');
      if (heroLabel) {
        heroLabel.textContent = 'SYNCED';
        heroLabel.style.opacity = '1';
      }
    } else {
      // Keep others hidden
      thumb.style.opacity = '0';
      thumb.style.transform = 'translate(-50%, -50%) scale(0.5)';
      thumb.style.marginTop = '';
      thumb.style.marginLeft = '';
      thumb.style.width = '';
      thumb.style.height = '';
      thumb.style.borderRadius = '';
      thumb.style.borderColor = '';
      thumb.style.overflow = '';
      thumb.classList.add('visible');
    }
  }

  // Restore agent circle to fixed corner position
  agentCircle.classList.remove('merging');
  agentCircle.classList.add('corner-mode');
  agentCircle.style.opacity = '1';
  agentCircle.style.width = '';
  agentCircle.style.height = '';
  agentCircle.style.marginLeft = '';
  agentCircle.style.marginTop = '';
  agentCircle.style.transition = '';
  const agentBars = agentCircle.querySelector('#agent-bars');
  if (agentBars) agentBars.style.transform = '';

  const orbitRing = document.getElementById('orbit-ring');
  if (orbitRing) orbitRing.style.opacity = '0';
  const oldSyncStatus = document.getElementById('sync-status');
  if (oldSyncStatus) oldSyncStatus.remove();
  const oldSyncLabel = document.getElementById('sync-label');
  if (oldSyncLabel) oldSyncLabel.remove();

  // Resume video playback from where it left off (don't restart)
  videosPaused = false;
  for (const video of videoEls) {
    video.play().catch(() => {});
  }
}

// ── Helpers ───────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// Expose for voice module
export function setIndicatorState(state) {
  agentCircle.dataset.state = state;
  const hudInd = document.getElementById('listening-indicator');
  if (hudInd) hudInd.dataset.state = state;
}
window.setIndicatorState = setIndicatorState;
