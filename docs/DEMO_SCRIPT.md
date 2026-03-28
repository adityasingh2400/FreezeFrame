# Replay — 60-Second Demo Script

## The Hook (10 seconds)

> "What if you could freeze any moment in time, then walk around inside it?
> We built a system that takes video from 4 phone cameras, and in under a minute,
> turns it into an explorable 4D scene you can scrub through in your browser."

**Action:** Viewer is already open showing the hero frame. Slowly orbit the camera.

## The Demo (35 seconds)

**Action 1: Orbit** (8 seconds)
Slowly orbit 180 degrees around the frozen hero frame. Let judges see the 3D quality.

> "This is one moment in time, captured from 4 angles, reconstructed as
> 3D Gaussian splats. I can look at it from any angle."

**Action 2: Time scrub** (12 seconds)
Start dragging the timeline slider slowly. Let the scene animate.

> "But here's the thing that makes this different from every other Gaussian splat
> demo. Watch the timeline."
>
> (scrub forward slowly)
>
> "Time AND space. I can move through the moment while orbiting around it.
> That's 80 frames of volumetric video in your browser tab."

**Action 3: Speed demo** (5 seconds)
Hit play, let it loop at 1x speed while continuing to orbit.

> "Real-time playback at 30fps. No plugins, no downloads, just a URL."

**Action 4: Pipeline flex** (10 seconds)
Stop playback. Switch to a split-screen or terminal showing the pipeline output.

> "The whole pipeline runs in 51 seconds on a single GPU. We replaced the
> traditional 27-minute initialization step with VGGT, a new model from Meta
> that does camera pose estimation 225x faster. One forward pass instead of
> pairwise matching."

## The Close (15 seconds)

> "Sports replays, concert moments, crime scene reconstruction, heritage
> preservation. Any moment that matters, captured from phones, explorable
> forever. This is Replay."

**Action:** Switch back to viewer, hit Director mode (the cinematic auto-orbit),
let it play as judges ask questions.

---

## Judge Q&A Prep

**"How is this different from NeRF / existing 3D capture?"**
> NeRF gives you one frozen moment. We give you time. 80 frames at 30fps,
> each independently reconstructed. And it runs in a browser, not a CUDA app.

**"What's the pipeline?"**
> 4 phones → frame extraction → VGGT (camera poses in 0.15s per frame) →
> Gaussian splatting training → web viewer. Under a minute on an A100.

**"What's VGGT?"**
> Meta's CVPR 2025 Best Paper. A transformer that estimates 3D camera poses
> from multiple views in a single forward pass. It replaced COLMAP/MASt3R
> which took 20 seconds per frame with pairwise matching. VGGT does it in
> 0.15 seconds.

**"Can this work with more cameras?"**
> VGGT handles 1 to 200+ images. More cameras = better reconstruction.
> 4 is the minimum viable setup, but 8-12 would be ideal for production.

**"What about real-time?"**
> The viewer is real-time (30fps playback). The reconstruction pipeline is
> near-real-time (51 seconds for 80 frames). With optimization, sub-10-second
> pipelines are achievable.

---

## Demo Day Checklist

- [ ] Viewer open and loaded BEFORE judges arrive (never show a loading screen)
- [ ] Hero frame showing something visually interesting (not a blank wall)
- [ ] Mouse positioned on the timeline slider for smooth scrub demo
- [ ] Director mode tested and working for the "cinematic close"
- [ ] Terminal with pipeline output ready to show (screenshot or live)
- [ ] Backup: screen recording of the demo in case of technical failure
