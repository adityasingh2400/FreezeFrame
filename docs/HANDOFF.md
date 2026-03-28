# AGENT HANDOFF — Replay Project Status
## Written: Mar 27, 2026 ~11:30 PM (updated)

## What This Project Is
A 4D sports replay engine for a hackathon. Upload multi-angle phone videos of a sports moment → reconstruct as a navigable 3D scene over time → interactive viewer with orbit/zoom/time-scrub → Gemini Live voice control.

## Team
- **Aditya** (user) — 4DGS training (Stage 3), viewer, overall lead
- **Arshia** — Stage 1 (video preprocessing) — DONE
- **Divij** — Stage 2 (COLMAP pose recovery) — DONE, output on GitHub
- **Mia** — Cloud infra + BulletGen gap detection — working on it

## Current Git State
- Repo: https://github.com/adityasingh2400/Replay
- Branch: `main` — just merged Divij's branch, has everything
- Last commit: `e9e9452` (merge of origin/divij)
- The 4DGaussians repo is cloned locally at `/Users/aditya/Desktop/Replay/4DGaussians/` but NOT in git (it's a separate repo)

## What's Done
1. **Stage 1 (Arshia)**: 4 cameras × 80 frames, 1-indexed JPGs, `cam01/`-`cam04/`, 720×1280 vertical, synced via audio clap detection. Files at `scene/images/cam01-04/frame_00001-00080.jpg` + `scene/metadata.json`
2. **Stage 2 (Divij)**: COLMAP recovered 3/4 cameras (45 registered images = 15 frames × 3 cameras). Output at `scene/sparse/0/cameras.bin`, `scene/sparse/0/images.bin`, `scene/sparse/0/points3D.bin`, `scene/poses_bounds.npy` (shape 45×17)
3. **Viewer**: Complete Vite + Three.js + Spark.js app at `viewer/`. Loads Gaussian Splat files, orbit controls, timeline, play/pause, speed, camera presets, Director Mode. Demo splat at `viewer/public/demo/nike.splat`. Run with `cd viewer && npm run dev`.
4. **Training configs**: At `4DGaussians/arguments/multipleview/replay.py` (quality, 14k iters) and `replay_fast.py` (fast, 7k iters). Temporal grid resolution set to 40 (for 80 frames).
5. **Run script**: `run_training.py` at repo root — orchestrates training + export + viewer manifest generation.

## WHAT'S DONE SINCE LAST HANDOFF

### Data Restructure Script — DONE
`restructure_for_4dgs.py` at repo root. Fully tested locally. Handles ALL the issues:

**What we discovered from parsing Divij's COLMAP output:**
- 45 images registered: 15 each from cam02, cam03, cam04 (cam01 FAILED to register)
- Image names in images.bin: `cam03/frame_00051.jpg` style, NOT `imageN.jpg`
- Camera models: SIMPLE_RADIAL, camera IDs 2, 3, 4 (no ID 1)
- 754 sparse 3D points

**What the script does:**
1. Reads images.bin, picks best pose per camera (most 3D point matches)
2. Rewrites images.bin: `cam02/frame_00023.jpg` → `image2.jpg`, `cam03/frame_00068.jpg` → `image3.jpg`, `cam04/frame_00051.jpg` → `image4.jpg`
3. Remaps camera IDs to sequential 1,2,3 (4DGS hardcodes `cam_intrinsics[1]`)
4. Converts points3D.bin → points3D_multipleview.ply with voxel downsampling
5. Copies poses_bounds.npy → poses_bounds_multipleview.npy
6. Symlinks cam02-04 frame directories

**Verified**: the 4DGS loader name parsing `os.path.basename(extr.name)[5:-4]` correctly extracts `2`, `3`, `4` from `image2.jpg`, `image3.jpg`, `image4.jpg` → maps to `cam02/`, `cam03/`, `cam04/`.

### RunPod One-Shot Script — DONE
`runpod_setup.sh` at repo root. Handles the full pipeline:
1. Clones repo, installs system deps + Python packages
2. Builds 4DGS CUDA extensions (depth-diff-gaussian-rasterization, simple-knn)
3. Runs restructure_for_4dgs.py
4. Fast training → export per-frame PLYs
5. Quality training → export per-frame PLYs
6. Generates viewer manifest.json
7. Prints download commands

## WHAT NEEDS TO HAPPEN RIGHT NOW

### 1. Load RunPod Credits & Launch Pod
- Load ~$10 on RunPod
- Deploy: RTX A6000 ($0.40/hr, 48GB VRAM) or A100 with **PyTorch template**
- SSH in

### 2. Push These New Files to GitHub
```bash
git add restructure_for_4dgs.py runpod_setup.sh
git commit -m "Add data restructure script and RunPod one-shot training script"
git push
```

### 3. Run on RunPod
```bash
git clone https://github.com/adityasingh2400/Replay /workspace/Replay
cd /workspace/Replay && bash runpod_setup.sh
```

### 4. IMPORTANT: Frame Images
The frame JPGs (scene/images/cam01-04/) are NOT in git (gitignored). They need to be on the RunPod machine. Options:
- Upload from local machine: `scp -r scene/images/ root@<pod-ip>:<port>:/workspace/Replay/scene/images/`
- Or if they're on Google Drive, download them on the pod
- The restructure script symlinks to these, so they must exist before training

### Training Commands (for reference, the script runs these automatically):
```bash
cd /workspace/Replay/4DGaussians

# Fast test (~5 min on A100)
python3 train.py -s data/multipleview/replay --port 6017 --expname "multipleview/replay_fast" --configs arguments/multipleview/replay_fast.py

# Quality run (~15-20 min on A100)
python3 train.py -s data/multipleview/replay --port 6018 --expname "multipleview/replay" --configs arguments/multipleview/replay.py

# Export per-frame PLYs
python3 export_perframe_3DGS.py --iteration 14000 --configs arguments/multipleview/replay.py --model_path output/multipleview/replay
```

### After Training: Connect to Viewer
Per-frame .ply files go to `viewer/public/frames/` with a `manifest.json`:
```json
{
  "frames": ["time_00000.ply", "time_00001.ply", ...],
  "fps": 30,
  "baseDir": "/frames/"
}
```

## Other Parallel Work Streams
- **Mia**: Working on gap detection (Stage 5) + Nano Banana repair (Stage 6)
- **Gemini Live integration**: Not started yet — WebSocket proxy + function calling to control viewer
- **Greptile review**: PR #2 open at https://github.com/adityasingh2400/Replay/pull/2

## Key Files to Read
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/__init__.py` — dataset type detection
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/multipleview_dataset.py` — the loader that will consume our data
- `/Users/aditya/Desktop/Replay/4DGaussians/scene/dataset_readers.py` lines 596-633 — readMultipleViewinfos()
- `/Users/aditya/Desktop/Replay/4DGaussians/multipleviewprogress.sh` — reference preprocessing script
- `/Users/aditya/Desktop/Replay/4DGaussians/scripts/extractimages.py` — how official pipeline names images
- `/Users/aditya/Desktop/Replay/run_training.py` — our training orchestrator
- `/Users/aditya/Desktop/Replay/viewer/src/main.js` — viewer entry point
- `/Users/aditya/Desktop/Replay/Replay.pdf` — full project design doc

## User Preferences
- Uses `python3` not `python`
- On macOS (darwin 25.3.0)
- Prefers Claude-friendly messages for teammates (paste into Claude to implement)
- Wants things done properly, not shortcuts
- Hackathon deadline pressure but quality matters
