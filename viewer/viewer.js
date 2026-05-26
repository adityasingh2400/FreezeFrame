/**
 * viewer.js — Gaussian splat viewer with orbit/zoom/time controls
 *
 * Loads .ply/.splat files from output/frames/ and renders them using gsplat.js.
 * Implements orbit (mouse drag), zoom (scroll), and time scrub (slider).
 *
 * Mia: this is your primary file to implement. The HTML structure and controls
 * are wired up — you need to integrate gsplat.js for rendering.
 */

// ============================================================
// STATE
// ============================================================

const state = {
    currentFrame: 0,
    totalFrames: 0,
    fps: 30,
    playing: false,
    playbackSpeed: 1.0,
    heroFrame: 0,
    camera: {
        azimuth: 0,
        elevation: 15,
        zoom: 1.0,
    },
    frames: [],       // loaded frame data (per-timestep .ply/.splat)
    meta: null,        // output_meta.json contents
};

// ============================================================
// DOM
// ============================================================

const canvas = document.getElementById("scene-canvas");
const slider = document.getElementById("time-slider");
const frameLabel = document.getElementById("frame-label");
const playBtn = document.getElementById("play-btn");
const resetBtn = document.getElementById("reset-btn");
const loadingEl = document.getElementById("loading");
const loadingDetail = document.getElementById("loading-detail");

// ============================================================
// SCENE LOADING
// ============================================================

async function loadOutputMeta() {
    try {
        const resp = await fetch("/output/output_meta.json");
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

async function discoverFrames() {
    /**
     * TODO Mia: Implement frame discovery.
     *
     * Option A: Read output_meta.json to get num_frames, then construct
     *   URLs like /output/frames/frame_00000.ply, frame_00001.ply, etc.
     *
     * Option B: If only a single .splat demo file exists, load just that
     *   for a static (non-temporal) demo.
     *
     * Return: array of URLs to load.
     */
    const meta = await loadOutputMeta();
    if (meta) {
        state.meta = meta;
        state.totalFrames = meta.num_frames;
        state.fps = meta.fps || 30;
        state.heroFrame = meta.hero_frame || 0;

        const urls = [];
        for (let i = 0; i < meta.num_frames; i++) {
            const padded = String(i).padStart(5, "0");
            urls.push(`/output/frames/frame_${padded}.ply`);
        }
        return urls;
    }

    // Fallback: check for demo .splat file
    try {
        const resp = await fetch("/output/frames/nike.splat", { method: "HEAD" });
        if (resp.ok) {
            state.totalFrames = 1;
            return ["/output/frames/nike.splat"];
        }
    } catch {}

    return [];
}

async function initScene() {
    /**
     * TODO Mia: Initialize the gsplat.js renderer.
     *
     * 1. npm install gsplat (or load from CDN)
     * 2. Create a gsplat Scene + Camera + Renderer
     * 3. Attach to the canvas element
     * 4. Load the first frame's .ply/.splat
     * 5. Start the render loop
     *
     * gsplat.js docs: https://www.npmjs.com/package/gsplat
     */

    const frameUrls = await discoverFrames();

    if (frameUrls.length === 0) {
        loadingDetail.textContent = "No scene files found. Run the pipeline or 'make demo'.";
        return;
    }

    loadingDetail.textContent = `Found ${frameUrls.length} frames. Loading...`;

    // Update slider
    slider.max = Math.max(0, frameUrls.length - 1);
    slider.value = state.heroFrame;
    updateFrameLabel();

    // TODO: load and render the scene with gsplat.js
    loadingEl.classList.add("hidden");
    console.log(`Scene ready: ${frameUrls.length} frames, ${state.fps}fps`);
}

// ============================================================
// ORBIT / ZOOM CONTROLS
// ============================================================

let isDragging = false;
let lastMouse = { x: 0, y: 0 };

canvas.addEventListener("mousedown", (e) => {
    isDragging = true;
    lastMouse = { x: e.clientX, y: e.clientY };
});

window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - lastMouse.x;
    const dy = e.clientY - lastMouse.y;
    state.camera.azimuth += dx * 0.3;
    state.camera.elevation = Math.max(-85, Math.min(85, state.camera.elevation - dy * 0.3));
    lastMouse = { x: e.clientX, y: e.clientY };
    // TODO: update gsplat camera
});

window.addEventListener("mouseup", () => { isDragging = false; });

canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    state.camera.zoom = Math.max(0.1, Math.min(10, state.camera.zoom * (1 - e.deltaY * 0.001)));
    // TODO: update gsplat camera
}, { passive: false });

// ============================================================
// TIME CONTROLS
// ============================================================

function updateFrameLabel() {
    frameLabel.textContent = `${state.currentFrame} / ${state.totalFrames - 1}`;
}

slider.addEventListener("input", () => {
    state.currentFrame = parseInt(slider.value);
    updateFrameLabel();
    // TODO: swap to the current frame's .ply
});

playBtn.addEventListener("click", () => {
    state.playing = !state.playing;
    playBtn.textContent = state.playing ? "Pause" : "Play";
    if (state.playing) playLoop();
});

resetBtn.addEventListener("click", () => {
    state.camera = { azimuth: 0, elevation: 15, zoom: 1.0 };
    state.currentFrame = state.heroFrame;
    slider.value = state.currentFrame;
    updateFrameLabel();
    // TODO: update gsplat camera + swap frame
});

function playLoop() {
    if (!state.playing) return;
    state.currentFrame = (state.currentFrame + 1) % state.totalFrames;
    slider.value = state.currentFrame;
    updateFrameLabel();
    // TODO: swap to current frame's .ply
    setTimeout(playLoop, 1000 / (state.fps * state.playbackSpeed));
}

// ============================================================
// PUBLIC API (called by Gemini Live via gemini_live.js)
// ============================================================

window.replayAPI = {
    orbitCamera(azimuth, elevation) {
        state.camera.azimuth = azimuth;
        state.camera.elevation = Math.max(-85, Math.min(85, elevation));
        // TODO: update gsplat camera
        return { azimuth: state.camera.azimuth, elevation: state.camera.elevation };
    },

    jumpToFrame(frameIndex) {
        const idx = Math.max(0, Math.min(state.totalFrames - 1, frameIndex));
        state.currentFrame = idx;
        slider.value = idx;
        updateFrameLabel();
        // TODO: swap frame
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
        state.camera.zoom = Math.max(0.1, Math.min(10, level));
        // TODO: update gsplat camera
        return { zoom: state.camera.zoom };
    },

    resetView() {
        state.camera = { azimuth: 0, elevation: 15, zoom: 1.0 };
        state.currentFrame = state.heroFrame;
        slider.value = state.currentFrame;
        updateFrameLabel();
        return { camera: state.camera, frame: state.currentFrame };
    },

    getSceneInfo() {
        return {
            totalFrames: state.totalFrames,
            currentFrame: state.currentFrame,
            fps: state.fps,
            heroFrame: state.heroFrame,
            camera: { ...state.camera },
            playing: state.playing,
        };
    },
};

// ============================================================
// INIT
// ============================================================

initScene();
