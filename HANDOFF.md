# AGENT HANDOFF — Replay Project Status
## Written: Mar 28, 2026 ~12:30 AM (updated)

## What This Project Is
A 4D sports replay engine for a hackathon. Upload multi-angle phone videos of a sports moment → reconstruct as a navigable 3D scene over time → interactive viewer with orbit/zoom/time-scrub → Gemini Live voice control.

## Team
- **Aditya** (user) — 4DGS training (Stage 3), viewer, overall lead
- **Arshia** — Stage 1 (video preprocessing) — DONE
- **Divij** — Stage 2 (COLMAP pose recovery) — DONE, dense + sparse on GitHub
- **Mia** — Cloud infra + BulletGen gap detection — working on it

## Current Git State
- Repo: https://github.com/adityasingh2400/Replay
- Branch: `aditya/training` — merged Divij's dense data, has all fixes
- Parent: merged `origin/divij` (dense point cloud + updated sparse)
- The 4DGaussians repo is cloned locally at `/Users/aditya/Desktop/Replay/4DGaussians/` but NOT in git (it's a separate repo)

## What's Done
1. **Stage 1 (Arshia)**: 4 cameras × 80 frames, 1-indexed JPGs, `cam01/`-`cam04/`, 720×1280 vertical, synced via audio clap detection. Files at `scene/images/cam01-04/frame_00001-00080.jpg` + `scene/metadata.json`
2. **Stage 2 (Divij)**: COLMAP recovered all 4 cameras (48 registered images). Dense reconstruction via patch_match_stereo produced 194,444 points. cam01 only got 3 frames with 0.04% match rate — effectively useless, excluded from training. cam02-04: 15 frames each, 1-2% match rate, reliable poses.
   - Sparse: `scene/sparse/0/{cameras,images,points3D}.bin` (757 pts)
   - Dense: `scene/dense/fused.ply` (194,444 pts)
   - Poses: `scene/poses_bounds.npy` (shape 48×17)
3. **Viewer**: Complete Vite + Three.js + Spark.js app at `viewer/`. Loads Gaussian Splat PLY files (Spark.js auto-detects gsplat PLY format), orbit controls, timeline, play/pause, speed, camera presets, Director Mode. Demo splat at `viewer/public/demo/nike.splat`. Run with `cd viewer && npm run dev`.
4. **Training configs**: At `4DGaussians/arguments/multipleview/replay.py` (quality, 14k iters) and `replay_fast.py` (fast, 7k iters). Temporal grid resolution set to 40 (for 80 frames).
5. **Run script**: `run_training.py` at repo root — orchestrates training + export + viewer manifest generation.

## CRITICAL FIXES APPLIED (Mar 28)

### Problem: Previous training produced incomprehensible garbage
Root causes identified and fixed:

**1. Sparse initialization (757 points → 194,444 dense points)**
- OLD: `restructure_for_4dgs.py` converted `points3D.bin` (757 sparse COLMAP triangulated points) to `points3D_multipleview.ply`. Starting 4DGS from 757 scattered points means Gaussians can't grow enough to fill the scene.
- FIX: Script now loads `scene/dense/fused.ply` (194,444 points from COLMAP patch_match_stereo), downsamples to ~50k, and writes that as `points3D_multipleview.ply`. 257x more initialization points = dramatically better coverage.
- Falls back to sparse if dense unavailable (with warning).

**2. cam01 poisoning training (bad poses injected noise)**
- OLD: cam01 registered 3 frames with 0.04% match rate (6-7 out of 16,000 features matched). Wildly inconsistent translation vectors across frames. COLMAP wasn't confident in cam01's pose at all — training against these frames corrupted the Gaussian field.
- FIX: `restructure_for_4dgs.py` now rejects cameras with <0.5% match rate. cam01 gets excluded. Only cam02-04 (1-2% match rate, consistent poses) are used.

**3. cam01 hardcode in 4DGS loader (would crash)**
- OLD: `multipleview_dataset.py` line 32 hardcoded `cam01` to count frames. If cam01 doesn't exist in the restructured data, FileNotFoundError.
- FIX: Loader now finds the first camera directory from the actual extrinsics data. Also, restructure script creates a `cam01` → `cam02` symlink as a safety fallback.

**4. Export produced 9 frames instead of 80**
- OLD: `export_perframe_3DGS.py` iterated over test cameras (3 frames per camera × 3 cameras = 9 viewpoints). Output: 9 PLY files. The viewer got a 9-frame "video" instead of smooth 80-frame replay.
- FIX: Script now exports one PLY per original frame. Auto-detects frame count from training data (240 samples / 3 cameras = 80 frames). Can also be overridden with `--num_frames 80`. Uses a lightweight TimeQuery object to sample the deformation network at each timestamp.

### Data Restructure Script — Updated
`restructure_for_4dgs.py` at repo root. What it now does:
1. Reads images.bin, **filters out unreliable cameras** (cam01 rejected at 0.04% match rate)
2. Picks best pose per accepted camera (most 3D point matches)
3. Rewrites images.bin: `cam02/frame_00023.jpg` → `image2.jpg`, etc.
4. Remaps camera IDs to sequential 1,2,3
5. **Loads dense fused.ply** (194k pts), downsamples to ~50k → `points3D_multipleview.ply`
6. Copies poses_bounds.npy → poses_bounds_multipleview.npy
7. Symlinks cam02-04 frame directories + cam01 compatibility shim

## HOW 4DGS WORKS (for the team)

4DGS does NOT preserve original videos. It learns a continuous 4D representation:

1. **Initialize**: Each dense point becomes a 3D Gaussian (position, color via spherical harmonics, opacity, scale, rotation).
2. **Coarse phase (iters 0-3000)**: Freezes time. Renders Gaussians from each camera viewpoint, compares to real photo, adjusts Gaussians via gradient descent. Densifies (splits/clones) in underrepresented areas. Learns static geometry.
3. **Fine phase (iters 3000-14000)**: Activates a deformation network (MLP + k-planes temporal grid). For each Gaussian at each time t, the network predicts position/rotation/scale deltas. Trained against all cameras at all timestamps. Learns motion.
4. **Query**: Given any time t ∈ [0,1], the deformation network produces the full Gaussian field at that moment. Render from any viewpoint via differentiable rasterization.
5. **Export**: For each of 80 timestamps, query the deformation network → get all Gaussian positions/colors/sizes at that time → write a standard 3DGS PLY file.
6. **Viewer**: Spark.js loads each per-frame PLY, swaps them on a timer = animation.

## WHAT NEEDS TO HAPPEN RIGHT NOW

### 1. Push fixes to GitHub
```bash
cd /Users/aditya/Desktop/Replay
git add restructure_for_4dgs.py 4DGaussians/scene/multipleview_dataset.py 4DGaussians/export_perframe_3DGS.py
git commit -m "Fix training pipeline: dense init, cam01 filtering, 80-frame export"
git push
```

### 2. On RunPod (or wherever training runs)
```bash
# Pull latest
cd /workspace/Replay && git pull

# Re-run restructure with dense data
python3 restructure_for_4dgs.py

# Train (quality)
cd 4DGaussians
python3 train.py -s data/multipleview/replay --port 6018 --expname "multipleview/replay" --configs arguments/multipleview/replay.py

# Export ALL 80 frames (not 9!)
python3 export_perframe_3DGS.py --iteration 14000 --configs arguments/multipleview/replay.py --model_path output/multipleview/replay --num_frames 80
```

### 3. IMPORTANT: Frame Images
The frame JPGs (scene/images/cam01-04/) are NOT in git (gitignored). They need to be on the training machine. Options:
- Upload from local machine: `scp -r scene/images/ root@<pod-ip>:<port>:/workspace/Replay/scene/images/`
- Or if they're on Google Drive, download them on the pod
- The restructure script symlinks to these, so they must exist before training

### 4. After Training: Connect to Viewer
Per-frame .ply files go to `viewer/public/frames/` with a `manifest.json`:
```json
{
  "frames": ["time_00000.ply", "time_00001.ply", ...],
  "fps": 30,
  "baseDir": "/frames/"
}
```
`run_training.py` handles this automatically if used.

## Expected Output Quality
With 3 cameras and 50k dense initialization points, expect:
- Recognizable scene geometry from the 3 covered angles
- Visible motion over the 80-frame sequence
- Artifacts/blur from angles not covered by any camera (the "back" of subjects)
- This is a hackathon demo — it won't be photorealistic, but should clearly show the sports moment evolving in 3D

## Other Parallel Work Streams
- **Mia**: Working on gap detection (Stage 5) + Nano Banana repair (Stage 6)
- **Gemini Live integration**: Not started yet — WebSocket proxy + function calling to control viewer
- **Greptile review**: PR #2 open at https://github.com/adityasingh2400/Replay/pull/2

## Key Files to Read
- `/Users/aditya/Desktop/Replay/restructure_for_4dgs.py` — data restructure (dense cloud, camera filtering)
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/multipleview_dataset.py` — the loader (fixed cam01 hardcode)
- `/Users/aditya/Desktop/Replay/4DGaussians/export_perframe_3DGS.py` — per-frame export (fixed 80 frames)
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/__init__.py` — dataset type detection
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/dataset_readers.py` lines 596-633 — readMultipleViewinfos()
- `/Users/aditya/Desktop/Replay/4DGaussians/utils/render_utils.py` — get_state_at_time()
- `/Users/aditya/Desktop/Replay/run_training.py` — training orchestrator
- `/Users/aditya/Desktop/Replay/viewer/src/main.js` — viewer entry point

## User Preferences
- Uses `python3` not `python`
- On macOS (darwin 25.3.0)
- Prefers Claude-friendly messages for teammates (paste into Claude to implement)
- Wants things done properly, not shortcuts
- Hackathon deadline pressure but quality matters
