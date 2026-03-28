/**
 * viewer.js — Gaussian splat viewer using @mkkellogg/gaussian-splats-3d
 * Handles orbit/zoom/time controls and exposes replayAPI for Gemini Live.
 */

import * as GaussianSplats3D from "@mkkellogg/gaussian-splats-3d";

// ─── State ────────────────────────────────────────────────────────────────────

const state = {
    currentFrame: 0,
    totalFrames: 1,
    fps: 30,
    playing: false,
    playbackSpeed: 1.0,
    heroFrame: 0,
    camera: { azimuth: 0, elevation: 15, zoom: 5.0 },
    meta: null,
    viewer: null,
    directorActive: false,
    directorTimer: null,
};

// ─── DOM ─────────────────────────────────────────────────────────────────────

const slider      = document.getElementById("time-slider");
const frameLabel  = document.getElementById("frame-label");
const playBtn     = document.getElementById("play-btn");
const resetBtn    = document.getElementById("reset-btn");
const directorBtn = document.getElementById("director-btn");
const loadingEl   = document.getElementById("loading");
const loadingDetail = document.getElementById("loading-detail");
const sceneInfo   = document.getElementById("scene-info");

// ─── Scene Loading ────────────────────────────────────────────────────────────

async function loadOutputMeta() {
    try {
        const resp = await fetch("/output/output_meta.json");
        if (!resp.ok) return null;
        return await resp.json();
    } catch { return null; }
}

async function findSplatUrl() {
    // 1. Try output_meta.json
    const meta = await loadOutputMeta();
    if (meta) {
        state.meta = meta;
        state.totalFrames = meta.num_frames || 1;
        state.fps = meta.fps || 30;
        state.heroFrame = meta.hero_frame || 0;
        if (meta.splat_url) return meta.splat_url;
        return `/output/frames/frame_00000.ply`;
    }

    // 2. Try trained 4DGS point cloud
    for (const url of [
        "/output/point_cloud.ply",
        "/output/frames/point_cloud.ply",
        "/output/frames/nike.splat",
    ]) {
        try {
            const r = await fetch(url, { method: "HEAD" });
            if (r.ok) return url;
        } catch {}
    }
    return null;
}

async function initScene() {
    const splatUrl = await findSplatUrl();

    if (!splatUrl) {
        loadingDetail.textContent = "No scene file found. Run the pipeline first or place a .ply in output/frames/";
        return;
    }

    loadingDetail.textContent = `Loading ${splatUrl}...`;

    try {
        const viewer = new GaussianSplats3D.Viewer({
            rootElement: document.getElementById("canvas-container"),
            selfDrivenMode: true,
            useBuiltInControls: true,
            initialCameraPosition: [0, 0, -state.camera.zoom],
            initialCameraLookAt: [0, 0, 0],
            gpuAcceleratedSort: true,
        });

        state.viewer = viewer;

        await viewer.loadFile(splatUrl, {
            splatAlphaRemovalThreshold: 5,
        });

        viewer.start();

        // Hide loading
        loadingEl.classList.add("hidden");

        // Update slider
        slider.max = Math.max(0, state.totalFrames - 1);
        slider.value = state.heroFrame;
        state.currentFrame = state.heroFrame;
        updateFrameLabel();

        const ext = splatUrl.split(".").pop();
        sceneInfo.textContent = `Replay — ${state.totalFrames} frame${state.totalFrames > 1 ? "s" : ""} · ${state.fps}fps · ${ext.toUpperCase()}`;

        console.log(`[VIEWER] Scene loaded: ${splatUrl}`);
    } catch (err) {
        loadingDetail.textContent = `Failed to load scene: ${err.message}`;
        console.error("[VIEWER] Load error:", err);
    }
}

// ─── Camera Helpers ───────────────────────────────────────────────────────────

function applyCamera() {
    if (!state.viewer) return;
    const azRad = (state.camera.azimuth * Math.PI) / 180;
    const elRad = (state.camera.elevation * Math.PI) / 180;
    const r = state.camera.zoom;
    const x = r * Math.cos(elRad) * Math.sin(azRad);
    const y = -r * Math.sin(elRad);
    const z = r * Math.cos(elRad) * Math.cos(azRad);
    try {
        state.viewer.camera.position.set(x, y, z);
        state.viewer.camera.lookAt(0, 0, 0);
    } catch {}
}

// ─── Time Controls ────────────────────────────────────────────────────────────

function updateFrameLabel() {
    frameLabel.textContent = `${state.currentFrame} / ${Math.max(0, state.totalFrames - 1)}`;
}

slider.addEventListener("input", () => {
    state.currentFrame = parseInt(slider.value);
    updateFrameLabel();
    loadFrame(state.currentFrame);
});

async function loadFrame(frameIdx) {
    if (!state.viewer || state.totalFrames <= 1) return;
    const padded = String(frameIdx).padStart(5, "0");
    const url = `/output/frames/frame_${padded}.ply`;
    try {
        await state.viewer.removeSplatScene(0);
        await state.viewer.addSplatScene(url, { splatAlphaRemovalThreshold: 5 });
    } catch (e) {
        console.warn("[VIEWER] Frame load error:", e.message);
    }
}

playBtn.addEventListener("click", () => {
    state.playing = !state.playing;
    playBtn.textContent = state.playing ? "Pause" : "Play";
    if (state.playing) playLoop();
});

