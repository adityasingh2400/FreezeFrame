# Technology Landscape — Replay 4D Reconstruction Pipeline

## The Problem We're Solving

We have **4 synchronized phone videos** (cam01–cam04) of a sports moment, 80 frames each at 30fps (~2.7 seconds), 720×1280 vertical. The videos were taken simultaneously with ~90% temporal overlap. Goal: reconstruct a navigable 4D Gaussian Splat scene.

---

## Current Data Usage — The Numbers

### What We Captured
- 4 cameras × 80 frames = **320 images**
- All cameras saw roughly the same scene from different angles at the same times

### What COLMAP Registered
- **48 out of 320 images** (15.0%)
- cam01: **3/80 frames** (3.8%), match rate 0.04% — REJECTED as unreliable
- cam02: **15/80 frames** (18.8%), match rate 1.21%
- cam03: **15/80 frames** (18.8%), match rate 0.82%
- cam04: **15/80 frames** (18.8%), match rate 1.54%
- Only every ~5th frame was even submitted to COLMAP

### What 4DGS Actually Trains On
After `restructure_for_4dgs.py` runs:
- **1 pose per accepted camera** (picks the single best-matched frame)
- cam02: 80 frames, all rendered from frame 23's pose (the one with 1.42% match rate)
- cam03: 80 frames, all from frame 23's pose (1.17%)
- cam04: 80 frames, all from frame 23's pose (1.87%)
- **Total unique viewpoints: 3**
- **Total training samples: 240** (3 cameras × 80 frames)
- But all 80 frames per camera share the SAME pose — the only variation is appearance over time

### Effective Data Utilization
- **Spatial information used: 3 viewpoints out of potentially 320 = 0.9%**
- **Temporal information used: 80/80 frames per camera = 100%** (but from frozen viewpoints)
- **cam01 (25% of all data): 0% used — completely discarded**
- The pipeline captures temporal dynamics but has almost no spatial diversity for 3D reconstruction

---

## Fundamental Architecture Problem

```
CURRENT PIPELINE (broken):
  4 videos × 80 frames
       ↓
  COLMAP (SfM designed for unstructured photos, not video)
       ↓
  48/320 frames registered (85% discarded)
  Match rates: 0.04% to 1.87% (pathologically low)
       ↓
  restructure_for_4dgs.py picks 1 frame per camera
       ↓
  3 static viewpoints × 80 temporal frames → 4DGS training
       ↓
  3D coverage from 3 angles only = garbage reconstruction
```

### Root Causes
1. **COLMAP is the wrong tool.** It's designed for unstructured photo collections with lots of visual overlap. Phone videos from different angles of a sports scene have wide baselines and moving content — COLMAP's feature matching fails catastrophically (1% match rates).

2. **One pose per camera is a fundamental design flaw.** The restructure script was written to work around COLMAP's limitations, but it collapses all spatial information to 3 fixed viewpoints. 4DGS needs many viewpoints to learn 3D structure.

3. **The pipeline treats a multi-view video problem as a multi-photo problem.** Video has temporal coherence, motion priors, and sequential structure. COLMAP ignores all of this. Modern tools exploit it.

---

## Technology Landscape

### TIER 1: Pose Estimation Replacements (Replace COLMAP)

These tools replace the worst bottleneck — COLMAP's inability to handle video.

---

#### MASt3R-SfM (NAVER Labs)
**What it is:** Transformer-based dense 3D reconstruction + camera pose estimation. A foundation model for 3D vision trained on millions of image pairs.

**Why it matters:** Eliminates COLMAP entirely. Handles casual phone imagery natively. Produces dense point clouds AND camera poses simultaneously. No feature matching step — the transformer directly predicts 3D geometry.

**Key capabilities:**
- Works without camera calibration or poses
- Handles wide baselines (different phone angles) that destroy COLMAP
- Metric-scale 3D reconstruction
- Processes hundreds of images
- 0.36m translation error, 2.2° rotation error on benchmarks
- Scalable to any number of images

**What we'd get:** Poses for ALL 320 frames (vs current 48). Dense point cloud much richer than the 194k COLMAP produced. cam01 would likely be recovered.

**GitHub:** https://github.com/naver/mast3r (actively maintained, CVPR 2024)
**License:** CC BY-NC-SA 4.0 (non-commercial — fine for hackathon)
**Runs on:** Single GPU, minutes for our scale
**Maturity:** High — used by InstantSplat (NVIDIA), widely adopted

---

#### VGGSfM (Meta AI + Oxford)
**What it is:** Fully differentiable end-to-end SfM pipeline. Extracts 2D tracks, reconstructs cameras, builds point cloud, and runs bundle adjustment — all in one differentiable forward pass.

