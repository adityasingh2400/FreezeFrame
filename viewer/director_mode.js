/**
 * director_mode.js — Autonomous cinematic camera path (POST-MVP)
 *
 * Generates and plays back a cinematic camera path over the reconstructed scene.
 * Not a separate product — rides on the same scene and viewer as interactive mode.
 *
 * The camera choreography:
 *   1. Choose a strong opening angle
 *   2. Ease into the hero frame
 *   3. Slow down at the apex
 *   4. Orbit through the repaired sector (if gap repair ran)
 *   5. Zoom for dramatic emphasis
 *   6. Exit cleanly
 *
 * Keyframe format:
 *   { time: 0.0, azimuth: 45, elevation: 15, zoom: 1.0, speed: 1.0 }
 *   time is normalized [0, 1] over the duration
 */

const DEFAULT_KEYFRAMES = [
    { time: 0.0, azimuth: 0,   elevation: 20, zoom: 1.0, speed: 1.0 },
    { time: 0.2, azimuth: 45,  elevation: 15, zoom: 1.2, speed: 0.5 },
    { time: 0.5, azimuth: 90,  elevation: 10, zoom: 1.5, speed: 0.2 },
    { time: 0.7, azimuth: 180, elevation: 5,  zoom: 2.0, speed: 0.1 },
    { time: 0.9, azimuth: 270, elevation: 15, zoom: 1.5, speed: 0.3 },
    { time: 1.0, azimuth: 360, elevation: 20, zoom: 1.0, speed: 1.0 },
];

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function interpolateKeyframes(keyframes, t) {
    /**
     * Given normalized time t in [0, 1], interpolate between keyframes.
     * Returns { azimuth, elevation, zoom, speed }.
     */
    const clamped = Math.max(0, Math.min(1, t));

    for (let i = 0; i < keyframes.length - 1; i++) {
        const a = keyframes[i];
        const b = keyframes[i + 1];
        if (clamped >= a.time && clamped <= b.time) {
            const local = (clamped - a.time) / (b.time - a.time);
            const eased = local * local * (3 - 2 * local); // smoothstep
            return {
                azimuth: lerp(a.azimuth, b.azimuth, eased),
                elevation: lerp(a.elevation, b.elevation, eased),
                zoom: lerp(a.zoom, b.zoom, eased),
                speed: lerp(a.speed, b.speed, eased),
            };
        }
    }

    const last = keyframes[keyframes.length - 1];
    return { azimuth: last.azimuth, elevation: last.elevation, zoom: last.zoom, speed: last.speed };
}

// POST-MVP: export for use by viewer.js and Gemini Live toggle_director_mode
window.directorMode = {
    keyframes: DEFAULT_KEYFRAMES,
    interpolate: interpolateKeyframes,
    active: false,
    durationSeconds: 8.0,
};