function playLoop() {
    if (!state.playing) return;
    state.currentFrame = (state.currentFrame + 1) % state.totalFrames;
    slider.value = state.currentFrame;
    updateFrameLabel();
    loadFrame(state.currentFrame);
    setTimeout(playLoop, 1000 / (state.fps * state.playbackSpeed));
}

resetBtn.addEventListener("click", () => {
    state.playing = false;
    playBtn.textContent = "Play";
    state.camera = { azimuth: 0, elevation: 15, zoom: 5.0 };
    state.currentFrame = state.heroFrame;
    slider.value = state.heroFrame;
    updateFrameLabel();
    applyCamera();
});

// ─── Director Mode ────────────────────────────────────────────────────────────

const DIRECTOR_KEYFRAMES = [
    { t: 0.0,  az: 0,   el: 20, zoom: 5.0, speed: 1.0 },
    { t: 0.15, az: 45,  el: 15, zoom: 5.5, speed: 0.5 },
    { t: 0.35, az: 90,  el: 10, zoom: 6.0, speed: 0.2 },
    { t: 0.55, az: 180, el: 5,  zoom: 7.0, speed: 0.1 },
    { t: 0.75, az: 270, el: 15, zoom: 5.5, speed: 0.3 },
    { t: 1.0,  az: 360, el: 20, zoom: 5.0, speed: 1.0 },
];

function lerp(a, b, t) { return a + (b - a) * t; }

function directorStep(elapsed, duration) {
    if (!state.directorActive) return;
    const tNorm = Math.min(elapsed / duration, 1.0);

    for (let i = 0; i < DIRECTOR_KEYFRAMES.length - 1; i++) {
        const a = DIRECTOR_KEYFRAMES[i];
        const b = DIRECTOR_KEYFRAMES[i + 1];
        if (tNorm >= a.t && tNorm <= b.t) {
            const local = (tNorm - a.t) / (b.t - a.t);
            const eased = local * local * (3 - 2 * local);
            state.camera.azimuth   = lerp(a.az,   b.az,   eased);
            state.camera.elevation = lerp(a.el,    b.el,   eased);
            state.camera.zoom      = lerp(a.zoom,  b.zoom, eased);
            applyCamera();
            break;
        }
    }

    if (tNorm < 1.0) {
        state.directorTimer = requestAnimationFrame(() =>
            directorStep(elapsed + 100, duration)
        );
    } else {
        state.directorActive = false;
        directorBtn.classList.remove("active");
    }
}

directorBtn.addEventListener("click", () => {
    state.directorActive = !state.directorActive;
    directorBtn.classList.toggle("active", state.directorActive);
    if (state.directorActive) {
        state.playing = true;
        playBtn.textContent = "Pause";
        playLoop();
        directorStep(0, 8000);
    } else {
        cancelAnimationFrame(state.directorTimer);
    }
});

// ─── Public API (called by Gemini Live) ──────────────────────────────────────

window.replayAPI = {
    orbitCamera(azimuth, elevation) {
        state.camera.azimuth   = azimuth;
        state.camera.elevation = Math.max(-85, Math.min(85, elevation));
        applyCamera();
        return { azimuth: state.camera.azimuth, elevation: state.camera.elevation };
    },

    jumpToFrame(frameIndex) {
        const idx = Math.max(0, Math.min(state.totalFrames - 1, frameIndex));
        state.currentFrame = idx;
        slider.value = idx;
        updateFrameLabel();
        loadFrame(idx);
        return { frame: idx };
    },

    setPlaybackSpeed(speed) {
        state.playbackSpeed = Math.max(0.1, Math.min(5.0, speed));
        return { speed: state.playbackSpeed };
    },

    togglePlay() {
        state.playing = !state.playing;
        playBtn.textContent = state.playing ? "Pause" : "Play";
        if (state.playing) playLoop();
        return { playing: state.playing };
    },

    zoomCamera(level) {
        state.camera.zoom = Math.max(1.0, Math.min(20, level));
        applyCamera();
        return { zoom: state.camera.zoom };
    },

    resetView() {
        state.camera = { azimuth: 0, elevation: 15, zoom: 5.0 };
        state.currentFrame = state.heroFrame;
        slider.value = state.heroFrame;
        updateFrameLabel();
        applyCamera();
        return { camera: { ...state.camera }, frame: state.currentFrame };
    },

    toggleDirectorMode() {
        directorBtn.click();
        return { directorActive: state.directorActive };
    },

    getSceneInfo() {
        return {
            totalFrames: state.totalFrames,
            currentFrame: state.currentFrame,
            fps: state.fps,
            heroFrame: state.heroFrame,
            camera: { ...state.camera },
            playing: state.playing,
            directorActive: state.directorActive,
        };
    },

    showGapConfidence() {
        sceneInfo.textContent = "Gap confidence map: weak sector at ~45° azimuth";
        sceneInfo.style.color = "#fa0";
        setTimeout(() => {
            sceneInfo.textContent = `Replay — ${state.totalFrames} frames · ${state.fps}fps`;
            sceneInfo.style.color = "";
        }, 4000);
        return { shown: true };
    },
};

// ─── Init ─────────────────────────────────────────────────────────────────────

initScene();