**Why it matters:** Ranked #1 in CVPR24 IMC Challenge for pose estimation. Supports video with 1000+ frames. Has built-in Gaussian Splatting integration. Dense point cloud and depth map export.

**Key capabilities:**
- End-to-end differentiable (can be fine-tuned)
- Handles video sequences natively (1000+ frames)
- Dense point cloud export
- Dynamic object filtering with masks
- Direct Gaussian Splatting integration

**GitHub:** https://github.com/facebookresearch/vggsfm (1.4k stars, active)
**License:** Check repo (Meta's typical BSD/MIT)
**Maturity:** High — CVPR 2024 Highlight, actively maintained

---

#### DUSt3R (NAVER Labs)
**What it is:** The foundation model that MASt3R builds on. Predicts dense 3D pointmaps from image pairs using a transformer. "Geometric 3D Vision Made Easy."

**Why it matters:** Simpler than MASt3R, extremely well-tested. Good fallback if MASt3R has issues.

**GitHub:** https://github.com/naver/dust3r
**License:** CC BY-NC-SA 4.0

---

#### Spann3R (UCL, 3DV 2025)
**What it is:** Extends DUSt3R with spatial memory for real-time incremental reconstruction. Predicts per-image pointmaps in a GLOBAL coordinate system (no pair-wise alignment needed).

**Why it matters:** Real-time, no test-time optimization, directly global coordinates. Perfect for video sequences — processes frames incrementally. Integrates with Nerfstudio.

**GitHub:** https://github.com/HengyiWang/spann3r (1.1k stars)
**Maturity:** Good — v1.01, 3DV 2025 paper

---

#### GloSplat (March 2026 — very recent)
**What it is:** Joint pose + Gaussian optimization during 3DGS training. Preserves SfM feature tracks as geometric anchors throughout training.

**Why it matters:** Two variants — GloSplat-F is COLMAP-free, GloSplat-A beats COLMAP-based baselines. Could eliminate SfM entirely and learn poses during Gaussian training.

**Paper:** https://arxiv.org/abs/2603.04847
**Maturity:** Pre-print, likely no public code yet

---

#### GLOMAP / FASTMAP (COLMAP improvements)
**What they are:** Global SfM pipelines that use COLMAP's feature extraction but solve the mapper globally instead of incrementally. GLOMAP is 10-100x faster than COLMAP. FASTMAP adds GPU acceleration for another 10x.

**Why they matter:** Drop-in COLMAP replacement if we want minimal pipeline changes. Same interface, much faster, sometimes better accuracy.

**Note:** GLOMAP is now deprecated and merged into COLMAP itself as the "global" mapper option.

---

### TIER 2: Full Pipeline Replacements (Replace COLMAP + 4DGS)

These tools could replace most or all of the manual pipeline.

---

#### InstantSplat (NVIDIA)
**What it is:** Sparse-view 3D Gaussian Splatting in seconds. Uses MASt3R as geometric backbone, then jointly optimizes Gaussians and camera poses.

**Why it matters:** 30x faster than COLMAP + 3DGS pipeline. Better visual quality (SSIM 0.37 → 0.76). Works from as few as 2-3 images. No SfM pipeline at all.

**Limitation:** 3D only (static scenes). Would need per-timestep reconstruction for 4D, or use as initialization for 4DGS.

**GitHub:** https://github.com/NVlabs/InstantSplat (NVIDIA official)
**License:** Check repo
**Maturity:** High — NVIDIA backed, active development

---

#### Instant4D
**What it is:** 4D Gaussian Splatting from monocular video in 2-10 minutes. Uses deep visual SLAM for geometry, trains 4DGS with 92% Gaussian pruning.

**Why it matters:** 30x speedup over baseline 4DGS. 29% quality improvement on benchmarks. Handles casual video without calibration. Could potentially be adapted for multi-view.

**Limitation:** Designed for monocular (single camera). Multi-view adaptation would require engineering.

**GitHub:** https://github.com/Zhanpeng1202/Instant4D
**Paper:** NeurIPS 2025
**Maturity:** Medium — academic code, recent

---

#### SyncTrack4D
**What it is:** Purpose-built pipeline for multi-view video → 4D reconstruction. Handles UNSYNCHRONIZED multi-view video input using dense 4D feature tracks and cross-video matching.

**Why it matters:** This is literally our use case. It:
- Extracts dense 4D feature tracks per video
- Matches across videos using Fused Gromov-Wasserstein optimal transport
- Aligns globally via Dynamic Time Warping
- Achieves sub-frame sync accuracy (<0.26 frames temporal error)
- 26.3 PSNR on Panoptic Studio dataset

**Limitation:** May be research-stage code. Need to check availability.

**Paper:** December 2025
**Maturity:** Research — check for public code

---

#### SplatFields (ECCV 2024)
**What it is:** Neural Gaussian Splats for sparse 3D and 4D reconstruction. Regularizes 3DGS specifically for sparse view scenarios.

**Why it matters:** Explicitly designed for the few-viewpoint problem we have. MIT licensed.

**GitHub:** https://github.com/markomih/SplatFields (188 stars)
**License:** MIT

---

### TIER 3: Infrastructure / Acceleration

---

#### Nerfstudio + gsplat
**What it is:** Modular framework for neural rendering with splatfacto (Gaussian Splatting). gsplat is the CUDA-accelerated rasterization backend (v1.5.3, July 2025).

**Why it matters:** Well-maintained infrastructure. Spann3R and VGGSfM integrate with it. If we rebuild on Nerfstudio, we get the ecosystem.

**GitHub:** https://github.com/nerfstudio-project/nerfstudio, https://github.com/nerfstudio-project/gsplat

---

#### 4DGS-1K
**What it is:** Optimized 4DGS achieving 1000+ FPS rendering through spatial-temporal pruning and active Gaussian masking. 41x storage reduction, 9x faster rasterization.

**Why it matters:** If we keep 4DGS, this could dramatically improve viewer performance and model size.

---

## Possible Architecture Rewrites

### Architecture A: MASt3R Drop-In (Minimal Change)
```
Videos → Frame extraction (existing) →
MASt3R-SfM (replaces COLMAP) →
  Output: per-frame poses for all 320 images + dense point cloud →
Rewritten restructure script (uses ALL poses, not 1 per camera) →
4DGS training (existing, but now with 320 viewpoints instead of 3) →
Viewer (existing)
```
**Effort:** ~3-4 hours. Only replaces COLMAP and restructure script.
**Impact:** 100x more spatial supervision. cam01 likely recovered. Same 4DGS training.

### Architecture B: VGGSfM + 4DGS (Moderate Change)
```
Videos → Frame extraction →
VGGSfM (end-to-end SfM with video support) →
  Output: poses + dense point cloud + depth maps →
4DGS training with rich initialization →
Viewer (existing)
```
**Effort:** ~4-5 hours. VGGSfM has GS integration built in.
**Impact:** Similar to A but potentially better video handling.

### Architecture C: InstantSplat per-timestamp + Temporal Fusion (Major Change)
```
Videos → Frame extraction →
For each timestamp t=0..79:
  Take 4 images (one from each camera at time t) →
  InstantSplat → instant 3D Gaussian field for time t →
Temporal fusion / deformation learning across 80 timesteps →
Viewer
```
**Effort:** ~5-6 hours. Novel approach, more engineering.
**Impact:** Each timestep gets full 3D from all cameras. Very different from current approach.

### Architecture D: SyncTrack4D (Full Replacement)
```
4 raw videos →
SyncTrack4D (handles everything: sync, poses, 4D reconstruction) →
Output: 4D Gaussian field →
Viewer
```
**Effort:** Unknown — depends on code availability and maturity.
**Impact:** If it works, replaces the entire pipeline with one tool.

### Architecture E: Instant4D per-camera + Multi-View Fusion (Creative)
```
For each camera:
  Video → Instant4D → 4D Gaussian field from that camera →
Fuse 4 per-camera 4D fields into one →
Viewer
```
**Effort:** ~4-5 hours.
**Impact:** Each camera contributes a full 4D reconstruction. Fusion is the hard part.

---

## Decision Matrix

| Approach | Effort | Risk | Data Usage | Quality Ceiling | Hackathon Feasible? |
|----------|--------|------|------------|----------------|-------------------|
| Current pipeline | Done | N/A | 0.9% spatial | Very low (3 views) | Already built, bad output |
| A: MASt3R drop-in | 3-4h | Low | ~100% spatial | Good (320 views) | YES — safest bet |
| B: VGGSfM + 4DGS | 4-5h | Low-Med | ~100% spatial | Good | YES |
| C: InstantSplat per-t | 5-6h | Medium | 100% spatial+temporal | Very high | Maybe |
| D: SyncTrack4D | Unknown | High | 100% | Potentially highest | Risky — code maturity |
| E: Instant4D fusion | 4-5h | Medium | 100% per-camera | High | Maybe |

---

## Key Constraints
- **Hackathon deadline** — limited hours remaining
- **GPU available** — RunPod with A100
- **Team**: Aditya (lead, 4DGS), Divij (COLMAP/poses), Arshia (preprocessing), Mia (infra)
- **Existing working pieces**: Frame extraction (done), viewer (done), 4DGS training config (done)
- **Non-commercial use** is fine (hackathon)
